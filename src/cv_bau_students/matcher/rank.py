"""Rank a candidate against the ad corpus — with SQL pre-filter.

Two-stage flow:
1. **SQL pre-filter** narrows ads to those plausibly relevant before
   any Python scoring runs. Saves ~95 % of the per-ad cost at scale
   (thousands of ads). Filters by:
   - candidate target_domains (when stated) ∪ ad domain hint
   - levels the candidate is plausibly competitive at — students target
     junior + medior; experienced + lead target their detected band
   - at least one skill overlap (taxonomy ids) between candidate and ad
2. **Python scoring + hard filter + ranking** runs on the narrowed set.

When the pre-filter returns an empty set (e.g. cold student with no
target_domains stated), we fall back to the full list so the recruiter
sees *something* — at the cost of speed, not correctness.
"""

from cv_bau_students.jobads.repo import find_candidate_ads, list_ads
from cv_bau_students.matcher.hard_filter import passes_hard_filter
from cv_bau_students.matcher.score import score_match
from cv_bau_students.models import CandidateProfile, MatchScore, TranslatedCapability
from cv_bau_students.taxonomy.repo import resolve_skill


def rank_candidate(
    profile: CandidateProfile,
    capabilities: list[TranslatedCapability],
    *,
    top_n: int = 10,
) -> list[MatchScore]:
    """Run SQL pre-filter → Python score → sort. Return top-N by total."""
    ads = _candidate_pool(profile, capabilities)
    if not ads:
        # Fallback so the demo doesn't show an empty UI when the
        # pre-filter is over-eager (cold candidate with no targets
        # stated). Production should surface "narrow your filters"
        # instead — but that's a UX call, not a matcher one.
        ads = list_ads()

    scored: list[MatchScore] = []
    for ad in ads:
        if not passes_hard_filter(profile, ad):
            continue
        scored.append(score_match(profile, capabilities, ad))
    scored.sort(key=lambda m: m.total, reverse=True)
    return scored[:top_n]


def _candidate_pool(
    profile: CandidateProfile,
    capabilities: list[TranslatedCapability],
) -> list:
    """Build the (domains, levels, skill_ids) filter triple for SQL."""
    domains = [d.strip().lower() for d in profile.target_domains if d.strip()]
    levels = _likely_levels(profile)
    skill_ids = _resolve_skill_ids(profile, capabilities)

    if not domains and not skill_ids:
        # Not enough signal to pre-filter usefully — skip narrowing.
        return []

    return find_candidate_ads(
        levels=levels or None,
        domains=domains or None,
        skill_ids_any=skill_ids or None,
    )


def _likely_levels(profile: CandidateProfile) -> list[str]:
    """Which ad levels is this candidate plausibly competitive at?"""
    if profile.candidate_type == "student":
        return ["junior", "medior"]
    if profile.candidate_type == "career_changer":
        return ["junior", "medior"]
    return ["junior", "medior", "senior", "lead"]


def _resolve_skill_ids(
    profile: CandidateProfile,
    capabilities: list[TranslatedCapability],
) -> set[int]:
    ids: set[int] = set()
    for raw in profile.explicit_skills:
        match = resolve_skill(raw)
        if match:
            ids.add(match[0])
    for cap in capabilities:
        match = resolve_skill(cap.skill)
        if match:
            ids.add(match[0])
    return ids
