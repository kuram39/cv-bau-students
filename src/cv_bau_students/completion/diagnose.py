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

# Phase 12: BAU-mandatory minimums per the round-2 brief.
# - At least 1 work or school-project entry.
# - At least 3 hard skills (so the matcher has signal to score against).
# - At least 3 soft skills (most roles need them; can't pre-judge in
#   role-agnostic Stage 1).
# - At least 1 language with a level.
# Identity (name, location) and at least 1 education entry are always
# required regardless of candidate type.
MIN_HARD_SKILLS = 3
MIN_SOFT_SKILLS = 3


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


def diagnose_bau_mandatory(profile: CandidateProfile) -> list[str]:
    """Strict role-agnostic check — fields MUST be present before any match.

    Stage 1 of the candidate journey: we don't yet know which target
    role will match, so the check is unconditional. Returns a list of
    field tokens the completion-question generator can use; empty list
    means the profile is matchable.

    Difference from `diagnose_missing`: this is the BAU-mandatory
    minimum (without these, scoring is meaningless), not the
    nice-to-ask soft list.
    """
    missing: list[str] = []

    if not profile.name or len(profile.name.strip()) < 2:
        missing.append("name")
    if not profile.location or len(profile.location.strip()) < 2:
        missing.append("location")

    if not profile.education:
        missing.append("education")

    # At least 1 work record OR 1 school project entry — students
    # without paid work history still match if they show projects.
    if not profile.work_experience and not profile.school_projects:
        missing.append("work_or_project")

    # Hard skills: combine the two lists (hard + legacy explicit) for
    # the threshold check so back-compat CVs that only populated
    # `explicit_skills` still pass.
    hard_count = len(set(profile.hard_skills) | set(profile.explicit_skills))
    if hard_count < MIN_HARD_SKILLS:
        missing.append(f"hard_skills::need_{MIN_HARD_SKILLS - hard_count}_more")

    if len(profile.soft_skills) < MIN_SOFT_SKILLS:
        missing.append(f"soft_skills::need_{MIN_SOFT_SKILLS - len(profile.soft_skills)}_more")

    if not profile.languages:
        missing.append("languages")

    return missing


__all__ = [
    "diagnose_missing",
    "diagnose_bau_mandatory",
    "HIGH_CONFIDENCE_THRESHOLD",
    "MIN_HARD_SKILLS",
    "MIN_SOFT_SKILLS",
]
