"""3-axis matcher — skill_fit + bridge_fit + personal_fit.

- Skill fit: % of the ad's must_have + nice_to_have covered by the
  candidate's translated capabilities (via the taxonomy + hierarchy).
- Bridge fit: per-cell gap distance from the ad's (domain, level)
  checklist. Bridgeable months scale the score; experience-only gaps
  cap the score so a junior cannot "bridge" a senior position.
- Personal fit: text-overlap proxy between the candidate's summary +
  target_domains and the ad's raw_text. Replaced with an LLM call in
  later iterations; the proxy is good enough for the demo.

Output: `MatchScore` per ad with weighted total + confidence band.
Higher-confidence translated capabilities collapse the band; thin
profiles widen it.
"""

import statistics
from collections.abc import Iterable

from cv_bau_students.config import (
    WEIGHT_BRIDGE_FIT,
    WEIGHT_PERSONAL_FIT,
    WEIGHT_SKILL_FIT,
)
from cv_bau_students.levels.repo import bridge_plan
from cv_bau_students.models import (
    CandidateProfile,
    GapItem,
    JobAd,
    MatchScore,
    TranslatedCapability,
)
from cv_bau_students.taxonomy.repo import resolve_skill


def score_match(
    profile: CandidateProfile,
    capabilities: list[TranslatedCapability],
    ad: JobAd,
) -> MatchScore:
    """Score a single (candidate, ad) pair on the 3 axes + assemble."""
    candidate_skill_ids = _resolve_candidate_skill_ids(capabilities, profile)
    ad_must_ids = _resolve_iterable(ad.must_have)
    ad_nice_ids = _resolve_iterable(ad.nice_to_have)

    skill_fit = _skill_fit(candidate_skill_ids, ad_must_ids, ad_nice_ids)
    gaps = bridge_plan(ad.domain, ad.level, candidate_skill_ids)
    bridge_fit = _bridge_fit(gaps)
    personal_fit = _personal_fit(profile, ad)

    total = (
        WEIGHT_SKILL_FIT * skill_fit
        + WEIGHT_BRIDGE_FIT * bridge_fit
        + WEIGHT_PERSONAL_FIT * personal_fit
    )
    band = _confidence_band(capabilities)
    assert ad.id is not None
    return MatchScore(
        ad_id=ad.id,
        skill_fit=round(skill_fit, 1),
        bridge_fit=round(bridge_fit, 1),
        personal_fit=round(personal_fit, 1),
        total=round(total, 1),
        confidence_band=round(band, 1),
        bridge_plan=gaps,
    )


# --- axes --------------------------------------------------------------------


def _skill_fit(candidate: set[int], must: set[int], nice: set[int]) -> float:
    """Must-have hits weighted 2× nice-to-have.

    A candidate covering all musts + half of nices scores ~75 — leaves
    room for a perfect cover at 100. Pure must coverage (no nice
    overlap) caps at ~67.
    """
    must_score = (len(candidate & must) / max(1, len(must))) * 100 if must else 0.0
    nice_score = (len(candidate & nice) / max(1, len(nice))) * 100 if nice else 0.0
    if not must and not nice:
        return 0.0
    must_weight = 2.0 if must else 0.0
    nice_weight = 1.0 if nice else 0.0
    return (must_score * must_weight + nice_score * nice_weight) / (must_weight + nice_weight)


def _bridge_fit(gaps: list[GapItem]) -> float:
    """Closer-to-bridged → higher score. 100 = nothing missing; 0 = at least
    one experience-only gap that the candidate can't shortcut.

    Bridgeable gaps cost score proportional to their bridge_months;
    experience-only gaps short-circuit to a low cap so the recruiter
    sees the wall.
    """
    if not gaps:
        return 100.0
    if any(g.bridgeable_in_months is None for g in gaps):
        # Experience-only wall hit — cap at 35 regardless of other detail.
        return 35.0
    total_months = sum(g.bridgeable_in_months or 0 for g in gaps)
    # Scale: 0 months → 100, 12 months → 50, 24 months → 0.
    return max(0.0, 100.0 - (total_months / 24.0) * 100.0)


def _personal_fit(profile: CandidateProfile, ad: JobAd) -> float:
    """Lexical overlap between the candidate's summary + target_domains and
    the ad's raw_text. Cheap proxy — production swaps in an LLM scoring
    call. Returns 0..100.
    """
    haystack = ad.raw_text.lower()
    needles = []
    if profile.summary:
        needles.append(profile.summary.lower())
    needles.extend(d.lower().replace("-", " ") for d in profile.target_domains)
    if not needles:
        return 40.0  # neutral baseline when the candidate told us nothing
    hits = sum(1 for needle in needles if needle and needle in haystack)
    return min(100.0, 40.0 + 25.0 * hits)


def _confidence_band(capabilities: list[TranslatedCapability]) -> float:
    """Wider band when the average translator confidence is low.

    Average confidence 1.0 → ±5 band. Average 0.5 → ±18. Average 0.3 →
    ±26.
    """
    if not capabilities:
        return 30.0
    avg = statistics.mean(c.confidence for c in capabilities)
    # Linear: avg=1.0 → 5, avg=0.0 → 30.
    return max(5.0, 30.0 - 25.0 * avg)


# --- helpers -----------------------------------------------------------------


def _resolve_candidate_skill_ids(
    capabilities: list[TranslatedCapability],
    profile: CandidateProfile,
) -> set[int]:
    """Combine translated capabilities + explicit_skills into a single
    canonical id set.

    `HIGH_CONFIDENCE_THRESHOLD` is the floor for treating a translated
    capability as "candidate has this" without caveat — below that it
    still counts toward skill_fit (recruiter sees the caveat string)
    but the bridge_plan does NOT credit it.
    """
    ids: set[int] = set()
    for cap in capabilities:
        match = resolve_skill(cap.skill)
        if match:
            ids.add(match[0])
    for raw in profile.explicit_skills:
        match = resolve_skill(raw)
        if match:
            ids.add(match[0])
    return ids


def _resolve_iterable(names: Iterable[str]) -> set[int]:
    out: set[int] = set()
    for name in names:
        match = resolve_skill(name)
        if match:
            out.add(match[0])
    return out
