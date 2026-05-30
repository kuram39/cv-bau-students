"""Skill-taxonomy repository — alias resolution + hierarchy queries.

SQL-backed (SQLite via SQLAlchemy). Functions return canonical names
plus per-row ids so the matcher can join on `job_ad_skills` /
`level_checklists` rows without re-resolving strings.
"""

from functools import lru_cache

from sqlalchemy import select

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillAlias, SkillHierarchy


def resolve_skill(name: str) -> tuple[int, str] | None:
    """Map a raw skill string to (canonical_id, canonical_name).

    Resolution order:
    1. Exact canonical_name (CS or EN) — `ilike` for case-insensitivity.
    2. Alias in any language / source (lowercase match).

    Returns None when no match. Aliases are deduplicated by (alias, lang,
    source) at the DB level so the first match is canonical.
    """
    if not name:
        return None
    stripped = name.strip()
    lowered = stripped.lower()
    with get_session() as session:
        # Exact CS or EN canonical match.
        skill = (
            session.execute(
                select(Skill).where(
                    (Skill.canonical_name.ilike(stripped))
                    | (Skill.canonical_name_en.ilike(stripped))
                )
            )
            .scalars()
            .first()
        )
        if skill is not None:
            return skill.id, skill.canonical_name
        # Alias lookup — case-insensitive via lower(alias).
        alias_row = session.execute(
            select(SkillAlias, Skill)
            .join(Skill, Skill.id == SkillAlias.canonical_id)
            .where(SkillAlias.alias.ilike(lowered))
        ).first()
        if alias_row is None:
            return None
        _, skill = alias_row
        return skill.id, skill.canonical_name


def descendants_of(parent_id: int) -> list[int]:
    """All transitive children of a skill (BFS, since SQLite needs
    explicit recursion to avoid a recursive CTE on the prototype scale)."""
    seen: set[int] = set()
    queue = [parent_id]
    with get_session() as session:
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            child_ids = (
                session.execute(
                    select(SkillHierarchy.child_id).where(SkillHierarchy.parent_id == current)
                )
                .scalars()
                .all()
            )
            queue.extend(child_ids)
    seen.discard(parent_id)
    return sorted(seen)


@lru_cache(maxsize=256)
def canonical_for_alias(raw: str) -> str | None:
    """Convenience wrapper — return the canonical name for a raw string."""
    match = resolve_skill(raw)
    return match[1] if match else None
