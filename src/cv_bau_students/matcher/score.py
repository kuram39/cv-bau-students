"""Candidate–ad scorer: skill coverage headline + bridge-fit secondary signal.

- Skill fit (headline, 0–100 %): coverage of the recruiter's curated target
  skill set (ESCO ids from the skill-picker), or the ad's must_have ∪
  nice_to_have if no curation exists. `total == skill_fit`.
- Bridge fit (secondary): how bridgeable the level/domain gaps are. Shown
  beside the headline as a "potential/growth" signal; NOT folded into total.
- Personal fit: retired from the product after PR #20 (was a weak lexical
  proxy). Schema field kept at 0.0; remove after a DB migration cycle.

Output: `MatchScore` per ad with headline % + confidence band.
Higher-confidence translated capabilities collapse the band; thin
profiles widen it.
"""

import statistics
from collections.abc import Iterable

from cv_bau_students.config import ROLE_ESSENTIAL_GAP_SAMPLE
from cv_bau_students.evidence import evidence_tier
from cv_bau_students.jobads.repo import get_target_skills
from cv_bau_students.levels.repo import bridge_plan, checklist_exists
from cv_bau_students.models import (
    CandidateProfile,
    GapItem,
    JobAd,
    MatchScore,
    SkillFitDetail,
    TranslatedCapability,
)
from cv_bau_students.taxonomy.repo import (
    names_for_ids,
    resolve_many_esco,
    resolve_skill,
    resolve_skill_esco,
)


def score_match(
    profile: CandidateProfile,
    capabilities: list[TranslatedCapability],
    ad: JobAd,
) -> MatchScore:
    """Score a single (candidate, ad) pair on the 3 axes + assemble."""
    candidate_skill_ids = _resolve_candidate_skill_ids(capabilities, profile)
    ad_must_ids = _resolve_iterable(ad.must_have)
    ad_nice_ids = _resolve_iterable(ad.nice_to_have)
    candidate_esco_ids = _resolve_candidate_esco_ids(capabilities, profile)

    # Evidence strength per skill id: the STRONGEST tier among the capabilities
    # that resolve to it. Includes the esco_term/skill fallback id (so a
    # capability matched without a stored skill_id still carries its tier), and
    # keeps the best tier when several capabilities (different source_types)
    # resolve to the same id.
    tier_by_id = _evidence_tier_by_id(capabilities)

    # MVP headline: skill coverage of the target set (recruiter-curated, else
    # the ad's must/nice). This is the comparator across students/experienced.
    skill_fit, skill_fit_detail = _skill_fit(
        candidate_skill_ids, ad_must_ids, ad_nice_ids, ad, candidate_esco_ids, tier_by_id
    )
    # Bridge fit kept as a SECONDARY "potential/growth" signal (how bridgeable
    # the gaps are) — shown beside, NOT folded into the headline. personal_fit
    # dropped from the product (was a weak lexical proxy); kept 0.0 for schema.
    gaps = bridge_plan(ad.domain, ad.level, candidate_skill_ids)
    has_rubric = checklist_exists(ad.domain, ad.level)
    bridge_fit = _bridge_fit(gaps, has_rubric=has_rubric)

    total = skill_fit  # skills-only headline
    band = _confidence_band(capabilities)
    assert ad.id is not None
    return MatchScore(
        ad_id=ad.id,
        skill_fit=round(skill_fit, 1),
        # Bridge_fit is a float ≥ 0; -1.0 encodes "no rubric" (UI shows N/A).
        bridge_fit=round(bridge_fit, 1) if bridge_fit is not None else -1.0,
        personal_fit=0.0,  # retired from the product (schema field kept)
        total=round(total, 1),
        confidence_band=round(band, 1),
        bridge_plan=gaps,
        skill_fit_detail=skill_fit_detail,
    )


# --- axes --------------------------------------------------------------------


def _skill_fit(
    candidate: set[int],
    must: set[int],
    nice: set[int],
    ad: JobAd,
    candidate_esco: set[int],
    tier_by_id: dict[int, str] | None = None,
) -> tuple[float, SkillFitDetail]:
    """MVP headline = % of the *target skill set* the candidate covers.

    Target set, in priority:
      1. recruiter-curated skills (the skill-picker) — ESCO ids; candidate
         compared in ESCO space. This is the recruiter's "score everyone on
         these base skills".
      2. else the ad's must_have ∪ nice_to_have (seed-namespace ids).
    The full ESCO essential∪optional set (~600) is deliberately NOT a
    denominator — coverage would collapse to ~0. A small recruiter-chosen set
    is what makes the % comparable across students vs experienced.
    Returns (coverage 0..100, SkillFitDetail audit).
    """
    # must/nice breakdown — always shown to the recruiter for context.
    mn = names_for_ids((candidate & must) | (must - candidate) | (candidate & nice))
    detail = SkillFitDetail(
        matched_must=_sorted_names(candidate & must, mn),
        missing_must=_sorted_names(must - candidate, mn),
        matched_nice=_sorted_names(candidate & nice, mn),
    )

    curated = get_target_skills(ad.id) if ad.id is not None else None
    if curated:
        target = curated.get("core", set()) | curated.get("optional", set())
        cand = candidate_esco
        detail.target_source = "curated"
    else:
        target = must | nice
        cand = candidate
        detail.target_source = "must_nice"

    if not target:
        return 0.0, detail

    matched = cand & target
    coverage = 100.0 * len(matched) / len(target)
    missing_sample = set(sorted(target - cand)[:ROLE_ESSENTIAL_GAP_SAMPLE])
    namemap = names_for_ids(matched | missing_sample)
    detail.isco_code = ad.isco_code
    detail.occupation_label = ad.isco_occupation_label
    detail.role_essential_total = len(target)
    detail.role_essential_evidenced = len(matched)
    detail.role_essential_matched = _sorted_names(matched, namemap)
    detail.role_essential_missing = _sorted_names(missing_sample, namemap)
    # Evidence strength per matched skill — strongest tier of the backing
    # capabilities (explicit-only matches have no capability → "weak"/claimed).
    tiers = tier_by_id or {}
    detail.matched_evidence = [
        (namemap[i], tiers.get(i, "weak")) for i in sorted(matched) if i in namemap
    ]
    return coverage, detail


