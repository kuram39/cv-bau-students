"""Candidate-type classifier — student / career-changer / experienced.

The profile extractor (LLM #1) already tags `candidate_type` inline.
This module re-applies the same heuristics in Python so the audit trail
is visible: if `candidate_type` from the LLM disagrees with the
heuristic, we record the disagreement in the analysis metadata and
trust the heuristic by default. Hard rules > prose vibes.

The heuristic uses only the structured profile fields (`total_work_years`,
`most_recent_grad_year`, `studying_in_progress`, `target_domains`,
`work_experience`). No LLM call here.
"""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

from cv_bau_students.config import (
    RECENT_GRAD_LOOKBACK_YEARS,
    STUDENT_MAX_WORK_YEARS,
)
from cv_bau_students.models import CandidateProfile, CandidateType, JobAd

# Above this fuzzy score a target_domain is considered to match a piece of work
# history → the candidate is staying in their field (experienced), not changing.
_DOMAIN_MATCH_THRESHOLD = 85


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _target_matches_history(profile: CandidateProfile, target_set: set[str]) -> str | None:
    """Does any target_domain line up with the candidate's actual work?

    Compares each target slug against every work entry's ROLE title (token-set:
    'data-analyst' ≈ 'Lead Data Analyst' = 100) and its free-text DOMAIN
    (partial: 'data-analyst' ≈ 'e-commerce / data analytics' = 92). Fuzzy on
    purpose: target_domains are normalized slugs while role/domain are free
    prose, so exact-match wrongly flagged staying-in-field analysts (Lucie,
    Petr) as career-changers. Returns the matched signal (for the audit
    reason), else None. Brigády are ignored — cross-domain by definition.
    """
    from rapidfuzz import fuzz

    targets = [_norm(t) for t in target_set if _norm(t)]
    for entry in profile.work_experience:
        if entry.is_brigada:
            continue
        role_n = _norm(entry.role or "")
        domain_n = _norm(entry.domain or "")
        for t in targets:
            if role_n and fuzz.token_set_ratio(t, role_n) >= _DOMAIN_MATCH_THRESHOLD:
                return f"role '{entry.role}'"
            if domain_n and fuzz.partial_ratio(t, domain_n) >= _DOMAIN_MATCH_THRESHOLD:
                return f"domain '{entry.domain}'"
    return None


@dataclass(frozen=True)
class ClassificationResult:
    """Output of the Python heuristic.

    `verdict` is the final candidate type. `llm_agrees` flags whether
    the profile extractor's tag matched our heuristic — recorded for
    audit + downstream meta-reflection.
    """

    verdict: CandidateType
    llm_agrees: bool
    reasons: list[str]


def classify(
    profile: CandidateProfile,
    *,
    target_ad: JobAd | None = None,
    today: date | None = None,
) -> ClassificationResult:
    """Apply the heuristic to a profile + report agreement with the LLM tag.

    `target_ad` (single-target app): when given, career_changer vs experienced
    is decided by whether the candidate's work history aligns with THIS ad's
    field — far more reliable than the self-stated `target_domains` (usually
    empty). Without an ad, falls back to the legacy target_domains comparison.
    """
    current_year = (today or date.today()).year
    reasons: list[str] = []

    # Judge on REAL (non-brigáda) experience. total_work_years dilutes brigády at
    # 0.3×, so brigáda-heavy histories could cross the threshold without real
    # career years. Fall back to total_work_years for legacy profiles (None).
    real_years = (
        profile.real_work_years if profile.real_work_years is not None else profile.total_work_years
    )

    # Student rules — order matters.
    if profile.studying_in_progress and real_years < STUDENT_MAX_WORK_YEARS:
        reasons.append(
            f"studying_in_progress=True AND real_work_years"
            f" ({real_years}) < {STUDENT_MAX_WORK_YEARS}"
        )
        verdict: CandidateType = "student"
    elif (
        profile.most_recent_grad_year is not None
        and profile.most_recent_grad_year >= current_year - RECENT_GRAD_LOOKBACK_YEARS
        and real_years < STUDENT_MAX_WORK_YEARS
    ):
        reasons.append(
            f"fresh grad — most_recent_grad_year"
            f" ({profile.most_recent_grad_year}) >="
            f" {current_year - RECENT_GRAD_LOOKBACK_YEARS}"
            f" AND real_work_years ({real_years}) < {STUDENT_MAX_WORK_YEARS}"
        )
        verdict = "student"
    else:
        verdict = _classify_changer_vs_experienced(profile, reasons, target_ad, real_years)

    return ClassificationResult(
        verdict=verdict,
        llm_agrees=(profile.candidate_type == verdict),
        reasons=reasons,
    )


