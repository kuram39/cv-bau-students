#!/usr/bin/env python3
"""Load ESCO v1.2.x taxonomy into the local SQLite via the public REST API.

Pulls 14k+ skills with EN + CS preferredLabel and altLabels. Walks the
list endpoint with pagination (100 per page → ~142 calls). Idempotent:
on re-run, existing rows are updated rather than duplicated.

Hierarchy is intentionally skipped on the API path — each broader
relation requires a per-skill GET which would add ~14k extra calls.
When the user wants hierarchy, drop the ESCO ZIP into
`data/raw_esco/csv/` and the loader picks up `broaderRelationsSkillPillar.csv`.

Usage:
    python scripts/load_esco.py                      # full load
    python scripts/load_esco.py --limit 500          # quick smoke test
    python scripts/load_esco.py --languages en cs    # default
    python scripts/load_esco.py --resume             # resume from last offset

API: https://ec.europa.eu/esco/api
License: CC BY 4.0 (Commission Decision 2011/833/EU)
"""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import urllib.request

from sqlalchemy import select, update

from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import Skill, SkillAlias

ESCO_BASE = "https://ec.europa.eu/esco/api/resource/skill"
ESCO_SCHEME = "http://data.europa.eu/esco/concept-scheme/skills"

# Skip rows that fail to surface at least one English preferredLabel.
MIN_LABEL_CHARS = 2

# Reasonable backoff on the public API.
REQUEST_TIMEOUT_S = 20
SLEEP_BETWEEN_BATCHES_S = 0.05


def _fetch_page(language: str, offset: int, limit: int) -> dict:
    params = {
        "isInScheme": ESCO_SCHEME,
        "language": language,
        "limit": limit,
        "offset": offset,
    }
    url = f"{ESCO_BASE}?{urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_label(concept: dict, lang: str) -> str | None:
    """Pull the preferredLabel in the requested language."""
    labels = concept.get("preferredLabel") or {}
    return labels.get(lang) or labels.get(f"{lang}-001") or None


def _extract_alt_labels(concept: dict, lang: str) -> list[str]:
    alts = concept.get("alternativeLabel") or {}
    items = alts.get(lang) or []
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def _classify_skill_type(concept: dict) -> str:
    """Map ESCO skillType URI → short string."""
    types = concept.get("skillType") or []
    if not types:
        return "skill"
    type_uri = types[0] if isinstance(types, list) else types
    if isinstance(type_uri, dict):
        type_uri = type_uri.get("uri", "")
    tail = (type_uri or "").rsplit("/", 1)[-1].lower()
    if "knowledge" in tail:
        return "knowledge"
    if "language" in tail:
        return "language"
    if "transversal" in tail:
        return "transversal"
    return "skill"


def _persist_skill(
    *,
    uri: str,
    canonical_cs: str | None,
    canonical_en: str | None,
    alt_cs: list[str],
    alt_en: list[str],
    skill_type: str,
) -> int:
    """Upsert a single skill + its aliases."""
    canonical = canonical_cs or canonical_en
    if canonical is None or len(canonical) < MIN_LABEL_CHARS:
        return 0
    with get_session() as session:
        existing = session.execute(select(Skill).where(Skill.esco_uri == uri)).scalar_one_or_none()
        if existing is None:
            # Avoid collision when the same canonical_name was inserted via
            # the manual seed file — promote it to ESCO ownership.
            collision = session.execute(
                select(Skill).where(Skill.canonical_name == canonical)
            ).scalar_one_or_none()
            if collision is not None:
                session.execute(
                    update(Skill)
                    .where(Skill.id == collision.id)
                    .values(esco_uri=uri, canonical_name_en=canonical_en, skill_type=skill_type)
                )
                skill_id = collision.id
            else:
                row = Skill(
                    canonical_name=canonical,
                    canonical_name_en=canonical_en,
                    esco_uri=uri,
                    skill_type=skill_type,
                )
                session.add(row)
                session.flush()
                skill_id = row.id
        else:
            session.execute(
                update(Skill)
                .where(Skill.id == existing.id)
                .values(
                    canonical_name=canonical,
                    canonical_name_en=canonical_en,
                    skill_type=skill_type,
                )
            )
            skill_id = existing.id

        # Insert aliases — dedupe via UniqueConstraint(alias, lang, source).
        for alias_text, lang in [
            *((label, "cs") for label in alt_cs),
            *((label, "en") for label in alt_en),
        ]:
            alias_lower = alias_text.lower().strip()
            if not alias_lower:
                continue
            exists = session.execute(
                select(SkillAlias.id).where(
                    SkillAlias.alias == alias_lower,
                    SkillAlias.lang == lang,
                    SkillAlias.source == "esco",
                )
            ).scalar_one_or_none()
            if exists:
                continue
            session.add(
                SkillAlias(
                    alias=alias_lower,
                    canonical_id=skill_id,
                    lang=lang,
                    source="esco",
                )
            )
        return 1


