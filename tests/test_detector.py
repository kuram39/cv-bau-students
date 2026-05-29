"""Tests for the Python candidate-type heuristic.

The LLM extractor's tag is independent; the detector here re-applies
the same rules deterministically so we can reason about edge cases
without mocking an LLM.
"""

from datetime import date

from cv_bau_students.detector.classify import classify
from cv_bau_students.models import (
    CandidateProfile,
    EducationItem,
    WorkExperienceItem,
)

TODAY = date(2026, 5, 29)


def _student_profile(**overrides) -> CandidateProfile:
    base = CandidateProfile(
        candidate_type="student",
        language="cs",
        education=[
            EducationItem(
                institution="ČVUT FIT",
                field_of_study="Informatika",
                degree="Bachelor",
                start_year=2022,
                in_progress=True,
            )
        ],
        total_work_years=0.6,  # one McDonald's brigáda
        most_recent_grad_year=2025,
        studying_in_progress=True,
    )
    return base.model_copy(update=overrides)


def _experienced_profile(**overrides) -> CandidateProfile:
    base = CandidateProfile(
        candidate_type="experienced",
        language="en",
        education=[
            EducationItem(
                institution="Charles University",
                field_of_study="Computer Science",
                degree="Master",
                start_year=2014,
                end_year=2019,
                in_progress=False,
            )
        ],
        work_experience=[
            WorkExperienceItem(employer="Avast", role="Software Engineer", domain="cybersecurity"),
            WorkExperienceItem(
                employer="Seznam", role="Senior Software Engineer", domain="cybersecurity"
            ),
        ],
        total_work_years=7.0,
        most_recent_grad_year=2019,
        studying_in_progress=False,
    )
    return base.model_copy(update=overrides)


def test_student_with_in_progress_study_classifies_as_student():
    profile = _student_profile()
    result = classify(profile, today=TODAY)
    assert result.verdict == "student"
    assert any("studying_in_progress" in r for r in result.reasons)


def test_fresh_graduate_within_one_year_classifies_as_student():
    profile = _student_profile(
        studying_in_progress=False,
        most_recent_grad_year=2026,
        education=[
            EducationItem(
                institution="ČVUT FIT",
                field_of_study="Informatika",
                degree="Bachelor",
                start_year=2022,
                end_year=2026,
                in_progress=False,
            )
        ],
    )
    result = classify(profile, today=TODAY)
    assert result.verdict == "student"
    assert any("fresh grad" in r for r in result.reasons)


def test_experienced_engineer_classifies_as_experienced():
    profile = _experienced_profile()
    result = classify(profile, today=TODAY)
    assert result.verdict == "experienced"


def test_career_changer_target_outside_work_history_classifies_as_changer():
    profile = _experienced_profile(
        target_domains=["data-analyst"],
        work_experience=[
            WorkExperienceItem(
                employer="Restaurace U Pinkasů",
                role="Provozní manažer",
                domain="hospitality",
            ),
            WorkExperienceItem(
                employer="Restaurace U Pinkasů",
                role="Vrchní číšník",
                domain="hospitality",
            ),
        ],
    )
    result = classify(profile, today=TODAY)
    assert result.verdict == "career_changer"


def test_target_domain_matching_history_keeps_experienced():
    profile = _experienced_profile(target_domains=["cybersecurity"])
    result = classify(profile, today=TODAY)
    assert result.verdict == "experienced"


def test_llm_agreement_flag_set_when_tag_matches_heuristic():
    profile = _experienced_profile()
    result = classify(profile, today=TODAY)
    assert result.llm_agrees is True


def test_llm_disagreement_flag_set_when_tag_misses():
    # LLM tagged 'student' but our heuristic should overrule it
    profile = _experienced_profile(candidate_type="student")
    result = classify(profile, today=TODAY)
    assert result.verdict == "experienced"
    assert result.llm_agrees is False
