"""Tests for ESCO target-role enrichment of skill_fit (`matcher.score`).

Enrichment resolves candidate skills into the ESCO namespace
(`resolve_skill_esco`), so the skills are seeded WITH `esco_uri` and the
occupation map (`skill_industry_map`) points at the same ids. Covers the
explicit-skill path, the stored-capability `skill_id` path, optional
relations, the cap, and the no-ISCO regression.
"""

from __future__ import annotations

from cv_bau_students.config import ROLE_BONUS_CAP
from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillIndustryMap
from cv_bau_students.matcher.score import score_match
from cv_bau_students.models import CandidateProfile, JobAd, TranslatedCapability


def _seed_skills(names: list[str]) -> dict[str, int]:
    """Seed ESCO-namespace skills (esco_uri set) so resolve_skill_esco finds them."""
    out: dict[str, int] = {}
    with get_session() as session:
        for n in names:
            s = Skill(canonical_name=n, canonical_name_en=n, esco_uri=f"uri:{n}")
            session.add(s)
            session.flush()
            out[n] = s.id
    return out


def _seed_relation(isco: str, skill_ids: list[int], relation: str) -> None:
    with get_session() as session:
        for sid in skill_ids:
            session.add(SkillIndustryMap(skill_id=sid, isco_code=isco, relation_type=relation))


def _profile(skills: list[str]) -> CandidateProfile:
    return CandidateProfile(
        candidate_type="student", language="en", explicit_skills=skills, summary="data student"
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
    # role_set = essential ∪ optional = 6 skills (2 of them also musts).
    _seed_relation("2511", [ids["SQL"], ids["data mining"], ids["data visualisation"]], "essential")
    _seed_relation("2511", [ids["Python"], ids["statistics"], ids["reporting"]], "optional")
    # Candidate covers 2 musts (SQL, Python) + 2 extra role skills.
    profile = _profile(["SQL", "Python", "data mining", "data visualisation"])

    base_score = score_match(profile, [], _ad(isco_code=None))
    enriched = score_match(profile, [], _ad(isco_code="2511"))

    assert base_score.skill_fit_detail.isco_code is None
    assert base_score.skill_fit_detail.bonus_applied == 0.0

    d = enriched.skill_fit_detail
    assert d.isco_code == "2511"
    assert d.role_essential_total == 6  # essential ∪ optional
    assert d.role_essential_evidenced == 4
    # 2 role skills beyond the must-haves (data mining, data visualisation) → +3 each.
    assert d.bonus_applied == 6.0
    assert enriched.skill_fit == round(base_score.skill_fit + 6.0, 1)
    assert d.matched_must == ["Python", "SQL"]
    assert d.missing_must == ["Excel", "Power BI"]
    assert "statistics" in d.role_essential_missing
    assert "reporting" in d.role_essential_missing


def test_stored_capability_skill_id_is_used():
    """A capability carrying an ESCO skill_id counts even if its name is unresolvable."""
    ids = _seed_skills(["SQL", "Python", "Power BI", "Excel", "data mining"])
    _seed_relation("2511", [ids["data mining"]], "essential")
    cap = TranslatedCapability(
        skill="dolování dat",  # not seeded → name won't resolve
        evidence_quote="…",
        confidence=0.8,
        source_type="thesis",
        skill_id=ids["data mining"],  # but the ESCO id is stored
    )
    enriched = score_match(_profile([]), [cap], _ad(isco_code="2511"))
    d = enriched.skill_fit_detail
    assert d.role_essential_evidenced == 1
    assert d.bonus_applied == 3.0
    assert "data mining" in d.role_essential_matched


def test_enrichment_bonus_is_capped():
    extras = [f"skill{i}" for i in range(10)]
    ids = _seed_skills(["SQL", "Python", "Power BI", "Excel", *extras])
    _seed_relation("2511", [ids[name] for name in extras], "essential")
    profile = _profile(["SQL", *extras])  # evidences all 10 extras

    enriched = score_match(profile, [], _ad(isco_code="2511"))
    assert enriched.skill_fit_detail.bonus_applied == ROLE_BONUS_CAP
    assert enriched.skill_fit <= 100.0


def test_no_enrichment_when_isco_has_no_role_skills():
    _seed_skills(["SQL", "Python", "Power BI", "Excel"])
    enriched = score_match(_profile(["SQL", "Python"]), [], _ad(isco_code="9999"))
    assert enriched.skill_fit_detail.role_essential_total == 0
    assert enriched.skill_fit_detail.bonus_applied == 0.0


def test_no_enrichment_without_isco():
    _seed_skills(["SQL", "Python"])
    enriched = score_match(_profile(["SQL"]), [], _ad(isco_code=None))
    assert enriched.skill_fit_detail.isco_code is None
    assert enriched.skill_fit_detail.bonus_applied == 0.0
