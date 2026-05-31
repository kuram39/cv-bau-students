"""Base-skill preset + option-pool + deterministic rescore (recruiter picker).

The preset is the position's base-case skill set (shared comparator for
students vs experienced); it resolves English ESCO terms through the SAME
resolver the candidate side uses, so saving it actually scores. Saving a
target set re-scores every candidate for the ad without any LLM call.
"""

from __future__ import annotations

from cv_bau_students.candidates import repo as cr
from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill
from cv_bau_students.jobads.repo import (
    apply_base_preset,
    base_preset_ids,
    get_target_skills,
    set_ad_isco,
    store_ad,
    target_skill_options,
)
from cv_bau_students.models import CandidateProfile, JobAd


def _seed_esco(names: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    with get_session() as session:
        for n in names:
            s = Skill(canonical_name=n, canonical_name_en=n, esco_uri=f"uri:{n}")
            session.add(s)
            session.flush()
            out[n] = s.id
    return out


def _ad(**kw) -> JobAd:
    base = dict(
        id=1,
        title="Datový analytik",
        location="Praha",
        remote_mode="hybrid",
        level="junior",
        domain="data-analyst",
        must_have=["SQL", "Excel"],
        nice_to_have=["Python"],
        raw_text="analyst",
        source="synthetic",
    )
    base.update(kw)
    return JobAd(**base)


def _store_ad_with_isco(ad: JobAd, isco: str | None) -> int:
    ad_id = store_ad(ad)
    if isco is not None:
        set_ad_isco(ad_id, isco_code=isco, occupation_label="data analyst", method="test")
    return ad_id


def test_preset_for_isco_resolves_candidate_aligned_ids():
    ids = _seed_esco(["SQL", "Python", "data analysis", "statistics", "machine learning"])
    ad_id = _store_ad_with_isco(_ad(), "2511")
    preset = base_preset_ids(ad_id)
    # 2511 preset core terms: SQL, Python, data analysis (data visualisation
    # has no seeded esco node here → drops out).
    assert ids["SQL"] in preset["core"]
    assert ids["Python"] in preset["core"]
    assert ids["data analysis"] in preset["core"]
    # ML is optional in the preset, statistics too; both resolve here.
    assert ids["machine learning"] in preset["optional"]


def test_preset_falls_back_to_ad_must_nice_when_no_isco_preset():
    ids = _seed_esco(["SQL", "Excel", "Python"])
    ad_id = _store_ad_with_isco(_ad(), None)  # no ISCO → fall back to must/nice
    preset = base_preset_ids(ad_id)
    assert preset["core"] == {ids["SQL"], ids["Excel"]}
    assert preset["optional"] == {ids["Python"]}


def test_apply_base_preset_persists_curated_set():
    _seed_esco(["SQL", "Python", "data analysis"])
    ad_id = _store_ad_with_isco(_ad(), "2511")
    applied = apply_base_preset(ad_id)
    stored = get_target_skills(ad_id)
    assert stored is not None
    assert stored["core"] == applied["core"]
    assert stored["optional"] == applied["optional"]


def test_apply_base_preset_noop_preserves_manual_curation():
    """When nothing resolves, apply_base_preset must NOT wipe the recruiter's
    existing manual target set (set_target_skills would delete-then-insert)."""
    from cv_bau_students.jobads.repo import set_target_skills

    ids = _seed_esco(["Foo"])
    # No ISCO preset, must/nice are unresolvable nonsense → empty preset.
    ad = _ad(must_have=["UtterlyUnknownSkill"], nice_to_have=[])
    ad_id = _store_ad_with_isco(ad, None)
    set_target_skills(ad_id, core=[ids["Foo"]], optional=[])  # manual curation

    preset = apply_base_preset(ad_id)
    assert preset["core"] == set() and preset["optional"] == set()
    # Manual set survived.
    assert get_target_skills(ad_id) == {"core": {ids["Foo"]}, "optional": set()}


def test_options_pool_includes_ad_requirements_and_preset():
    ids = _seed_esco(["SQL", "Python", "data analysis"])
    ad_id = _store_ad_with_isco(_ad(), "2511")
    opts = target_skill_options(ad_id)
    all_ids = {i for i, _ in opts["core"]} | {i for i, _ in opts["optional"]}
    # SQL (ad must + preset) and data analysis (preset) must be selectable.
    assert ids["SQL"] in all_ids
    assert ids["data analysis"] in all_ids


def test_options_curated_tier_wins_over_isco_tier():
    """A skill curated as OPTIONAL must appear in the optional option pool even
    if ISCO/preset class it essential — else the saved default isn't in that
    multiselect's options and Streamlit raises (default not in options)."""
    from cv_bau_students.jobads.repo import set_target_skills

    ids = _seed_esco(["SQL", "Python", "machine learning"])
    ad_id = _store_ad_with_isco(_ad(), "2511")
    # Curate ML as optional (the 2511 preset already does; assert tier wins).
    set_target_skills(ad_id, core=[ids["SQL"], ids["Python"]], optional=[ids["machine learning"]])

    opts = target_skill_options(ad_id)
    core_pool = {i for i, _ in opts["core"]}
    opt_pool = {i for i, _ in opts["optional"]}
    assert ids["machine learning"] in opt_pool
    assert ids["machine learning"] not in core_pool


def test_rescore_ad_recomputes_after_target_change():
    _seed_esco(["SQL", "Python", "data analysis"])
    ad_id = _store_ad_with_isco(_ad(must_have=["SQL"], nice_to_have=[]), "2511")
    profile = CandidateProfile(
        candidate_type="student", language="en", explicit_skills=["SQL"], summary="s"
    )
    cid = cr.store_initial_candidate(file_hash="h1", profile=profile, capabilities=[])
    cr.record_interest(cid, ad_id, "interested")

    # Score once with no curated set (must=SQL only → 100%).
    from cv_bau_students.jobads.repo import get_ad_by_id
    from cv_bau_students.matcher.score import score_match

    m0 = score_match(profile, [], get_ad_by_id(ad_id))
    cr.store_match(cid, ad_id, match=m0)
    assert m0.skill_fit == 100.0

    # Recruiter curates a 3-skill set; candidate covers only SQL → 1/3.
    apply_base_preset(ad_id)  # core = SQL, Python, data analysis
    n = cr.rescore_ad(ad_id)
    assert n == 1
    d = cr.get_candidate_detail(cid, ad_id)
    assert d.match.skill_fit_detail.target_source == "curated"
    assert d.match.skill_fit_detail.role_essential_total == 3
    assert d.match.skill_fit_detail.role_essential_evidenced == 1
    assert round(d.match.skill_fit, 1) == 33.3
