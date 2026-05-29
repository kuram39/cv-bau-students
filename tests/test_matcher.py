"""Matcher tests: hard filter + scoring + bridge plan + ranking."""

import pytest
from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session
from cv_bau_students.jobads.repo import store_ad
from cv_bau_students.levels.repo import bridge_plan
from cv_bau_students.matcher.hard_filter import passes_hard_filter
from cv_bau_students.matcher.rank import rank_candidate
from cv_bau_students.matcher.score import score_match
from cv_bau_students.models import (
    CandidateProfile,
    JobAd,
    LanguageRequirement,
    TranslatedCapability,
)
from cv_bau_students.taxonomy.repo import resolve_skill


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
        target_domains=["data-analyst"],
        explicit_skills=["Python", "SQL", "Excel"],
        languages=[LanguageRequirement(language="English", min_level="B2")],
        summary="Final-year CS student interested in data analytics.",
    )


def _data_analyst_junior_ad() -> JobAd:
    return JobAd(
        id=None,
        title="Junior Data Analyst",
        location="Prague",
        remote_mode="hybrid",
        level="junior",
        domain="data-analyst",
        must_have=["SQL", "Excel", "Data Analysis"],
        nice_to_have=["Python", "Power BI"],
        languages_required=[LanguageRequirement(language="English", min_level="B2")],
        raw_text="Junior data analyst role helping the marketing team unpack their funnel data.",
        source="synthetic",
    )


def _store_and_fetch_ad(ad: JobAd) -> JobAd:
    ad_id = store_ad(ad)
    from cv_bau_students.jobads.repo import list_ads

    for fetched in list_ads():
        if fetched.id == ad_id:
            return fetched
    raise AssertionError("ad not found after store")


def test_hard_filter_blocks_when_language_level_too_low():
    profile = _student_profile().model_copy(
        update={"languages": [LanguageRequirement(language="English", min_level="A2")]}
    )
    ad = _data_analyst_junior_ad()
    assert passes_hard_filter(profile, ad) is False


def test_hard_filter_passes_when_language_level_meets_requirement():
    profile = _student_profile()
    ad = _data_analyst_junior_ad()
    assert passes_hard_filter(profile, ad) is True


def test_score_match_returns_high_skill_fit_when_must_have_covered():
    profile = _student_profile()
    ad = _store_and_fetch_ad(_data_analyst_junior_ad())
    capabilities: list[TranslatedCapability] = []
    score = score_match(profile, capabilities, ad)
    # Candidate covers SQL + Excel via explicit_skills; Data Analysis
    # is also a must-have. Python (nice) is covered.
    assert score.skill_fit > 60


def test_bridge_plan_returns_actionable_gaps():
    profile = _student_profile()
    # Resolve skills the candidate has into taxonomy ids.
    candidate_ids = set()
    for skill in profile.explicit_skills:
        match = resolve_skill(skill)
        if match:
            candidate_ids.add(match[0])

    gaps = bridge_plan("data-analyst", "medior", candidate_ids)
    skill_names = {g.skill for g in gaps}
    # data-analyst medior expects Python + pandas + Power BI. Python is
    # covered. pandas + Power BI are gaps.
    assert "pandas" in skill_names
    assert "Power BI" in skill_names


def test_bridge_fit_drops_when_experience_only_gap_present():
    profile = _student_profile()
    ad = _store_and_fetch_ad(_data_analyst_junior_ad().model_copy(update={"level": "senior"}))
    capabilities: list[TranslatedCapability] = []
    score = score_match(profile, capabilities, ad)
    # Senior level has Stakeholder Management as experience-only — bridge_fit
    # should be capped at 35.
    assert score.bridge_fit <= 35


def test_bridge_fit_is_minus_one_when_no_rubric_for_domain():
    """Ad with a domain we have no checklist for (e.g. 'data-engineer')
    must NOT produce bridge_fit=100. Returns -1.0 sentinel which the UI
    renders as 'N/A (no rubric)'."""
    profile = _student_profile()
    ad = _data_analyst_junior_ad().model_copy(update={"domain": "data-engineer-not-in-checklist"})
    stored = _store_and_fetch_ad(ad)
    score = score_match(profile, [], stored)
    assert score.bridge_fit == -1.0
    # Total must be a weighted average of skill_fit + personal_fit only,
    # NOT a 0 from the missing rubric being treated as a hard zero.
    assert score.total > 0


def test_rank_candidate_returns_top_n_sorted_by_total():
    profile = _student_profile()
    _store_and_fetch_ad(_data_analyst_junior_ad())
    _store_and_fetch_ad(
        _data_analyst_junior_ad().model_copy(
            update={
                "title": "Junior Backend Developer",
                "domain": "backend-developer",
                "must_have": ["Python", "REST API"],
                "nice_to_have": ["Docker"],
            }
        )
    )
    ranking = rank_candidate(profile, [], top_n=5)
    assert len(ranking) <= 5
    assert all(ranking[i].total >= ranking[i + 1].total for i in range(len(ranking) - 1))
