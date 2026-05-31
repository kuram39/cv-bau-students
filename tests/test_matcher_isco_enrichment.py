"""Tests for the MVP skills-coverage headline (`matcher.score`).

skill_fit = % of the *target skill set* the candidate covers. Target set:
recruiter-curated skills (skill-picker, ESCO ids) when present, else the ad's
must ∪ nice (seed ids). total == skill_fit (skills-only); personal_fit retired.
"""

from __future__ import annotations

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill
from cv_bau_students.jobads.repo import set_target_skills, store_ad
from cv_bau_students.matcher.score import score_match
from cv_bau_students.models import CandidateProfile, JobAd, TranslatedCapability


def _seed_skills(names: list[str]) -> dict[str, int]:
    """ESCO-namespace skills (esco_uri) — resolvable by both resolve_skill
    (canonical_name) and resolve_skill_esco."""
    out: dict[str, int] = {}
    with get_session() as session:
        for n in names:
            s = Skill(canonical_name=n, canonical_name_en=n, esco_uri=f"uri:{n}")
            session.add(s)
            session.flush()
            out[n] = s.id
    return out


def _profile(skills: list[str]) -> CandidateProfile:
    return CandidateProfile(
        candidate_type="student", language="en", explicit_skills=skills, summary="data student"
    )


def _ad(**kw) -> JobAd:
    base = dict(
        id=1,
        title="Data Analyst",
        location="Praha",
        remote_mode="hybrid",
        level="junior",
        domain="data-analyst",
        must_have=["SQL", "Excel"],
        nice_to_have=["Python"],
        raw_text="analyst role",
        source="synthetic",
    )
    base.update(kw)
    return JobAd(**base)


def test_curated_set_is_the_coverage_denominator():
    ids = _seed_skills(["SQL", "Python", "data mining", "reporting", "Excel"])
    ad = _ad()
    ad_id = store_ad(ad)
    ad = ad.model_copy(update={"id": ad_id})
    # Recruiter curates 4 skills; candidate evidences 2 of them.
    set_target_skills(
        ad_id, core=[ids["SQL"], ids["data mining"]], optional=[ids["Python"], ids["reporting"]]
    )

    score = score_match(_profile(["SQL", "Python"]), [], ad)
    d = score.skill_fit_detail
    assert d.target_source == "curated"
    assert d.role_essential_total == 4
    assert d.role_essential_evidenced == 2
    assert score.skill_fit == 50.0  # 2 / 4
    assert score.total == 50.0  # skills-only headline
    assert score.personal_fit == 0.0
    assert "SQL" in d.role_essential_matched


def test_stored_capability_skill_id_counts_toward_curated():
    ids = _seed_skills(["SQL", "data mining"])
    ad = _ad(must_have=["SQL"], nice_to_have=[])
    ad_id = store_ad(ad)
    ad = ad.model_copy(update={"id": ad_id})
    set_target_skills(ad_id, core=[ids["data mining"]], optional=[])
    cap = TranslatedCapability(
        skill="dolování dat",  # unresolvable name
        evidence_quote="…",
        confidence=0.8,
        source_type="thesis",
        skill_id=ids["data mining"],  # but the ESCO id is stored
    )
    score = score_match(_profile([]), [cap], ad)
    assert score.skill_fit == 100.0  # the one curated skill is covered via skill_id
    assert "data mining" in score.skill_fit_detail.role_essential_matched


def test_must_nice_fallback_when_no_curated_set():
    _seed_skills(["SQL", "Excel", "Python"])
    ad = _ad()  # must=[SQL,Excel], nice=[Python]; no curated set
    ad_id = store_ad(ad)
    ad = ad.model_copy(update={"id": ad_id})

    score = score_match(_profile(["SQL", "Python"]), [], ad)
    d = score.skill_fit_detail
    assert d.target_source == "must_nice"
    assert d.role_essential_total == 3  # SQL, Excel, Python
    assert d.role_essential_evidenced == 2  # SQL + Python
    assert round(score.skill_fit, 1) == 66.7
    assert score.total == score.skill_fit


def test_no_target_set_scores_zero():
    _seed_skills(["SQL"])
    ad = _ad(must_have=[], nice_to_have=[])
    ad_id = store_ad(ad)
    ad = ad.model_copy(update={"id": ad_id})
    score = score_match(_profile(["SQL"]), [], ad)
    assert score.skill_fit == 0.0
