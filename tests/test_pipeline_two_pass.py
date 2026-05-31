"""End-to-end tests for the Phase 12 two-pass candidate journey.

Mocks `cv_bau_students.llm.call_json` with a dispatcher keyed on
prompt-substring so the whole flow (extract → BAU-complete → match →
interest → prefill → submit) runs without network.
"""

from __future__ import annotations

from unittest.mock import patch

from cv_bau_students.db import get_session
from cv_bau_students.db_models import CandidateInterest, Match, RoleSpecificAnswer
from cv_bau_students.jobads.repo import store_ad
from cv_bau_students.models import GenericResult, JobAd
from cv_bau_students.pipeline import (
    express_interest,
    run_generic_pass,
    submit_role_specific,
)
from cv_bau_students.translator.translate import _translate_raw

# --- A fully BAU-complete student profile -----------------------------------

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
        {
            "institution": "VŠE",
            "field_of_study": "IT for management",
            "degree": "Bachelor",
            "start_year": 2022,
            "in_progress": True,
        }
    ],
    "work_experience": [
        {"employer": "McDonald's", "role": "Obsluha", "is_brigada": True},
    ],
    "school_projects": [
        {"title": "Regression of e-commerce data", "technologies": ["Python"]},
    ],
    "total_work_years": 0.6,
    "most_recent_grad_year": 2025,
    "studying_in_progress": True,
}

# A profile missing hard skills + soft skills + location → needs completion.
_INCOMPLETE_PROFILE = {
    **_COMPLETE_PROFILE,
    "location": None,
    "hard_skills": ["Python"],
    "explicit_skills": ["Python"],
    "soft_skills": [],
}

_TRANSLATE_PAYLOAD = {
    "translated_capabilities": [
        {
            "skill": "Python",
            "evidence_quote": "Regression of e-commerce data",
            "confidence": 0.65,
            "caveat": "Academic project",
            "source_type": "school_project",
            "relevance": "must_have",
        }
    ]
}

_ROLE_QUESTIONS_PAYLOAD = {
    "questions": [
        {
            "slot": "elevator_pitch_for_role",
            "question_text": "Proč se hodíte na tuto roli?",
            "extract_hint": "summary + target_domains",
        },
        {
            "slot": "python_experience",
            "question_text": "Popište zkušenost s Pythonem.",
            "extract_hint": "hard_skills + projects",
        },
        {
            "slot": "motivation_or_scenario",
            "question_text": "Popište situaci s daty pro netechnické publikum.",
            "extract_hint": "soft_skills",
        },
    ]
}

_PREFILL_PAYLOAD = {
    "answers": [
        {
            "slot": "elevator_pitch_for_role",
            "answer": "Baví mě data.",
            "confidence": 0.7,
            "missing": False,
        },
        {
            "slot": "python_experience",
            "answer": "Python ze školního projektu.",
            "confidence": 0.6,
            "missing": False,
        },
        {"slot": "motivation_or_scenario", "answer": "", "confidence": 0.0, "missing": True},
    ]
}


def _dispatcher(profile_payload: dict):
    def _dispatch(prompt: str, **_kwargs) -> dict:
        if "Role-specific question generator" in prompt:
            return _ROLE_QUESTIONS_PAYLOAD
        if "Pre-fill role-specific answers" in prompt:
            return _PREFILL_PAYLOAD
        if "Translate student / career-changer artefacts" in prompt:
            return _TRANSLATE_PAYLOAD
        if "recruiter-facing rationale" in prompt:
            return {"rationale": "Strong baseline fit; bridge via Power BI."}
        return profile_payload

    return _dispatch


def _seed_target_ad() -> int:
    return store_ad(
        JobAd(
            title="Datový analytik",
            employer="ApexFinance s.r.o.",
            location="Praha",
            remote_mode="hybrid",
            level="medior",
            domain="data-analyst",
            must_have=["SQL", "Python"],
            nice_to_have=["Power BI"],
            languages_required=[],
            raw_text="Hledáme datového analytika se znalostí SQL a Pythonu.",
            source="scraped",
        )
    )


def test_generic_pass_needs_completion_when_fields_missing():
    _translate_raw.cache_clear()
    with patch("cv_bau_students.llm.call_json", side_effect=_dispatcher(_INCOMPLETE_PROFILE)):
        # answer_provider=None → can't auto-fill → returns needs_completion.
        result = run_generic_pass(b"cv bytes", "anna.txt", answer_provider=None)
    assert isinstance(result, GenericResult)
    assert result.status == "needs_completion"
    assert result.candidate_id is not None  # candidate row still created


