"""Skill-taxonomy repository — alias resolution + hierarchy queries.

SQL-backed (SQLite via SQLAlchemy). Functions return canonical names
plus per-row ids so the matcher can join on `job_ad_skills` /
`level_checklists` rows without re-resolving strings.
"""

import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache

from rapidfuzz import fuzz, process
from sqlalchemy import select

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Skill, SkillAlias, SkillHierarchy, SkillIndustryMap

# Fuzzy-match acceptance floor for ESCO resolution (token_sort_ratio, 0-100).
# 92 is strict enough to avoid false links while catching morphology / minor
# wording drift ("data modelling" ~ "data modeling"). Tune with real CVs.
_FUZZY_THRESHOLD = 92


def normalize(text: str | None) -> str:
    """Lowercase, strip diacritics, drop punctuation, collapse whitespace.

    Single source of truth for skill/occupation string normalisation —
    `roles/isco_resolver` imports this. Diacritics-insensitive so Czech
    CV phrasing matches the taxonomy regardless of háčky/čárky.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = "".join(c if c.isalnum() else " " for c in stripped.lower())
    return " ".join(cleaned.split())


# Proficiency/level qualifiers (cs+en, post-diacritic-strip) that decorate a
# skill without changing it — "SQL (pokročilý)", "základy Pythonu", "Excel advanced".
_LEVEL_WORDS = re.compile(
    r"\b(zaklady|zakladni|pokrocily|pokrocila|pokrocile|expert|advanced|basic|"
    r"intermediate|samouk|mirne|pokrocila)\b"
)
# UK/US spelling so candidate "data visualization" reaches ESCO "data visualisation".
_SPELLING = (
    ("visualization", "visualisation"),
    ("modeling", "modelling"),
    ("optimization", "optimisation"),
    ("organization", "organisation"),
    ("analyze", "analyse"),
)


def canonicalize_skill_phrase(name: str) -> str:
    """Normalised form with proficiency qualifiers + parentheticals stripped and
    UK→UK spelling unified. Measured to lift ESCO resolution ~21%→33% on the
    demo CVs (recovers "SQL (pokročilý)", "základy Pythonu", "Git (základy)"…)
    deterministically — no embeddings/LLM needed. Used as a second-pass key in
    `resolve_skill_esco`.
    """
    no_parens = re.sub(r"\(.*?\)", " ", name)  # drop "(pandas, numpy)" noise
    norm = normalize(no_parens)
    norm = _LEVEL_WORDS.sub(" ", norm)
    for src, dst in _SPELLING:
        norm = norm.replace(src, dst)
    return " ".join(norm.split())


@lru_cache(maxsize=8192)
def resolve_skill(name: str) -> tuple[int, str] | None:
    """Map a raw skill string to (canonical_id, canonical_name).

    Resolution order:
    1. Exact canonical_name (CS or EN) — `ilike` for case-insensitivity.
    2. Alias in any language / source (lowercase match).

    Returns None when no match. Aliases are deduplicated by (alias, lang,
    source) at the DB level so the first match is canonical.

    Memoized: the matcher ranks a candidate against many ads, re-resolving the
    same skill strings each time; the diacritics fallback also fuzz-scans the
    full index, so caching by name turns per-ad re-resolution into O(1).
    Cleared per test via conftest; loaders run as one-shot processes.
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
        if alias_row is not None:
            _, skill = alias_row
            return skill.id, skill.canonical_name

    # Diacritics-insensitive fallback: `ilike` does NOT strip háčky/čárky, so a
    # CV writing "datove modelovani" (no diacritics) misses the canonical
    # "datové modelování". Match on the normalized form via a cached index.
    sid = _seed_skill_index().get(normalize(stripped))
    if sid is None:
        return None
    with get_session() as session:
        skill = session.get(Skill, sid)
        return (skill.id, skill.canonical_name) if skill else None