def _classify_changer_vs_experienced(
    profile: CandidateProfile,
    reasons: list[str],
    target_ad: JobAd | None = None,
    real_years: float | None = None,
) -> CandidateType:
    """experienced vs career_changer.

    With a `target_ad` (single-target app): career_changer ⟺ ≥2y work AND the
    work history is in a DIFFERENT field than the ad → switching INTO it; aligned
    history → experienced. Without an ad: legacy self-stated target_domains
    comparison (vague aspiration alone is not evidence of a change).
    """
    if real_years is None:
        real_years = (
            profile.real_work_years
            if profile.real_work_years is not None
            else profile.total_work_years
        )
    # Too little REAL (non-brigáda) work → early-career "student / potential"
    # bucket, NOT experienced. A non-studying, non-fresh-grad person with <2y real
    # work (career gap, re-entry, late starter) has no tenure to stand on →
    # judged on potential. "experienced" is reserved for ≥2y real work.
    if real_years < STUDENT_MAX_WORK_YEARS:
        reasons.append(
            f"real_work_years ({real_years}) < {STUDENT_MAX_WORK_YEARS}"
            " — too little real experience → student/potential"
        )
        return "student"

    if not profile.work_experience:
        reasons.append("no work history — student/potential")
        return "student"

    # Brigády are excluded from the career signal (cross-domain by definition).
    # ONLY brigáda history = no real career experience → student/potential, not
    # experienced and not career_changer.
    if not any(not w.is_brigada for w in profile.work_experience):
        reasons.append("only brigáda work — no real career experience → student/potential")
        return "student"

    # Preferred path: classify relative to the actual target ad's field.
    if target_ad is not None:
        aligned = _aligns_with_target_ad(profile, target_ad)
        if aligned is not None:
            reasons.append(f"work history aligns with target ad ({aligned}) — experienced")
            return "experienced"
        families = ", ".join(sorted(_family_distribution(profile))) or "—"
        reasons.append(
            f"work history ({families}) in a different field than the target ad"
            f" ({target_ad.domain or target_ad.title!r}) — career_changer"
        )
        return "career_changer"

    # Fallback (no ad): self-stated target_domains vs work history.
    if not profile.target_domains:
        reasons.append("no target ad + no target_domains stated — experienced by default")
        return "experienced"
    target_set = {d.lower() for d in profile.target_domains}
    matched = _target_matches_history(profile, target_set)
    if matched is not None:
        reasons.append(f"target_domains match work history ({matched}) — experienced")
        return "experienced"
    families = ", ".join(sorted(_family_distribution(profile))) or "—"
    reasons.append(
        f"target_domains {sorted(target_set)} match no work role/domain"
        f" (history: {families}) — career_changer"
    )
    return "career_changer"


def _aligns_with_target_ad(profile: CandidateProfile, ad: JobAd) -> str | None:
    """Does any non-brigáda work entry's role/domain align with the TARGET AD's
    field? Compares against the ad's domain + title via partial_ratio (catches
    'Analytik' inside 'Datový analytik', 'data analytics' ~ 'data-analyst').
    Returns the matched signal, else None (→ different field → career_changer)."""
    from rapidfuzz import fuzz

    ad_fields = [f for f in (_norm(ad.domain or ""), _norm(ad.title or "")) if f]
    for entry in profile.work_experience:
        if entry.is_brigada:
            continue
        for txt in (entry.role, entry.domain):
            t = _norm(txt or "")
            if not t:
                continue
            for af in ad_fields:
                if (
                    max(fuzz.partial_ratio(t, af), fuzz.partial_ratio(af, t))
                    >= _DOMAIN_MATCH_THRESHOLD
                ):
                    return f"{entry.role or entry.domain!r} ~ {ad.domain or ad.title!r}"
    return None


def _family_distribution(profile: CandidateProfile) -> Counter:
    """Count work_experience entries by their declared `domain` field.

    Brigády are excluded — they're cross-domain by definition for the
    candidate-type signal, even if they happen to land in the target
    family by coincidence.
    """
    counter: Counter = Counter()
    for entry in profile.work_experience:
        if entry.is_brigada or not entry.domain:
            continue
        counter[entry.domain] += 1
    return counter
