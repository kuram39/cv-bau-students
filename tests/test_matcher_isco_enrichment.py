"""Tests for ESCO target-role enrichment of skill_fit (`matcher.score`).

Seeds a minimal taxonomy + occupation→skill map in-memory, then checks
that an ad with a resolved ISCO code lifts skill_fit by a capped bonus
and emits a populated `SkillFitDetail`, while a no-ISCO ad is unchanged.
"""

from __future__ import annotations

from cv_bau_students.config import ROLE_BONUS_CAP
from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillIndustryMap
from cv_bau_students.matcher.score import score_match
from cv_bau_students.models import CandidateProfile, JobAd


def _seed_skills(names: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    with get_session() as session:
        for n in names:
            s = Skill(canonical_name=n)
            session.add(s)
            session.flush()
            out[n] = s.id
    return out


def _seed_essential(isco: str, skill_ids: list[int]) -> None:
    with get_session() as session:
        for sid in skill_ids:
            session.add(SkillIndustryMap(skill_id=sid, isco_code=isco, relation_type="essential"))


def _profile(skills: list[str]) -> CandidateProfile:
    return CandidateProfile(
        candidate_type="student",
        language="en",
        explicit_skills=skills,
        summary="data student",
    )


def _ad(isco_code: str | None) -> JobAd:
    return JobAd(
        id=1,
        title="Data Analyst",
        location="Praha",
        remote_mode="hybrid",
        level="junior",
        domain="data-analyst",
        must_have=["SQL", "Python", "Power BI", "Excel"],
        nice_to_have=["statistics"],
        raw_text="analyst role",
        source="synthetic",
        isco_code=isco_code,
        isco_occupation_label="data analyst" if isco_code else None,
        isco_method="lexical" if isco_code else None,
    )


def test_enrichment_adds_capped_bonus_and_detail():
    ids = _seed_skills(
        [
            "SQL",
            "Python",
            "Power BI",
            "Excel",
            "data mining",
            "data visualisation",
            "statistics",
            "reporting",
        ]
    )
    # Essential set for the occupation: 2 of the musts + 4 extras.
    _seed_essential(
        "2511",
        [
            ids["SQL"],
            ids["Python"],
            ids["data mining"],
            ids["data visualisation"],
            ids["statistics"],
            ids["reporting"],
        ],
    )
    # Candidate covers 2 musts + 2 extra essentials.
    profile = _profile(["SQL", "Python", "data mining", "data visualisation"])

    base_score = score_match(profile, [], _ad(isco_code=None))
    enriched = score_match(profile, [], _ad(isco_code="2511"))

    # No-ISCO path: no enrichment recorded.
    assert base_score.skill_fit_detail.isco_code is None
    assert base_score.skill_fit_detail.bonus_applied == 0.0

    d = enriched.skill_fit_detail
    assert d.isco_code == "2511"
    assert d.occupation_label == "data analyst"
    assert d.role_essential_total == 6
    assert d.role_essential_evidenced == 4
    # 2 essentials beyond the must-haves → +3 each = +6.
    assert d.bonus_applied == 6.0
    assert enriched.skill_fit == round(base_score.skill_fit + 6.0, 1)
    assert d.matched_must == ["Python", "SQL"]
    assert d.missing_must == ["Excel", "Power BI"]
    assert "statistics" in d.role_essential_missing
    assert "reporting" in d.role_essential_missing


def test_enrichment_bonus_is_capped():
    extras = [f"skill{i}" for i in range(10)]
    ids = _seed_skills(["SQL", "Python", "Power BI", "Excel", *extras])
    _seed_essential("2511", [ids[name] for name in extras])  # 10 essentials, all extra
    profile = _profile(["SQL", *extras])  # evidences all 10 extras

    enriched = score_match(profile, [], _ad(isco_code="2511"))
    assert enriched.skill_fit_detail.bonus_applied == ROLE_BONUS_CAP
    assert enriched.skill_fit <= 100.0


def test_no_enrichment_when_isco_has_no_essential_skills():
    _seed_skills(["SQL", "Python", "Power BI", "Excel"])
    # ISCO set on the ad but no SkillIndustryMap rows for it.
    profile = _profile(["SQL", "Python"])
    enriched = score_match(profile, [], _ad(isco_code="9999"))
    assert enriched.skill_fit_detail.role_essential_total == 0
    assert enriched.skill_fit_detail.bonus_applied == 0.0