def counterfactual_lifts(
    detail: SkillFitDetail | None, *, cap: int = 5
) -> list[tuple[str, int, int]]:
    """Actionable recourse: for each currently-missing target skill, what the
    coverage % would become if the candidate *evidenced* that one skill.

    Returns ``[(skill_name, current_pct, new_pct), …]`` (≤ ``cap`` items).
    Pure arithmetic from the existing ``SkillFitDetail`` counts — no re-score,
    no LLM. This is the GDPR/CJEU-endorsed counterfactual explanation (research
    #8) and doubles as the candidate's "what to demonstrate next".

    NB: every missing skill adds exactly one to the numerator, so the new % is
    the same for each — but we pair it per-skill so the UI can render concrete
    "Doložit «X» → N% → M%" lines. Kept deliberately simple so swapping in a
    plain "reason-codes" list (the contested alternative in #8) is cheap.
    """
    if detail is None:
        return []
    total = detail.role_essential_total
    if total <= 0:
        return []
    evidenced = detail.role_essential_evidenced
    if evidenced >= total:
        return []  # full coverage — nothing to recommend
    current = round(100.0 * evidenced / total)
    new = round(100.0 * (evidenced + 1) / total)
    return [(skill, current, new) for skill in detail.role_essential_missing[:cap]]


def _evidence_tier_by_id(capabilities: list[TranslatedCapability]) -> dict[int, str]:
    """Strongest evidence tier per resolved skill id across all capabilities.

    Resolves each capability to its skill id (stored `skill_id`, else the same
    `esco_term`/`skill` fallback the matcher uses) and keeps the best tier when
    several capabilities map to one id."""
    rank = {"weak": 0, "medium": 1, "strong": 2}
    out: dict[int, str] = {}
    for cap in capabilities:
        sid = cap.skill_id
        if sid is None:
            m = resolve_skill_esco(cap.esco_term or cap.skill)
            sid = m[0] if m else None
        if sid is None:
            continue
        tier = evidence_tier(cap.source_type)
        if sid not in out or rank[tier] > rank[out[sid]]:
            out[sid] = tier
    return out


def _resolve_candidate_esco_ids(
    capabilities: list[TranslatedCapability],
    profile: CandidateProfile,
) -> set[int]:
    """Candidate skills in the ESCO namespace, for target-role enrichment.

    Prefers each capability's stored/translated `skill_id` (the LLM-mapped
    ESCO link); falls back to resolving `esco_term`/`skill` for legacy rows
    that predate the mapping. Explicit CV skills are resolved straight into
    ESCO via the fuzzy resolver.
    """
    ids: set[int] = set()
    for cap in capabilities:
        if cap.skill_id is not None:
            ids.add(cap.skill_id)
            continue
        match = resolve_skill_esco(cap.esco_term or cap.skill)
        if match:
            ids.add(match[0])
    ids |= resolve_many_esco(profile.explicit_skills)
    return ids


def _sorted_names(skill_ids: Iterable[int], namemap: dict[int, str]) -> list[str]:
    """Sorted canonical names for the given ids, using a prebuilt name map
    (so callers batch one `names_for_ids` query instead of one per subset)."""
    return sorted(namemap[i] for i in skill_ids if i in namemap)


def _bridge_fit(gaps: list[GapItem], *, has_rubric: bool) -> float | None:
    """Closer-to-bridged → higher score. 100 = nothing missing; 0 = at least
    one experience-only gap that the candidate can't shortcut.

    Returns None when no checklist row exists for the ad's (domain,
    level) — the matcher then drops the axis from the weighted sum
    rather than fabricating a perfect-ready score from absent data.
    """
    if not has_rubric:
        return None
    if not gaps:
        return 100.0
    if any(g.bridgeable_in_months is None for g in gaps):
        # Experience-only wall hit — cap at 35 regardless of other detail.
        return 35.0
    total_months = sum(g.bridgeable_in_months or 0 for g in gaps)
    # Scale: 0 months → 100, 12 months → 50, 24 months → 0.
    return max(0.0, 100.0 - (total_months / 24.0) * 100.0)


def bridge_estimate(gaps: list[GapItem]) -> dict:
    """Human-graspable form of bridge_fit: how long to ready this candidate for
    the ad. Sums the per-gap `bridgeable_in_months`; gaps with no estimate
    (`bridgeable_in_months is None`) are the experience-only walls that no course
    or project shortcuts. Pure — derived from the stored bridge_plan."""
    months = sum(g.bridgeable_in_months or 0 for g in gaps if g.bridgeable_in_months is not None)
    bridgeable = sum(1 for g in gaps if g.bridgeable_in_months is not None)
    experience_only = sum(1 for g in gaps if g.bridgeable_in_months is None)
    return {
        "months": months,
        "bridgeable": bridgeable,
        "experience_only": experience_only,
        "gaps": len(gaps),
    }


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
