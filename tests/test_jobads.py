"""Job-ad repository tests."""

from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session
from cv_bau_students.db_models import JobAdRow, Skill, SkillIndustryMap
from cv_bau_students.jobads.repo import (
    get_ad_by_id,
    get_target_skills,
    list_ads,
    set_ad_fields_and_skills,
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


def test_truncate_job_ads_clears_target_skills():
    """Reloading the ad corpus must not orphan recruiter-curated target skills."""
    from scripts.normalise_scraped_ads import _truncate_job_ads

    with get_session() as session:
        s = Skill(canonical_name="data mining", canonical_name_en="data mining", esco_uri="uri:dm")
        session.add(s)
        session.flush()
        sid = s.id
        ad = JobAdRow(
            title="Data Analyst",
            location="Praha",
            remote_mode="hybrid",
            level="junior",
            domain="data-analyst",
            source="scraped",
            raw_text="...",
        )
        session.add(ad)
        session.flush()
        ad_id = ad.id
    set_target_skills(ad_id, core=[sid], optional=[])
    assert get_target_skills(ad_id) is not None

    _truncate_job_ads()
    assert get_target_skills(ad_id) is None  # not orphaned


def test_set_ad_isco_clears_curated_skills_on_isco_change():
    """Changing an ad's ISCO drops curated target skills picked for the old role."""
    with get_session() as session:
        s = Skill(canonical_name="data mining", canonical_name_en="data mining", esco_uri="uri:dmc")
        session.add(s)
        session.flush()
        sid = s.id
        ad = JobAdRow(
            title="X",
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
    set_target_skills(ad_id, core=[sid], optional=[])
    assert get_target_skills(ad_id) is not None
    # Re-resolve to a DIFFERENT ISCO → curated set must clear.
    set_ad_isco(ad_id, isco_code="2120", occupation_label="statistician", method="llm")
    assert get_target_skills(ad_id) is None
    # Same-ISCO re-write must NOT clear.
    set_target_skills(ad_id, core=[sid], optional=[])
    set_ad_isco(ad_id, isco_code="2120", occupation_label="statistician", method="lexical")
    assert get_target_skills(ad_id) is not None


def test_truncate_taxonomy_clears_target_skills():
    """Re-seeding the taxonomy must clear AdTargetSkill (FK to skills.id)."""
    from scripts.load_seeds import _truncate_taxonomy

    with get_session() as session:
        s = Skill(canonical_name="data mining", esco_uri="uri:dm2")
        session.add(s)
        session.flush()
        sid = s.id
        ad = JobAdRow(
            title="X",
            location="Praha",
            remote_mode="hybrid",
            level="junior",
            domain="data-analyst",
            source="synthetic",
            raw_text="...",
        )
        session.add(ad)
        session.flush()
        ad_id = ad.id
    set_target_skills(ad_id, core=[sid], optional=[])
    with get_session() as session:
        _truncate_taxonomy(session)
    assert get_target_skills(ad_id) is None


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


def test_set_ad_fields_updates_domain():
    """set_ad_fields_and_skills can realign the ad's domain (so the demo target,
    scraped as 'general', maps onto the data-analyst level_checklists rubric and
    bridge_fit computes instead of returning the N/A sentinel)."""
    _seed_taxonomy()
    ad_id = store_ad(_example_ad().model_copy(update={"domain": "general"}))
    set_ad_fields_and_skills(ad_id, domain="data-analyst")
    assert get_ad_by_id(ad_id).domain == "data-analyst"
