"""Role → ISCO-08 resolver — two-tier (lexical, then LLM fallback).

Given a job ad's title / domain / must-have skills, pick the ISCO-08
occupation group whose ESCO skill set the matcher should score against.

Tier 1 (free): diacritics-insensitive match of the ad title + domain
against ESCO occupation labels (`occupations` table, both languages).
A strong hit resolves with zero LLM cost — the demo "Datový analytik"
lands on ISCO 2511 via the CS alt-label "datový analytik".

Tier 2 (LLM, cheap): no confident lexical hit → one `llm.call_json`
over a shortlist of the closest candidate occupations. Mirrors the
round-1 role-mapping hybrid: known roles resolve free, edge cases ask
the model.

`resolve_isco_for_ad(...)` returns `(isco_code, occupation_label, method)`
where `method` ∈ {"lexical", "llm", "unresolved"}. `isco_code` is None
when nothing fits — the matcher then skips ESCO enrichment entirely.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from cv_bau_students import llm
from cv_bau_students.db import get_session
from cv_bau_students.db_models import Occupation
from cv_bau_students.taxonomy.repo import normalize as _normalize

# Lexical thresholds. A multiword occupation label that appears verbatim
# inside the ad title is a strong signal; a single-word label only counts
# on an exact normalised equality (so "dat" can't spuriously match).
_MIN_SUBSTRING_LEN = 6
_LEXICAL_ACCEPT = 500  # min score to trust a lexical hit without the LLM
_SHORTLIST_SIZE = 30


def _labels_for(occ: Occupation) -> list[str]:
    return [occ.preferred_label, *(occ.alt_labels or [])]


def _load_occupations() -> list[Occupation]:
    with get_session() as session:
        return list(session.execute(select(Occupation)).scalars().all())


def _en_label_for_uri(occupations: Iterable[Occupation], uri: str, fallback: str) -> str:
    """EN preferred_label for the SAME occupation (by URI) — so a lexical
    hit on a CS alt-label shows the matched occupation, not just any en
    occupation that happens to share the ISCO group."""
    for occ in occupations:
        if occ.occupation_uri == uri and occ.lang == "en":
            return occ.preferred_label
    return fallback


def _en_label_for_isco(occupations: Iterable[Occupation], isco_code: str, fallback: str) -> str:
    """EN preferred_label for any occupation in the ISCO group — used for
    the LLM menu / fallback display where only a code is known."""
    for occ in occupations:
        if occ.isco_code == isco_code and occ.lang == "en":
            return occ.preferred_label
    return fallback


def _score_label(label_norm: str, haystack: str) -> int:
    """Higher = stronger lexical match of one occupation label vs. the ad text."""
    if not label_norm:
        return 0
    if label_norm == haystack:
        return 1000 + len(label_norm)
    multiword = " " in label_norm
    if (
        multiword
        and len(label_norm) >= _MIN_SUBSTRING_LEN
        and (label_norm in haystack or haystack in label_norm)
    ):
        return 500 + len(label_norm)
    return 0


def _token_overlap(label_norm: str, hay_tokens: set[str]) -> float:
    label_tokens = set(label_norm.split())
    if not label_tokens:
        return 0.0
    return len(label_tokens & hay_tokens) / len(label_tokens)


def _lexical_match(
    occupations: list[Occupation], haystack: str
) -> tuple[str, str, str, int] | None:
    """Best (isco_code, occupation_uri, preferred_label, score) by match."""
    best: tuple[str, str, str, int] | None = None
    for occ in occupations:
        for label in _labels_for(occ):
            score = _score_label(_normalize(label), haystack)
            if score and (best is None or score > best[3]):
                best = (occ.isco_code, occ.occupation_uri, occ.preferred_label, score)
    return best


def _shortlist(occupations: list[Occupation], haystack: str) -> list[tuple[str, str]]:
    """Top candidate (label, isco) pairs by token overlap, deduped by isco.

    Scans labels in BOTH languages so a Czech-titled ad with no English
    word overlap can still build a menu; the menu itself shows the EN
    label per ISCO group for a stable prompt.
    """
    hay_tokens = set(haystack.split())
    best_overlap: dict[str, float] = {}
    for occ in occupations:
        overlap = max(
            (_token_overlap(_normalize(lbl), hay_tokens) for lbl in _labels_for(occ)),
            default=0.0,
        )
        if overlap > 0 and overlap > best_overlap.get(occ.isco_code, 0.0):
            best_overlap[occ.isco_code] = overlap
    ranked = sorted(best_overlap.items(), key=lambda kv: kv[1], reverse=True)[:_SHORTLIST_SIZE]
    return [(_en_label_for_isco(occupations, isco, isco), isco) for isco, _ in ranked]


def _llm_pick(
    title: str, domain: str, must_have: list[str], shortlist: list[tuple[str, str]]
) -> str | None:
    """Tier-2 fallback. Returns a chosen isco_code or None."""
    valid = {isco for _, isco in shortlist}
    options = "\n".join(f"- {label} ({isco})" for label, isco in shortlist)
    prompt = llm.render_prompt(
        "resolve_isco",
        title=title or "—",
        domain=domain or "—",
        must_have=", ".join(must_have) or "—",
        options=options,
    )
    try:
        payload = llm.call_json(prompt, max_tokens=200)
    except (ValueError, RuntimeError):
        return None
    code = payload.get("isco_code")
    if code is None:
        return None
    code = str(code).strip()
    return code if code in valid else None


def resolve_isco_for_ad(
    title: str,
    domain: str | None = None,
    must_have: list[str] | None = None,
) -> tuple[str | None, str | None, str]:
    """Resolve an ad to (isco_code, occupation_label, method).

    method ∈ {"lexical", "llm", "unresolved"}. isco_code/occupation_label
    are None when nothing fits (matcher then skips ESCO enrichment).
    """
    must_have = must_have or []
    occupations = _load_occupations()
    if not occupations:
        return None, None, "unresolved"

    haystack = _normalize(f"{title} {domain or ''}")

    hit = _lexical_match(occupations, haystack)
    if hit is not None and hit[3] >= _LEXICAL_ACCEPT:
        isco_code, uri, label, _ = hit
        return isco_code, _en_label_for_uri(occupations, uri, label), "lexical"

    shortlist = _shortlist(occupations, haystack)
    if shortlist:
        code = _llm_pick(title, domain or "", must_have, shortlist)
        if code is not None:
            label = next((lbl for lbl, isco in shortlist if isco == code), code)
            return code, _en_label_for_isco(occupations, code, label), "llm"

    return None, None, "unresolved"
