"""Reasoning tests — cache hit + payload generation."""

import json
from unittest.mock import patch

import pytest
from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session
from cv_bau_students.db_models import Candidate
from cv_bau_students.explanation.reason import reason
from cv_bau_students.jobads.repo import store_ad
from cv_bau_students.models import (
    CandidateProfile,
    JobAd,
    LanguageRequirement,
    MatchScore,
    TranslatedCapability,
)


@pytest.fixture(autouse=True)
def _seed_taxonomy():
    with get_session() as session:
        _truncate_taxonomy(session)
        canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
        _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)
    yield


def _student_profile() -> CandidateProfile:
    return CandidateProfile(
        candidate_type="student",
        language="en",
        summary="Final-year CS student.",
        target_domains=["data-analyst"],
        explicit_skills=["Python", "SQL"],
        languages=[LanguageRequirement(language="English", min_level="B2")],
    )


def _ad() -> JobAd:
    return JobAd(
        id=None,
        title="Junior Data Analyst",
        location="Prague",
        remote_mode="hybrid",
        level="junior",
        domain="data-analyst",
        must_have=["Python", "SQL"],
        nice_to_have=["Power BI"],
        languages_required=[LanguageRequirement(language="English", min_level="B2")],
        raw_text="Junior data analyst role.",
        source="synthetic",
    )


def _seed_candidate() -> int:
    with get_session() as session:
        cand = Candidate(cv_hash="abc123", language="en", type="student")
        session.add(cand)
        session.flush()
        return cand.id


def _match_score(ad_id: int) -> MatchScore:
    return MatchScore(
        ad_id=ad_id,
        skill_fit=70,
        bridge_fit=80,
        personal_fit=60,
        total=72,
        confidence_band=15,
        bridge_plan=[],
    )


_FAKE_PAYLOAD = {
    "verdict": "Probably yes — strong technical core.",
    "strengths": ["Python fluency demonstrated"],
    "gaps": ["No production data experience"],
    "interview_prompts": ["Walk through your school project."],
}


def test_reason_returns_validated_payload_text():
    profile = _student_profile()
    candidate_id = _seed_candidate()
    ad_id = store_ad(_ad())
    match = _match_score(ad_id)
    ad = _ad().model_copy(update={"id": ad_id})

    with patch("cv_bau_students.llm.call_json", return_value=_FAKE_PAYLOAD):
        text = reason(profile, [], match, ad, candidate_id=candidate_id)

    payload = json.loads(text)
    assert payload["verdict"].startswith("Probably yes")


def test_reason_hits_cache_on_repeat_call():
    profile = _student_profile()
    candidate_id = _seed_candidate()
    ad_id = store_ad(_ad())
    match = _match_score(ad_id)
    ad = _ad().model_copy(update={"id": ad_id})

    with patch("cv_bau_students.llm.call_json", return_value=_FAKE_PAYLOAD) as mock_call:
        first = reason(profile, [], match, ad, candidate_id=candidate_id)
        second = reason(profile, [], match, ad, candidate_id=candidate_id)

    assert first == second
    assert mock_call.call_count == 1  # second call hit the cache


def test_reason_skips_cache_when_no_candidate_id():
    profile = _student_profile()
    ad_id = store_ad(_ad())
    match = _match_score(ad_id)
    ad = _ad().model_copy(update={"id": ad_id})

    with patch("cv_bau_students.llm.call_json", return_value=_FAKE_PAYLOAD) as mock_call:
        reason(profile, [], match, ad)
        reason(profile, [], match, ad)
    assert mock_call.call_count == 2


def test_reason_cache_busts_on_model_change(monkeypatch):
    """Switching the model must NOT serve a stale cached rationale."""
    import cv_bau_students.explanation.reason as reason_mod

    profile = _student_profile()
    candidate_id = _seed_candidate()
    ad_id = store_ad(_ad())
    match = _match_score(ad_id)
    ad = _ad().model_copy(update={"id": ad_id})

    with patch("cv_bau_students.llm.call_json", return_value=_FAKE_PAYLOAD) as mock_call:
        monkeypatch.setattr(reason_mod, "LLM_MODEL", "claude-sonnet-4-6")
        reason(profile, [], match, ad, candidate_id=candidate_id)
        monkeypatch.setattr(reason_mod, "LLM_MODEL", "claude-opus-4-8")
        reason(profile, [], match, ad, candidate_id=candidate_id)

    assert mock_call.call_count == 2  # different model → different key → fresh call


def test_reason_includes_capabilities_in_prompt():
    profile = _student_profile()
    candidate_id = _seed_candidate()
    ad_id = store_ad(_ad())
    match = _match_score(ad_id)
    ad = _ad().model_copy(update={"id": ad_id})
    capabilities = [
        TranslatedCapability(
            skill="Python",
            evidence_quote="...",
            confidence=0.7,
            caveat=None,
            source_type="school_project",
            relevance="must_have",
        )
    ]

    captured: dict[str, str] = {}

    def _capture(prompt: str, **_kwargs) -> dict:
        captured["prompt"] = prompt
        return _FAKE_PAYLOAD

    with patch("cv_bau_students.llm.call_json", side_effect=_capture):
        reason(profile, capabilities, match, ad, candidate_id=candidate_id)
    assert "Python" in captured["prompt"]
    assert "school_project" in captured["prompt"]
