"""Job-ad repository tests."""

from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session
from cv_bau_students.db_models import JobAdRow, Skill, SkillIndustryMap
from cv_bau_students.jobads.repo import (
    get_ad_by_id,
    get_target_skills,
    list_ads,
    set_ad_isco,
    set_target_skills,
    store_ad,
    suggest_target_skills,
)
from cv_bau_students.models import JobAd, LanguageRequirement


def _seed_taxonomy() -> None:
    with get_session() as session:
        _truncate_taxonomy(session)
        canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
        _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)


def _example_ad() -> JobAd:
    return JobAd(
        title="Backend Developer",
        employer="Avast",
        location="Prague",
        remote_mode="hybrid",
        level="medior",
        domain="backend-developer",
        must_have=["Python", "PostgreSQL", "REST API"],
        nice_to_have=["Docker", "Kubernetes"],
        languages_required=[LanguageRequirement(language="English", min_level="B2")],
        raw_text="Backend developer for a medior role at Avast in Prague...",
        source="synthetic",
    )


def test_set_ad_isco_clears_stale_code():
    _seed_taxonomy()
    ad_id = store_ad(_example_ad())
    set_ad_isco(ad_id, isco_code="2511", occupation_label="data analyst", method="lexical")
    assert get_ad_by_id(ad_id).isco_code == "2511"
    # Re-resolution to unresolved must CLEAR the stale code (not keep it).
    set_ad_isco(ad_id, isco_code=None, occupation_label=None, method="unresolved")
    fetched = get_ad_by_id(ad_id)
    assert fetched.isco_code is None
    assert fetched.isco_occupation_label is None
    assert fetched.isco_method == "unresolved"


def test_target_skills_suggest_and_roundtrip():
    # Seed ESCO skills + an occupation map for ISCO 2511.
    with get_session() as session:
        for n in ("data mining", "reporting", "noise"):
            session.add(Skill(canonical_name=n, canonical_name_en=n, esco_uri=f"uri:{n}"))
        session.flush()
        ids = {
            s.canonical_name: s.id
            for s in session.query(Skill).filter(Skill.esco_uri.is_not(None)).all()
        }
        session.add(
            SkillIndustryMap(
                skill_id=ids["data mining"], isco_code="2511", relation_type="essential"
            )
        )
        session.add(
            SkillIndustryMap(skill_id=ids["reporting"], isco_code="2511", relation_type="optional")
        )
        ad = JobAdRow(
            title="Data Analyst",
            location="Praha",
            remote_mode="hybrid",
            level="junior",
            domain="data-analyst",
            source="synthetic",
            raw_text="...",
            isco_code="2511",
        )
        session.add(ad)
        session.flush()
        ad_id = ad.id

    sugg = suggest_target_skills(ad_id)
    assert "data mining" in [n for _, n in sugg["core"]]
    assert "reporting" in [n for _, n in sugg["optional"]]

    assert get_target_skills(ad_id) is None  # nothing curated yet
    set_target_skills(ad_id, core=[ids["data mining"]], optional=[ids["reporting"]])
    got = get_target_skills(ad_id)
    assert got == {"core": {ids["data mining"]}, "optional": {ids["reporting"]}}

    # Re-save replaces wholesale; core wins on overlap.
    set_target_skills(ad_id, core=[ids["reporting"]], optional=[ids["reporting"]])
    got = get_target_skills(ad_id)
    assert got["core"] == {ids["reporting"]}
    assert got.get("optional", set()) == set()


def test_store_ad_then_list_returns_normalised_skills():
    _seed_taxonomy()
    ad = _example_ad()
    store_ad(ad)
    ads = list_ads()
    assert len(ads) == 1
    fetched = ads[0]
    assert fetched.title == "Backend Developer"
    assert set(fetched.must_have) == {"Python", "PostgreSQL", "REST API"}
    assert set(fetched.nice_to_have) == {"Docker", "Kubernetes"}


def test_unresolvable_skill_is_dropped_silently():
    """Skills not in the taxonomy are not persisted as JobAdSkill rows —
    we still keep the raw_text so downstream LLMs can recover."""
    _seed_taxonomy()
    ad = _example_ad().model_copy(update={"must_have": ["Python", "Quantum Llama Whisperer"]})
    store_ad(ad)
    fetched = list_ads()[0]
    assert "Python" in fetched.must_have
    assert "Quantum Llama Whisperer" not in fetched.must_have
    assert "Quantum Llama Whisperer" not in fetched.nice_to_have


def test_languages_round_trip():
    _seed_taxonomy()
    ad = _example_ad()
    store_ad(ad)
    fetched = list_ads()[0]
    assert fetched.languages_required[0].language == "English"
    assert fetched.languages_required[0].min_level == "B2"
