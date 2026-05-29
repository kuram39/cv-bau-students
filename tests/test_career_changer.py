"""Career-changer parity tests.

The translator + matcher should produce non-zero output for a candidate
whose work history is in a different domain than their target. We mock
the LLM with a payload that surfaces transferable signals + reuse the
matcher + bridge_plan to confirm the bridge surfaces actionable gaps.
"""

from unittest.mock import patch

import pytest
from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session
from cv_bau_students.detector.classify import classify
from cv_bau_students.jobads.repo import store_ad
from cv_bau_students.matcher.score import score_match
from cv_bau_students.models import (
    CandidateProfile,
    JobAd,
    LanguageRequirement,
    WorkExperienceItem,
)
from cv_bau_students.translator.translate import _translate_raw, translate


@pytest.fixture(autouse=True)
def _seed_taxonomy():
    with get_session() as session:
        _truncate_taxonomy(session)
        canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
        _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)
    _translate_raw.cache_clear()
    yield
    _translate_raw.cache_clear()


def _changer_profile() -> CandidateProfile:
    """5 years restaurant ops manager pivoting to product manager."""
    return CandidateProfile(
        candidate_type="career_changer",
        language="en",
        summary=(
            "Five-year restaurant operations manager pivoting into a product role. "
            "I want to apply cross-functional coordination and stakeholder skills to "
            "product delivery."
        ),
        target_domains=["project-manager"],
        explicit_skills=["Excel", "Project Management"],
        languages=[LanguageRequirement(language="English", min_level="B2")],
        work_experience=[
            WorkExperienceItem(
                employer="Restaurace U Pinkasů",
                role="Provozní manažer",
                domain="hospitality",
                description=(
                    "Led a 12-person kitchen shift, owned P&L, coordinated supplier "
                    "relationships and weekly menu planning."
                ),
            ),
            WorkExperienceItem(
                employer="Restaurace U Pinkasů",
                role="Vrchní číšník",
                domain="hospitality",
                description="Managed front-of-house team during peak service.",
            ),
        ],
        total_work_years=5.0,
        most_recent_grad_year=2014,
        studying_in_progress=False,
    )


def test_career_changer_detected_correctly():
    profile = _changer_profile()
    result = classify(profile)
    assert result.verdict == "career_changer"


def test_translator_surfaces_transferable_capabilities():
    profile = _changer_profile()
    payload = {
        "translated_capabilities": [
            {
                "skill": "Stakeholder Management",
                "evidence_quote": "coordinated supplier relationships and weekly menu planning",
                "confidence": 0.65,
                "caveat": "Industry-different but skill-transferable",
                "source_type": "other",
                "relevance": "must_have",
            },
            {
                "skill": "Project Management",
                "evidence_quote": "owned P&L, coordinated supplier relationships",
                "confidence": 0.6,
                "caveat": "Restaurant scale, not product scale",
                "source_type": "other",
                "relevance": "must_have",
            },
        ]
    }
    with patch("cv_bau_students.llm.call_json", return_value=payload):
        capabilities = translate(profile)
    skills = {c.skill for c in capabilities}
    assert "Stakeholder Management" in skills
    assert "Project Management" in skills


def test_match_score_for_changer_surfaces_bridge_plan_against_pm_role():
    profile = _changer_profile()
    ad = JobAd(
        id=None,
        title="Junior Project Manager",
        location="Prague",
        remote_mode="hybrid",
        level="junior",
        domain="project-manager",
        must_have=["Project Management"],
        nice_to_have=["Stakeholder Management"],
        languages_required=[LanguageRequirement(language="English", min_level="B2")],
        raw_text="Junior PM role with mentor support for industry switchers.",
        source="synthetic",
    )
    ad_id = store_ad(ad)
    stored_ad = ad.model_copy(update={"id": ad_id})

    score = score_match(profile, [], stored_ad)
    # Project Management is in candidate.explicit_skills, so skill_fit
    # should be > 0 even without translated capabilities.
    assert score.skill_fit >= 60
    # Junior PM has no experience-only gaps → bridge_fit should be high.
    assert score.bridge_fit >= 70
