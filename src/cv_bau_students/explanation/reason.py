"""LLM #4 — produce a recruiter-facing rationale per (candidate, ad) match.

Cached via the `reasoning_cache` table: same (candidate_id, ad_id,
prompt_hash) returns the previously generated text. Prompt hash is the
sha256 of the rendered prompt body PLUS the generation settings (model +
thinking mode), so any change to the inputs (profile, capabilities, ad,
scores) OR to how the text is generated invalidates the cache — otherwise
a model/thinking switch would keep serving stale rationales.
"""

import hashlib
import json

from sqlalchemy import select

from cv_bau_students import llm
from cv_bau_students.config import LLM_MODEL, LLM_THINK_ENABLED
from cv_bau_students.db import get_session
from cv_bau_students.db_models import ReasoningCache
from cv_bau_students.jobads.repo import list_ads
from cv_bau_students.models import (
    CandidateProfile,
    JobAd,
    MatchScore,
    TranslatedCapability,
)


def reason(
    profile: CandidateProfile,
    capabilities: list[TranslatedCapability],
    match: MatchScore,
    ad: JobAd,
    *,
    candidate_id: int | None = None,
) -> str:
    """Return the rendered rationale text. Cached when candidate_id given."""
    prompt = llm.render_prompt(
        "reasoning",
        candidate_type=profile.candidate_type,
        profile_json=json.dumps(profile.model_dump(), ensure_ascii=False),
        capabilities_json=json.dumps([c.model_dump() for c in capabilities], ensure_ascii=False),
        match_json=json.dumps(match.model_dump(), ensure_ascii=False),
        ad_json=json.dumps(ad.model_dump(), ensure_ascii=False),
        language=profile.language,
    )
    # Key the cache on the prompt AND the generation settings (model +
    # EFFECTIVE thinking mode). think=True only takes effect when
    # LLM_THINK_ENABLED is on, so the key must reflect the effective mode —
    # otherwise flipping CV_BAU_STUDENTS_THINK=1 for the quality A/B keeps
    # serving the old no-thinking rationale until the cache is cleared.
    cache_key = f"model={LLM_MODEL}|think={LLM_THINK_ENABLED}|{prompt}"
    prompt_hash = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()

    if candidate_id is not None and match.ad_id is not None:
        cached = _cache_lookup(candidate_id, match.ad_id, prompt_hash)
        if cached is not None:
            return cached

    # Interpretive call — adaptive thinking improves the recruiter rationale
    # (strengths / gaps / interview-prompt synthesis). Result is cached, so the
    # extra cost is paid at most once per (candidate, ad, prompt).
    payload = llm.call_json(prompt, think=True)
    rationale = json.dumps(payload, ensure_ascii=False)

    if candidate_id is not None and match.ad_id is not None:
        _cache_store(candidate_id, match.ad_id, prompt_hash, rationale)

    return rationale


def reason_for_ranking(
    profile: CandidateProfile,
    capabilities: list[TranslatedCapability],
    matches: list[MatchScore],
    *,
    top_n: int = 5,
    candidate_id: int | None = None,
) -> list[MatchScore]:
    """Attach a rationale to each of the top-N matches.

    Returns a NEW list of MatchScore objects with the `reasoning` field
    filled; the original matches list stays untouched.
    """
    if not matches:
        return []
    ads_by_id = {ad.id: ad for ad in list_ads() if ad.id is not None}
    out: list[MatchScore] = []
    for match in matches[:top_n]:
        ad = ads_by_id.get(match.ad_id)
        if ad is None:
            out.append(match)
            continue
        rationale = reason(profile, capabilities, match, ad, candidate_id=candidate_id)
        out.append(match.model_copy(update={"reasoning": rationale}))
    if len(matches) > top_n:
        out.extend(matches[top_n:])
    return out


# --- cache helpers ----------------------------------------------------------


def _cache_lookup(candidate_id: int, ad_id: int, prompt_hash: str) -> str | None:
    with get_session() as session:
        row = session.execute(
            select(ReasoningCache).where(
                ReasoningCache.candidate_id == candidate_id,
                ReasoningCache.ad_id == ad_id,
                ReasoningCache.prompt_hash == prompt_hash,
            )
        ).scalar_one_or_none()
        return row.rationale if row else None


def _cache_store(candidate_id: int, ad_id: int, prompt_hash: str, rationale: str) -> None:
    with get_session() as session:
        session.add(
            ReasoningCache(
                candidate_id=candidate_id,
                ad_id=ad_id,
                prompt_hash=prompt_hash,
                rationale=rationale,
            )
        )
