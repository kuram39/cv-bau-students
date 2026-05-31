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
    ROLE_BONUS_CAP,
    ROLE_BONUS_PER,
    ROLE_ESSENTIAL_GAP_SAMPLE,
    WEIGHT_BRIDGE_FIT,
    WEIGHT_PERSONAL_FIT,
    WEIGHT_SKILL_FIT,
)
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
    expected_skills_for_isco,
    names_for_ids,
    normalize,
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

    # ESCO-namespace sets — only for the target-role enrichment, so candidate
    # skills share the occupation map's id space. Base must/nice stays seed-space.
    candidate_esco_ids = _resolve_candidate_esco_ids(capabilities, profile)
    must_esco_ids = resolve_many_esco(ad.must_have)

    skill_fit, skill_fit_detail = _skill_fit(
        candidate_skill_ids,
        ad_must_ids,
        ad_nice_ids,
        ad,
        candidate_esco_ids,
        must_esco_ids,
    )
    gaps = bridge_plan(ad.domain, ad.level, candidate_skill_ids)
    has_rubric = checklist_exists(ad.domain, ad.level)
    bridge_fit = _bridge_fit(gaps, has_rubric=has_rubric)
    personal_fit = _personal_fit(profile, ad)

    # When no rubric exists, drop bridge axis from the weighted sum and
    # rebalance the remaining weights — otherwise we'd be averaging
    # against an unknown value, which inflates the total.
    if bridge_fit is None:
        denom = WEIGHT_SKILL_FIT + WEIGHT_PERSONAL_FIT
        total = (WEIGHT_SKILL_FIT * skill_fit + WEIGHT_PERSONAL_FIT * personal_fit) / denom
    else:
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
        # Bridge_fit is a float ≥ 0; encode "no rubric" as -1.0 so the
        # Pydantic Field(ge=0, le=100) doesn't reject it. The UI maps
        # -1.0 back to "N/A". Documented in the model.
        bridge_fit=round(bridge_fit, 1) if bridge_fit is not None else -1.0,
        personal_fit=round(personal_fit, 1),
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
    must_esco: set[int],
) -> tuple[float, SkillFitDetail]:
    """Must-have hits weighted 2× nice-to-have, plus a capped ESCO bonus.

    Base: a candidate covering all musts + half of nices scores ~75 —
    leaves room for a perfect cover at 100. Pure must coverage (no nice
    overlap) caps at ~67.

    Enrichment: when the ad resolved to an ISCO occupation, demonstrating
    occupation-essential ESCO skills *beyond* the recruiter's must-haves
    adds a capped bonus (config `ROLE_BONUS_*`). The base is authoritative;
    the bonus can only lift, never deflate — so scores stay interpretable
    and the ~300-skill ESCO set is never a denominator. Returns the score
    plus a `SkillFitDetail` audit trail for the recruiter panel.
    """
    base = _base_skill_fit(candidate, must, nice)
    # One name lookup for all three must/nice subsets (was three queries).
    namemap = names_for_ids((candidate & must) | (must - candidate) | (candidate & nice))
    detail = SkillFitDetail(
        matched_must=_sorted_names(candidate & must, namemap),
        missing_must=_sorted_names(must - candidate, namemap),
        matched_nice=_sorted_names(candidate & nice, namemap),
    )

    base, detail = _apply_role_enrichment(base, detail, candidate_esco, must_esco, ad)
    return min(100.0, base), detail


def _base_skill_fit(candidate: set[int], must: set[int], nice: set[int]) -> float:
    must_score = (len(candidate & must) / max(1, len(must))) * 100 if must else 0.0
    nice_score = (len(candidate & nice) / max(1, len(nice))) * 100 if nice else 0.0
    if not must and not nice:
        return 0.0
    must_weight = 2.0 if must else 0.0
    nice_weight = 1.0 if nice else 0.0
    return (must_score * must_weight + nice_score * nice_weight) / (must_weight + nice_weight)


def _apply_role_enrichment(
    base: float,
    detail: SkillFitDetail,
    candidate_esco: set[int],
    must_esco: set[int],
    ad: JobAd,
) -> tuple[float, SkillFitDetail]:
    """Fold ESCO occupation skill coverage into skill_fit + the audit.

    Uses the ESCO-namespace candidate set so it actually intersects the
    occupation map. Counts the occupation's essential ∪ optional skills
    (optional is where common tools like SQL land in ESCO). Capped bonus,
    base untouched — enrichment only lifts.
    """
    # Prefer the recruiter-curated target set (small, interpretable) over the
    # full ESCO essential∪optional fallback. Curated can apply even without an
    # ISCO code (recruiter picked skills directly).
    curated = get_target_skills(ad.id) if ad.id is not None else None
    if curated:
        role_set = curated.get("core", set()) | curated.get("optional", set())
        source = "curated"
    elif ad.isco_code:
        role_set = set(expected_skills_for_isco(ad.isco_code, "essential")) | set(
            expected_skills_for_isco(ad.isco_code, "optional")
        )
        source = "isco"
    else:
        return base, detail
    # Mark the detail enriched ONLY once role_set is known non-empty — else an
    # ISCO with no skill_industry_map rows would render a bogus "0/0 · ISCO
    # None" coverage line (target_source set but isco_code never populated).
    if not role_set:
        return base, detail
    detail.target_source = source

    evidenced = candidate_esco & role_set
    extra = evidenced - must_esco  # role skills beyond the recruiter must-haves
    bonus = min(ROLE_BONUS_CAP, len(extra) * ROLE_BONUS_PER)

    missing_sample = set(sorted(role_set - candidate_esco)[:ROLE_ESSENTIAL_GAP_SAMPLE])
    namemap = names_for_ids(evidenced | missing_sample)  # one lookup for both lists
    detail.isco_code = ad.isco_code
    detail.occupation_label = ad.isco_occupation_label
    detail.role_essential_total = len(role_set)
    detail.role_essential_evidenced = len(evidenced)
    detail.role_essential_matched = _sorted_names(evidenced, namemap)
    detail.role_essential_missing = _sorted_names(missing_sample, namemap)
    detail.bonus_applied = round(bonus, 1)
    return base + bonus, detail


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


_PERSONAL_FIT_STOPWORDS = frozenset(
    # tiny cs+en function-word set; keeps content tokens only
    "a i o u v k s z na se si je to the of and to in for with on at as by".split()
)


def _personal_fit(profile: CandidateProfile, ad: JobAd) -> float:
    """Content-token overlap between the candidate's summary + target_domains
    and the ad's raw_text. Cheap proxy — production swaps in an LLM scoring
    call. Returns 0..100.

    Token-set overlap (not substring `in`): substring matching fired "SQL"
    inside "NoSQL" and missed "datová" vs "data"; tokenizing on the
    diacritics-stripped `normalize()` form fixes both. Short tokens + a small
    stopword set are dropped so only meaningful overlap scores.
    """

    def _content_tokens(text: str) -> set[str]:
        return {
            t for t in normalize(text).split() if len(t) > 2 and t not in _PERSONAL_FIT_STOPWORDS
        }

    haystack = _content_tokens(ad.raw_text)
    needles = _content_tokens(profile.summary or "")
    for domain in profile.target_domains:
        needles |= _content_tokens(domain.replace("-", " "))
    if not needles:
        return 40.0  # neutral baseline when the candidate told us nothing
    overlap = len(needles & haystack)
    return min(100.0, 40.0 + 8.0 * overlap)


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
