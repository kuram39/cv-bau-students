"""Skill-taxonomy repository — alias resolution + hierarchy queries.

SQL-backed (SQLite via SQLAlchemy). Functions return canonical names
plus per-row ids so the matcher can join on `job_ad_skills` /
`level_checklists` rows without re-resolving strings.
"""

from collections.abc import Iterable
from functools import lru_cache

from sqlalchemy import select

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillAlias, SkillHierarchy, SkillIndustryMap


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


def names_for_ids(skill_ids: Iterable[int]) -> dict[int, str]:
    """Batch-map skill_ids → canonical names (single query).

    Used by the matcher to turn matched/missing skill-id sets into the
    human-readable names the recruiter audit panel shows.
    """
    ids = [i for i in dict.fromkeys(skill_ids)]  # dedupe, preserve order
    if not ids:
        return {}
    with get_session() as session:
        rows = session.execute(
            select(Skill.id, Skill.canonical_name).where(Skill.id.in_(ids))
        ).all()
    return {row.id: row.canonical_name for row in rows}


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


def expected_skills_for_isco(
    isco_code: str,
    relation: str = "essential",
) -> list[int]:
    """Return skill_ids the ISCO occupation expects for `relation`.

    Used by the target-role-first matcher: pick an ISCO code, get the
    expected skill set from ESCO's occupation-skill mapping, intersect
    with the candidate's translated capabilities to score coverage and
    surface the bridge gap.

    Args:
        isco_code: ISCO-08 4-digit code (e.g. "25120" for software
            developer). Stored as string because some ESCO codes have
            leading zeros (e.g. "0210").
        relation: "essential" (default) or "optional". Pass "" to get
            all skills regardless of relation type.

    Returns sorted list of skill_ids — empty list when the ISCO code
    has no mapped skills (unknown code, or Phase 11c not yet loaded).
    """
    if not isco_code:
        return []
    with get_session() as session:
        stmt = select(SkillIndustryMap.skill_id).where(
            SkillIndustryMap.isco_code == isco_code.strip()
        )
        if relation:
            stmt = stmt.where(SkillIndustryMap.relation_type == relation)
        rows = session.execute(stmt).scalars().all()
    return sorted(set(rows))
