"""Taxonomy repository tests against the seeded in-memory DB."""

from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillAlias
from cv_bau_students.taxonomy.repo import (
    _esco_index,
    canonical_for_alias,
    descendants_of,
    normalize,
    resolve_many_esco,
    resolve_skill,
    resolve_skill_esco,
)


def _seed_esco(rows: list[dict]) -> dict[str, int]:
    """Seed ESCO-namespace skills (+ optional aliases); returns name→id.

    rows: [{"cn": canonical_cs, "en": canonical_en, "uri": esco_uri,
            "aliases": [..]}]. Clears the lru-cached index afterwards.
    """
    out: dict[str, int] = {}
    with get_session() as session:
        for r in rows:
            s = Skill(canonical_name=r["cn"], canonical_name_en=r.get("en"), esco_uri=r["uri"])
            session.add(s)
            session.flush()
            out[r["cn"]] = s.id
            for a in r.get("aliases", []):
                session.add(
                    SkillAlias(alias=a.lower(), canonical_id=s.id, lang="en", source="esco")
                )
    _esco_index.cache_clear()
    return out


def _seed() -> dict[str, int]:
    with get_session() as session:
        _truncate_taxonomy(session)
        canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
        _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)
    return canonical_to_id


def test_resolve_canonical_exact_match():
    _seed()
    canonical_for_alias.cache_clear()
    match = resolve_skill("Python")
    assert match is not None
    _, canonical = match
    assert canonical == "Python"


def test_resolve_alias_lowercase():
    _seed()
    canonical_for_alias.cache_clear()
    match = resolve_skill("k8s")
    assert match is not None
    _, canonical = match
    assert canonical == "Kubernetes"


def test_resolve_unknown_returns_none():
    _seed()
    canonical_for_alias.cache_clear()
    assert resolve_skill("Quantum Llama Whisperer") is None


def test_resolve_skill_diacritics_insensitive_fallback():
    """A CV without háčky/čárky still resolves to the diacritic canonical."""
    from cv_bau_students.taxonomy.repo import _seed_skill_index

    with get_session() as session:
        s = Skill(canonical_name="datové modelování")
        session.add(s)
        session.flush()
        sid = s.id
    _seed_skill_index.cache_clear()
    match = resolve_skill("datove modelovani")  # no diacritics
    assert match is not None
    assert match[0] == sid
    assert match[1] == "datové modelování"


def test_descendants_of_javascript_includes_react():
    canonical_to_id = _seed()
    canonical_for_alias.cache_clear()
    js_id = canonical_to_id["JavaScript"]
    descendants = descendants_of(js_id)
    descendant_canonicals = {name for name in (canonical_for_alias(str(c)) for c in []) if name}
    # Resolve descendant ids back to names for assertion clarity.
    with get_session() as session:
        from sqlalchemy import select

        from cv_bau_students.db_models import Skill

        rows = (
            session.execute(select(Skill.canonical_name).where(Skill.id.in_(descendants)))
            .scalars()
            .all()
        )
        descendant_canonicals = set(rows)
    assert "React" in descendant_canonicals
    assert "TypeScript" in descendant_canonicals


# --- ESCO-namespace resolution (Layer 1) -----------------------------------


def test_normalize_strips_diacritics_and_punct():
    assert normalize("Datový Analytik!") == "datovy analytik"
    assert normalize("  ČIŠTĚNÍ-dat ") == "cisteni dat"
    assert normalize(None) == ""


def test_resolve_skill_esco_prefers_esco_node_over_seed_duplicate():
    # A seed-style "Python" (no esco_uri) AND the ESCO node both exist.
    with get_session() as session:
        session.add(Skill(canonical_name="Python"))  # seed duplicate, no esco_uri
    esco = _seed_esco(
        [
            {
                "cn": "Python (počítačové programování)",
                "en": "Python (computer programming)",
                "uri": "uri:py",
                "aliases": ["python"],
            }
        ]
    )
    match = resolve_skill_esco("Python")
    assert match is not None
    assert match[0] == esco["Python (počítačové programování)"]  # ESCO id, not the seed row


def test_resolve_skill_esco_fuzzy_match():
    ids = _seed_esco([{"cn": "data modelling", "en": "data modelling", "uri": "uri:dm"}])
    match = resolve_skill_esco("data modeling")  # American spelling → fuzzy
    assert match is not None
    assert match[0] == ids["data modelling"]


def test_resolve_skill_esco_none_for_seed_only_skill():
    with get_session() as session:
        session.add(Skill(canonical_name="Power BI"))  # no esco_uri
    _esco_index.cache_clear()
    assert resolve_skill_esco("Power BI") is None


def test_resolve_skill_esco_unknown_returns_none():
    _seed_esco([{"cn": "SQL", "en": "SQL", "uri": "uri:sql"}])
    assert resolve_skill_esco("Quantum Llama Whisperer") is None


def test_resolve_many_esco_dedupes_and_drops_misses():
    ids = _seed_esco(
        [
            {"cn": "SQL", "en": "SQL", "uri": "uri:sql"},
            {"cn": "Python", "en": "Python", "uri": "uri:py"},
        ]
    )
    got = resolve_many_esco(["SQL", "sql", "Python", "nonexistent skill"])
    assert got == {ids["SQL"], ids["Python"]}
