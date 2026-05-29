"""Taxonomy repository tests against the seeded in-memory DB."""

from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session
from cv_bau_students.taxonomy.repo import canonical_for_alias, descendants_of, resolve_skill


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
