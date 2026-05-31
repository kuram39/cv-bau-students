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
from cv_bau_students.models import CandidateProfile, CandidateType

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


def classify(profile: CandidateProfile, *, today: date | None = None) -> ClassificationResult:
    """Apply the heuristic to a profile + report agreement with the LLM tag."""
    current_year = (today or date.today()).year
    reasons: list[str] = []

    # Student rules — order matters.
    if profile.studying_in_progress and profile.total_work_years < STUDENT_MAX_WORK_YEARS:
        reasons.append(
            f"studying_in_progress=True AND total_work_years"
            f" ({profile.total_work_years}) < {STUDENT_MAX_WORK_YEARS}"
        )
        verdict: CandidateType = "student"
    elif (
        profile.most_recent_grad_year is not None
        and profile.most_recent_grad_year >= current_year - RECENT_GRAD_LOOKBACK_YEARS
        and profile.total_work_years < STUDENT_MAX_WORK_YEARS
    ):
        reasons.append(
            f"fresh grad — most_recent_grad_year"
            f" ({profile.most_recent_grad_year}) >="
            f" {current_year - RECENT_GRAD_LOOKBACK_YEARS}"
            f" AND total_work_years ({profile.total_work_years}) <"
            f" {STUDENT_MAX_WORK_YEARS}"
        )
        verdict = "student"
    else:
        verdict = _classify_changer_vs_experienced(profile, reasons)

    return ClassificationResult(
        verdict=verdict,
        llm_agrees=(profile.candidate_type == verdict),
        reasons=reasons,
    )


def _classify_changer_vs_experienced(
    profile: CandidateProfile, reasons: list[str]
) -> CandidateType:
    """Career-changer rule needs explicit target-domain signal.

    Without `target_domains`, default to `experienced` — vague aspiration
    is not evidence of a career change.
    """
    if profile.total_work_years < STUDENT_MAX_WORK_YEARS:
        reasons.append(
            f"too little work history ({profile.total_work_years} yrs)"
            " but no student signal — defaulting to experienced"
        )
        return "experienced"

    if not profile.target_domains:
        reasons.append("no target_domains stated — experienced by default")
        return "experienced"

    if not profile.work_experience:
        reasons.append(
            "target_domains stated but no work history to compare against —"
            " defaulting to experienced"
        )
        return "experienced"

    # Fuzzy match target_domains against the candidate's actual roles/domains
    # (exact-match wrongly flagged staying-in-field analysts as changers).
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
