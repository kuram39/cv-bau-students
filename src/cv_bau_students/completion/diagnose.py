"""Diagnose which profile fields are missing-but-matchable.

Python pass (no LLM). Walks the structured profile, applies a small
ruleset for "this field is required by the matcher", and returns a
list of field names that the completion-question generator should
target. Heuristic is intentionally conservative: only flag fields the
recruiter genuinely cannot work without — chasing every blank cell
produces interrogation fatigue.
"""

from cv_bau_students.config import HIGH_CONFIDENCE_THRESHOLD
from cv_bau_students.models import CandidateProfile


def diagnose_missing(profile: CandidateProfile) -> list[str]:
    """Return a prioritised list of field names worth asking about."""
    missing: list[str] = []

    if not profile.summary or len(profile.summary.strip()) < 40:
        missing.append("summary")

    if not profile.target_domains:
        missing.append("target_domains")

    for entry in profile.work_experience:
        if entry.is_brigada and not (entry.description and len(entry.description) > 20):
            missing.append(f"brigada_description::{entry.employer}::{entry.role}")
            break  # one round = one brigáda question is enough

    for edu in profile.education:
        if edu.thesis_title and not edu.thesis_summary:
            missing.append(f"thesis_summary::{edu.institution}")
            break

    for lang in profile.languages:
        if not lang.min_level or lang.min_level.strip() == "":
            missing.append(f"language_level::{lang.language}")
            break

    # Skill listed without a project example — only flag the FIRST one
    # to avoid overwhelming the candidate. Confidence threshold mirrors
    # the translator's title-only cap.
    if profile.explicit_skills and not profile.school_projects and not profile.open_source:
        # No projects at all — every skill is title-only by definition.
        missing.append(f"skill_proof::{profile.explicit_skills[0]}")

    return missing


__all__ = ["diagnose_missing", "HIGH_CONFIDENCE_THRESHOLD"]
