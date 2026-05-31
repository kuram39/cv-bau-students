"""Tests for `scripts.seed_target_demo` — Phase 12d.

Builds a target ad + two tiny CV files in tmp_path, mocks the LLM
dispatcher, and asserts the full seed run populates candidates,
interests, role-question template, and Match rows. Idempotency on
re-run is checked too.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts import seed_target_demo as seed

from cv_bau_students.db import get_session
from cv_bau_students.db_models import (
    CandidateInterest,
    JobAdRow,
    Match,
    RoleSpecificQuestion,
)
from cv_bau_students.jobads.repo import store_ad
from cv_bau_students.models import JobAd
from cv_bau_students.translator.translate import _translate_raw

_COMPLETE_PROFILE = {
    "candidate_type": "student",
    "language": "en",
    "name": "Anna Nováková",
    "contact": "anna@example.com",
    "location": "Praha",
    "summary": "Student VŠE interested in data analysis.",
    "target_domains": ["data-analyst"],
    "explicit_skills": ["Python", "SQL", "Excel"],
    "hard_skills": ["Python", "SQL", "Excel"],
    "soft_skills": ["team work", "communication", "presentation"],
    "languages": [
        {"language": "Czech", "min_level": "C2"},
        {"language": "English", "min_level": "B2"},
    ],
    "education": [
        {"institution": "VŠE", "field_of_study": "IT", "degree": "Bachelor", "in_progress": True}
    ],
    "work_experience": [{"employer": "McDonald's", "role": "Obsluha", "is_brigada": True}],
    "school_projects": [{"title": "Regression", "technologies": ["Python"]}],
    "total_work_years": 0.6,
    "most_recent_grad_year": 2025,
    "studying_in_progress": True,
}

_ROLE_QUESTIONS = {
    "questions": [
        {"slot": "elevator_pitch_for_role", "question_text": "Proč?", "extract_hint": "summary"},
        {"slot": "sql_experience", "question_text": "SQL?", "extract_hint": "hard_skills"},
        {"slot": "motivation_or_scenario", "question_text": "Scénář?", "extract_hint": "soft"},
    ]
}

_PREFILL = {
    "answers": [
        {
            "slot": "elevator_pitch_for_role",
            "answer": "Baví mě data.",
            "confidence": 0.7,
            "missing": False,
        },
        {"slot": "sql_experience", "answer": "SQL ze školy.", "confidence": 0.6, "missing": False},
        {"slot": "motivation_or_scenario", "answer": "", "confidence": 0.0, "missing": True},
    ]
}


def _dispatch(prompt: str, **_kwargs) -> dict:
    if "Role-specific question generator" in prompt:
        return _ROLE_QUESTIONS
    if "Pre-fill role-specific answers" in prompt:
        return _PREFILL
    if "Translate student / career-changer artefacts" in prompt:
        return {"translated_capabilities": []}
    if "recruiter-facing rationale" in prompt:
        return {"rationale": "Solid baseline fit."}
    return _COMPLETE_PROFILE


def _make_target_ad() -> int:
    return store_ad(
        JobAd(
            title="Datový analytik/Datová analytička",
            employer=None,
            location="Praha",
            remote_mode="onsite",
            level="medior",
            domain="data-analyst",
            must_have=[],
            nice_to_have=[],
            languages_required=[],
            raw_text="Hledáme analytika.",
            source="scraped",
        )
    )


def _fake_fabricate(_summary: str, _question: str) -> str:
    return "Fabricated seed answer."


def _write_cvs(tmp_path: Path) -> tuple[Path, Path]:
    students = tmp_path / "students"
    experienced = tmp_path / "experienced"
    students.mkdir(parents=True)
    experienced.mkdir(parents=True)
    (students / "anna.txt").write_text("Anna CV text", encoding="utf-8")
    (experienced / "petr.txt").write_text("Petr CV text", encoding="utf-8")
    return students, experienced


def test_seed_populates_full_demo(tmp_path, monkeypatch):
    _translate_raw.cache_clear()
    _make_target_ad()
    students, experienced = _write_cvs(tmp_path)
    monkeypatch.setattr(seed, "STUDENTS_DIR", students)
    monkeypatch.setattr(seed, "EXPERIENCED_DIR", experienced)

    with (
        patch("cv_bau_students.llm.call_json", side_effect=_dispatch),
        patch.object(seed, "_fabricate_answer", side_effect=_fake_fabricate),
    ):
        rc = seed.run_seed()
    assert rc == 0

    with get_session() as s:
        # Target ad got the demo employer + skills.
        ad = s.query(JobAdRow).filter(JobAdRow.title.like("Datový analytik%")).one()
        assert ad.employer == seed.DEMO_EMPLOYER
        # One role-question template (3 rows) for the ad.
        assert s.query(RoleSpecificQuestion).filter_by(ad_id=ad.id).count() == 3
        # Two candidates → two interests → two matches.
        assert s.query(CandidateInterest).filter_by(status="interested").count() == 2
        assert s.query(Match).filter_by(ad_id=ad.id).count() == 2


def test_seed_is_idempotent(tmp_path, monkeypatch):
    _translate_raw.cache_clear()
    _make_target_ad()
    students, experienced = _write_cvs(tmp_path)
    monkeypatch.setattr(seed, "STUDENTS_DIR", students)
    monkeypatch.setattr(seed, "EXPERIENCED_DIR", experienced)

    with (
        patch("cv_bau_students.llm.call_json", side_effect=_dispatch),
        patch.object(seed, "_fabricate_answer", side_effect=_fake_fabricate),
    ):
        seed.run_seed()
        seed.run_seed()  # second run

    with get_session() as s:
        ad = s.query(JobAdRow).filter(JobAdRow.title.like("Datový analytik%")).one()
        # Still exactly 2 candidates / matches / 3 questions — no dupes.
        assert s.query(Match).filter_by(ad_id=ad.id).count() == 2
        assert s.query(RoleSpecificQuestion).filter_by(ad_id=ad.id).count() == 3
        # Employer modification stayed idempotent (no double intro).
        assert ad.raw_text.count(seed.DEMO_INTRO) == 1
