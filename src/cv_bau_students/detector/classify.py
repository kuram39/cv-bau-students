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

from collections import Counter
from dataclasses import dataclass
from datetime import date

from cv_bau_students.config import (
    RECENT_GRAD_LOOKBACK_YEARS,
    STUDENT_MAX_WORK_YEARS,
)
from cv_bau_students.models import CandidateProfile, CandidateType


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

    # Compare target_domains to the dominant family of work history.
    history_families = _family_distribution(profile)
    if not history_families:
        reasons.append(
            "target_domains stated but no work-history domain to compare against —"
            " defaulting to experienced"
        )
        return "experienced"

    dominant_family, dominant_count = history_families.most_common(1)[0]
    target_set = {d.lower() for d in profile.target_domains}
    if dominant_family.lower() in target_set:
        reasons.append(
            f"target_domains overlap dominant work family ({dominant_family}) —" " experienced"
        )
        return "experienced"

    reasons.append(
        f"target_domains {sorted(target_set)} ≠ dominant work family"
        f" ({dominant_family}, n={dominant_count}) — career_changer"
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