def _state_path() -> Path:
    return Path(".esco_load_state.json")


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {"offset": 0}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"offset": 0}


def _save_state(state: dict) -> None:
    _state_path().write_text(json.dumps(state), encoding="utf-8")


def main_args(
    *,
    limit: int | None = None,
    page_size: int = 100,
    languages: list[str] | None = None,
    resume: bool = False,
    verbose: bool = True,
) -> int:
    """Programmatic entry point — usable from tests without argparse."""
    if languages is None:
        languages = ["cs", "en"]

    init_db()

    state = _load_state() if resume else {"offset": 0}
    offset = state.get("offset", 0)
    fetched = 0
    written = 0
    start = time.time()

    while True:
        try:
            # We pull EN as the primary list (gives us the URI + EN labels)
            # and re-pull CS per page for the Czech preferredLabel + altLabels.
            page_en = _fetch_page("en", offset=offset, limit=page_size)
        except Exception as exc:  # noqa: BLE001
            print(f"ESCO fetch failed at offset {offset}: {exc}", file=sys.stderr)
            _save_state({"offset": offset})
            return 2

        embedded = page_en.get("_embedded", {}) or {}
        if not embedded:
            break

        # Bulk CS fetch for the same URIs — saves N round-trips.
        uris = list(embedded.keys())
        cs_map: dict[str, dict] = {}
        if "cs" in languages:
            for chunk_start in range(0, len(uris), 30):
                chunk = uris[chunk_start : chunk_start + 30]
                try:
                    payload = _fetch_by_uris(chunk, language="cs")
                    cs_map.update(payload.get("_embedded", {}) or {})
                except Exception as exc:  # noqa: BLE001
                    print(f"  WARN: CS chunk fetch failed: {exc}", file=sys.stderr)
                time.sleep(SLEEP_BETWEEN_BATCHES_S)

        for uri, concept_en in embedded.items():
            concept_cs = cs_map.get(uri, {})
            canonical_en = _extract_label(concept_en, "en")
            canonical_cs = _extract_label(concept_cs, "cs") if concept_cs else None
            alt_en = _extract_alt_labels(concept_en, "en")
            alt_cs = _extract_alt_labels(concept_cs, "cs") if concept_cs else []
            skill_type = _classify_skill_type(concept_en)
            written += _persist_skill(
                uri=uri,
                canonical_cs=canonical_cs,
                canonical_en=canonical_en,
                alt_cs=alt_cs,
                alt_en=alt_en,
                skill_type=skill_type,
            )
            fetched += 1
            if limit and fetched >= limit:
                break

        offset += page_size
        _save_state({"offset": offset})
        if verbose:
            elapsed = time.time() - start
            rate = fetched / elapsed if elapsed > 0 else 0
            print(
                f"  offset {offset:>6} | fetched {fetched:>6} | "
                f"written {written:>6} | {rate:.1f}/s"
            )

        if limit and fetched >= limit:
            break
        if len(embedded) < page_size:
            break  # last page

    if verbose:
        print(f"\nFetched {fetched} skills, wrote {written} new/updated.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Load ESCO via REST API.")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N skills (smoke test).")
    parser.add_argument(
        "--languages",
        nargs="+",
        default=["cs", "en"],
        help="Preferred-label languages to merge (default: cs en).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="API page size. Max ~100 per ESCO docs.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Pick up from the last saved offset (.esco_load_state.json).",
    )
    args = parser.parse_args()
    return main_args(
        limit=args.limit,
        page_size=args.page_size,
        languages=args.languages,
        resume=args.resume,
    )


def _fetch_by_uris(uris: list[str], *, language: str) -> dict:
    """Bulk-fetch multiple skills in one call via the `uris` query param."""
    params = [("uris", uri) for uri in uris]
    params.append(("language", language))
    url = f"{ESCO_BASE}?{urlencode(params, doseq=True)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    sys.exit(main())
