"""Tests for the capability translator.

The translator is LLM-driven; we mock `call_json` to return controlled
payloads and verify the confidence floor + per-(skill, source_type)
dedup work correctly.
"""

from unittest.mock import patch

import pytest

from cv_bau_students.models import CandidateProfile, SchoolProjectItem
from cv_bau_students.translator.translate import _translate_raw, translate


@pytest.fixture(autouse=True)
def _clear_translator_cache():
    _translate_raw.cache_clear()
    yield
    _translate_raw.cache_clear()


def _student_profile() -> CandidateProfile:
    return CandidateProfile(
        candidate_type="student",
        language="en",
        target_domains=["data-analyst"],
        school_projects=[
            SchoolProjectItem(
                title="Sentiment classifier",
                description="Trained BERT on Czech tweets in Python.",
                technologies=["Python", "BERT"],
            )
        ],
    )


def test_translator_returns_validated_capabilities():
    profile = _student_profile()
    payload = {
        "translated_capabilities": [
            {
                "skill": "Python",
                "evidence_quote": "Trained BERT on Czech tweets in Python.",
                "confidence": 0.65,
                "caveat": "Academic project",
                "source_type": "school_project",
                "relevance": "must_have",
            },
            {
                "skill": "NLP",
                "evidence_quote": "Trained BERT on Czech tweets",
                "confidence": 0.6,
                "caveat": None,
                "source_type": "school_project",
                "relevance": "must_have",
            },
        ]
    }
    with patch("cv_bau_students.llm.call_json", return_value=payload):
        capabilities = translate(profile)

    skills = {c.skill for c in capabilities}
    assert skills == {"Python", "NLP"}


def test_translator_drops_below_confidence_floor():
    profile = _student_profile()
    payload = {
        "translated_capabilities": [
            {
                "skill": "Python",
                "evidence_quote": "...",
                "confidence": 0.65,
                "source_type": "school_project",
                "relevance": "must_have",
            },
            {
                "skill": "Project Management",
                "evidence_quote": "implicit signal",
                "confidence": 0.2,  # below the 0.3 floor
                "source_type": "hobby",
                "relevance": "nice_to_have",
            },
        ]
    }
    with patch("cv_bau_students.llm.call_json", return_value=payload):
        capabilities = translate(profile)

    skills = {c.skill for c in capabilities}
    assert "Project Management" not in skills


def test_translator_dedupes_per_skill_and_source_type():
    """When the LLM emits two capabilities with the same (skill, source_type)
    pair, keep the highest-confidence entry."""
    profile = _student_profile()
    payload = {
        "translated_capabilities": [
            {
                "skill": "Python",
                "evidence_quote": "low-conf quote",
                "confidence": 0.45,
                "source_type": "school_project",
                "relevance": "nice_to_have",
            },
            {
                "skill": "Python",
                "evidence_quote": "stronger quote",
                "confidence": 0.7,
                "source_type": "school_project",
                "relevance": "must_have",
            },
        ]
    }
    with patch("cv_bau_students.llm.call_json", return_value=payload):
        capabilities = translate(profile)

    assert len(capabilities) == 1
    assert capabilities[0].confidence == 0.7


def test_translator_keeps_same_skill_from_distinct_source_types():
    """Python from a school_project and Python from an open_source contribution
    are independent signals — both stay."""
    profile = _student_profile()
    payload = {
        "translated_capabilities": [
            {
                "skill": "Python",
                "evidence_quote": "school project",
                "confidence": 0.55,
                "source_type": "school_project",
                "relevance": "must_have",
            },
            {
                "skill": "Python",
                "evidence_quote": "OSS PR",
                "confidence": 0.75,
                "source_type": "open_source",
                "relevance": "must_have",
            },
        ]
    }
    with patch("cv_bau_students.llm.call_json", return_value=payload):
        capabilities = translate(profile)

    assert len(capabilities) == 2
