"""Tests for the iterative completion loop.

`diagnose_missing` is pure Python — exhaustively cover the rules so we
can trust the question-generator's input. `fold_answers_into_profile`
mutates a profile based on the candidate's answers — verify each field
type round-trips correctly.
"""

from unittest.mock import patch

from cv_bau_students.completion.ask import ask, fold_answers_into_profile
from cv_bau_students.completion.diagnose import diagnose_missing
from cv_bau_students.models import (
    CandidateProfile,
    CompletionQuestion,
    CompletionRound,
    EducationItem,
    LanguageRequirement,
    SchoolProjectItem,
    WorkExperienceItem,
)


def _sparse_student() -> CandidateProfile:
    return CandidateProfile(
        candidate_type="student",
        language="cs",
        education=[
            EducationItem(
                institution="ČVUT FIT",
                field_of_study="Informatika",
                degree="Bachelor",
                start_year=2022,
                in_progress=True,
                thesis_title="Sentiment analysis of tweets",
            )
        ],
        work_experience=[
            WorkExperienceItem(employer="McDonald's", role="Obsluha", is_brigada=True)
        ],
        explicit_skills=["Python", "React"],
        languages=[LanguageRequirement(language="English", min_level="")],
        total_work_years=0.6,
        most_recent_grad_year=2025,
        studying_in_progress=True,
    )


def test_diagnose_flags_summary_when_missing():
    profile = _sparse_student()
    missing = diagnose_missing(profile)
    assert "summary" in missing


def test_diagnose_flags_target_domains_when_empty():
    profile = _sparse_student()
    missing = diagnose_missing(profile)
    assert "target_domains" in missing


def test_diagnose_flags_brigada_without_description():
    profile = _sparse_student()
    missing = diagnose_missing(profile)
    assert any(f.startswith("brigada_description::McDonald") for f in missing)


def test_diagnose_flags_thesis_title_without_summary():
    profile = _sparse_student()
    missing = diagnose_missing(profile)
    assert any(f.startswith("thesis_summary::ČVUT FIT") for f in missing)


def test_diagnose_flags_language_with_empty_level():
    profile = _sparse_student()
    missing = diagnose_missing(profile)
    assert any(f.startswith("language_level::English") for f in missing)


def test_diagnose_returns_empty_for_a_complete_profile():
    profile = _sparse_student().model_copy(
        update={
            "summary": "Computer-Science student at ČVUT, interested in NLP and backend work.",
            "target_domains": ["data-analyst", "backend-developer"],
            "work_experience": [
                WorkExperienceItem(
                    employer="McDonald's",
                    role="Obsluha",
                    is_brigada=True,
                    description="Pokladna, pracoval pod stresem o víkendech.",
                )
            ],
            "education": [
                EducationItem(
                    institution="ČVUT FIT",
                    field_of_study="Informatika",
                    degree="Bachelor",
                    start_year=2022,
                    in_progress=True,
                    thesis_title="Sentiment analysis of tweets",
                    thesis_summary="Trains BERT classifier on Czech tweets; my contribution is the data-cleaning pipeline.",
                )
            ],
            "languages": [LanguageRequirement(language="English", min_level="B2")],
            "school_projects": [
                SchoolProjectItem(title="School cafeteria web app", technologies=["React"]),
            ],
        }
    )
    assert diagnose_missing(profile) == []


def test_ask_returns_empty_round_when_nothing_missing():
    profile = _sparse_student()
    round_obj = ask(profile, missing_fields=[], round_no=1)
    assert isinstance(round_obj, CompletionRound)
    assert round_obj.questions == []


def test_ask_caps_questions_at_three():
    profile = _sparse_student()
    fake_llm_payload = {
        "questions": [
            {"field": "summary", "question": "Q1", "why_it_matters": "..."},
            {"field": "target_domains", "question": "Q2", "why_it_matters": "..."},
            {"field": "thesis_summary::X", "question": "Q3", "why_it_matters": "..."},
            {"field": "brigada_description::Y::Z", "question": "Q4", "why_it_matters": "..."},
        ]
    }
    with patch("cv_bau_students.llm.call_json", return_value=fake_llm_payload):
        round_obj = ask(profile, missing_fields=["summary", "target_domains"], round_no=1)
    assert len(round_obj.questions) == 3


def test_fold_answers_writes_summary_into_profile():
    profile = _sparse_student()
    round_obj = CompletionRound(
        round_no=1,
        questions=[CompletionQuestion(field="summary", question="?")],
        answers={"summary": "I'm a final-year CS student interested in NLP."},
    )
    new_profile = fold_answers_into_profile(profile, round_obj)
    assert new_profile.summary == "I'm a final-year CS student interested in NLP."


def test_fold_answers_splits_target_domains():
    profile = _sparse_student()
    round_obj = CompletionRound(
        round_no=1,
        questions=[CompletionQuestion(field="target_domains", question="?")],
        answers={"target_domains": "Data Analyst, Backend Developer, Marketing Analyst"},
    )
    new_profile = fold_answers_into_profile(profile, round_obj)
    assert new_profile.target_domains == [
        "data-analyst",
        "backend-developer",
        "marketing-analyst",
    ]


def test_fold_answers_writes_brigada_description():
    profile = _sparse_student()
    round_obj = CompletionRound(
        round_no=1,
        questions=[
            CompletionQuestion(field="brigada_description::McDonald's::Obsluha", question="?")
        ],
        answers={
            "brigada_description::McDonald's::Obsluha": "Pokladna, koordinace s kuchyní, řešení reklamací."
        },
    )
    new_profile = fold_answers_into_profile(profile, round_obj)
    assert (
        new_profile.work_experience[0].description
        == "Pokladna, koordinace s kuchyní, řešení reklamací."
    )


def test_fold_answers_writes_thesis_summary():
    profile = _sparse_student()
    round_obj = CompletionRound(
        round_no=1,
        questions=[CompletionQuestion(field="thesis_summary::ČVUT FIT", question="?")],
        answers={
            "thesis_summary::ČVUT FIT": "Klasifikátor sentimentu českých tweetů; můj přínos je preprocesing dat."
        },
    )
    new_profile = fold_answers_into_profile(profile, round_obj)
    assert new_profile.education[0].thesis_summary == (
        "Klasifikátor sentimentu českých tweetů; můj přínos je preprocesing dat."
    )


def test_fold_answers_writes_language_level():
    profile = _sparse_student()
    round_obj = CompletionRound(
        round_no=1,
        questions=[CompletionQuestion(field="language_level::English", question="?")],
        answers={"language_level::English": "b2"},
    )
    new_profile = fold_answers_into_profile(profile, round_obj)
    assert new_profile.languages[0].min_level == "B2"


def test_fold_answers_appends_skill_proof_as_project():
    profile = _sparse_student()
    round_obj = CompletionRound(
        round_no=1,
        questions=[CompletionQuestion(field="skill_proof::Python", question="?")],
        answers={
            "skill_proof::Python": "Wrote a Python script to scrape product prices from e-commerce sites."
        },
    )
    new_profile = fold_answers_into_profile(profile, round_obj)
    assert any(
        p.title.startswith("Candidate-supplied example: Python")
        for p in new_profile.school_projects
    )