@lru_cache(maxsize=1)
def _seed_skill_index() -> dict[str, int]:
    """Normalized label → skill_id over ALL skills (canonical cs/en) + aliases.

    Powers the diacritics-insensitive fallback in `resolve_skill` (seed-space
    must/nice/bridge). Not ESCO-restricted — unlike `_esco_index`. First writer
    wins per key (canonicals before aliases)."""
    index: dict[str, int] = {}
    with get_session() as session:
        for sid, cs, en in session.execute(
            select(Skill.id, Skill.canonical_name, Skill.canonical_name_en)
        ).all():
            for label in (cs, en):
                key = normalize(label)
                if key:
                    index.setdefault(key, sid)
        for alias, cid in session.execute(select(SkillAlias.alias, SkillAlias.canonical_id)).all():
            key = normalize(alias)
            if key:
                index.setdefault(key, cid)
    return index


@lru_cache(maxsize=1)
def _esco_index() -> tuple[dict[str, int], list[str]]:
    """Build once: normalized ESCO label/alias → skill_id, + a key list.

    Covers only ESCO rows (`esco_uri IS NOT NULL`) so resolution lands in
    the same namespace as the occupation→skill map. Both `canonical_name`
    (cs) and `canonical_name_en` are indexed, plus ESCO-sourced aliases.
    First writer wins per normalized key (canonicals inserted before
    aliases, so a canonical never loses to an alias collision).
    """
    index: dict[str, int] = {}
    with get_session() as session:
        rows = session.execute(
            select(Skill.id, Skill.canonical_name, Skill.canonical_name_en).where(
                Skill.esco_uri.is_not(None)
            )
        ).all()
        for sid, cs, en in rows:
            for label in (cs, en):
                key = normalize(label)
                if key:
                    index.setdefault(key, sid)
        alias_rows = session.execute(
            select(SkillAlias.alias, SkillAlias.canonical_id)
            .join(Skill, Skill.id == SkillAlias.canonical_id)
            .where(Skill.esco_uri.is_not(None))
        ).all()
        for alias, cid in alias_rows:
            key = normalize(alias)
            if key:
                index.setdefault(key, cid)
    return index, list(index.keys())


@lru_cache(maxsize=8192)
def resolve_skill_esco(name: str) -> tuple[int, str] | None:
    """Resolve a free-text skill into the ESCO namespace (id, canonical_name).

    Exact normalized match → fuzzy fallback (rapidfuzz token_sort_ratio over
    the ESCO label index, accepted at `_FUZZY_THRESHOLD`). ESCO-only, so the
    id is comparable with `expected_skills_for_isco`. Returns None when no
    confident match — the caller then skips that skill rather than guessing.

    Memoized: each fuzzy miss scans the ~90k-entry index, and the matcher
    re-resolves the same candidate/ad skills once per scored ad — caching by
    name collapses that to one scan per unique string. Cleared per test.
    """
    if not name:
        return None
    index, keys = _esco_index()

    def _lookup(key: str) -> int | None:
        if not key:
            return None
        sid = index.get(key)
        if sid is not None:
            return sid
        match = process.extractOne(key, keys, scorer=fuzz.token_sort_ratio)
        if match is None or match[1] < _FUZZY_THRESHOLD:
            return None
        return index[match[0]]

    # Pass 1: raw normalised. Pass 2: strip proficiency qualifiers / parentheticals
    # + unify spelling (recovers "SQL (pokročilý)" → "SQL", etc.).
    sid = _lookup(normalize(name))
    if sid is None:
        canon = canonicalize_skill_phrase(name)
        if canon != normalize(name):
            sid = _lookup(canon)
    if sid is None:
        return None
    with get_session() as session:
        skill = session.get(Skill, sid)
        return (skill.id, skill.canonical_name) if skill else None


def resolve_many_esco(names: Iterable[str]) -> set[int]:
    """Batch `resolve_skill_esco` → set of ESCO skill_ids (drops misses)."""
    out: set[int] = set()
    for n in names:
        match = resolve_skill_esco(n)
        if match:
            out.add(match[0])
    return out


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


def clear_resolution_caches() -> None:
    """Invalidate all memoized resolution/index state.

    The resolvers + indexes are lru_cached on DB content; call this after a
    loader mutates `skills`/`skill_aliases` so a later lookup in the same
    process doesn't return a stale (often negative) cached result."""
    resolve_skill.cache_clear()
    resolve_skill_esco.cache_clear()
    canonical_for_alias.cache_clear()
    _seed_skill_index.cache_clear()
    _esco_index.cache_clear()


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