def test_generic_pass_matches_when_complete():
    _translate_raw.cache_clear()
    _seed_target_ad()
    with patch("cv_bau_students.llm.call_json", side_effect=_dispatcher(_COMPLETE_PROFILE)):
        result = run_generic_pass(b"cv bytes complete", "anna.txt")
    assert result.status == "matched"
    assert result.candidate_id is not None
    assert len(result.matches) >= 1
    # No Match rows written yet — those wait for express_interest.
    with get_session() as s:
        assert s.query(Match).count() == 0


def test_express_interest_wait_writes_no_match():
    _translate_raw.cache_clear()
    ad_id = _seed_target_ad()
    with patch("cv_bau_students.llm.call_json", side_effect=_dispatcher(_COMPLETE_PROFILE)):
        gen = run_generic_pass(b"cv wait", "anna.txt")
        res = express_interest(gen.candidate_id, ad_id, "wait")
    assert res.status == "wait"
    with get_session() as s:
        assert s.query(Match).count() == 0
        interest = s.query(CandidateInterest).one()
        assert interest.status == "wait"


def test_full_interested_flow_writes_match_and_answers():
    _translate_raw.cache_clear()
    ad_id = _seed_target_ad()
    with patch("cv_bau_students.llm.call_json", side_effect=_dispatcher(_COMPLETE_PROFILE)):
        gen = run_generic_pass(b"cv interested", "anna.txt")
        interest = express_interest(gen.candidate_id, ad_id, "interested")
        assert interest.status == "interested"
        assert len(interest.prefilled_questions) == 3
        # One question came back missing (motivation_or_scenario).
        missing_q = [q for q in interest.prefilled_questions if q.prefilled_answer is None]
        assert any(q.slot == "motivation_or_scenario" for q in missing_q)

        # User accepts 2 prefills, writes the 3rd, edits none.
        answers = {
            "elevator_pitch_for_role": "Baví mě data.",
            "python_experience": "Python ze školního projektu.",
            "motivation_or_scenario": "Vysvětlil jsem výsledky vedení firmy.",
        }
        result = submit_role_specific(
            gen.candidate_id,
            ad_id,
            answers=answers,
            prefilled_set={"elevator_pitch_for_role", "python_experience"},
            edited_set=set(),
        )
    assert result.match.ad_id == ad_id
    with get_session() as s:
        assert s.query(Match).filter_by(candidate_id=gen.candidate_id, ad_id=ad_id).count() == 1
        answer_rows = (
            s.query(RoleSpecificAnswer).filter_by(candidate_id=gen.candidate_id, ad_id=ad_id).all()
        )
        by_slot = {r.slot: r for r in answer_rows}
        assert len(by_slot) == 3
        assert by_slot["elevator_pitch_for_role"].was_prefilled is True
        assert by_slot["motivation_or_scenario"].was_prefilled is False


def test_submit_folds_answers_into_translate():
    """Questionnaire answers must reach the re-translate (so new evidence flows
    into capabilities/skill_fit/rationale) — not just the display rows."""
    _translate_raw.cache_clear()
    ad_id = _seed_target_ad()
    captured: dict[str, str | None] = {}

    def _capture(profile):
        captured["summary"] = profile.summary
        return []

    with patch("cv_bau_students.llm.call_json", side_effect=_dispatcher(_COMPLETE_PROFILE)):
        gen = run_generic_pass(b"cv fold", "anna.txt")
        express_interest(gen.candidate_id, ad_id, "interested")
        with patch("cv_bau_students.pipeline.translate", side_effect=_capture):
            submit_role_specific(
                gen.candidate_id,
                ad_id,
                answers={"python_experience": "Použil jsem window functions na diplomce."},
                prefilled_set=set(),
                edited_set=set(),
            )
    assert "window functions" in (captured["summary"] or "")


def test_role_questions_generated_once_across_candidates():
    """Fairness: two candidates interested in the same ad see identical Qs."""
    _translate_raw.cache_clear()
    ad_id = _seed_target_ad()
    with patch("cv_bau_students.llm.call_json", side_effect=_dispatcher(_COMPLETE_PROFILE)):
        gen1 = run_generic_pass(b"cv one", "one.txt")
        gen2 = run_generic_pass(b"cv two", "two.txt")
        i1 = express_interest(gen1.candidate_id, ad_id, "interested")
        i2 = express_interest(gen2.candidate_id, ad_id, "interested")
    slots1 = [q.slot for q in i1.prefilled_questions]
    slots2 = [q.slot for q in i2.prefilled_questions]
    assert slots1 == slots2
    # And only ONE template row-set persisted for the ad.
    from cv_bau_students.db_models import RoleSpecificQuestion

    with get_session() as s:
        assert s.query(RoleSpecificQuestion).filter_by(ad_id=ad_id).count() == 3
