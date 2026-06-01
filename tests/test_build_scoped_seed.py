"""scripts.build_scoped_seed — keeps only the data-role family + demo's own skills.

Builds a tiny synthetic "full" SQLite, scopes it to one occupation, and asserts
the filter keeps the in-scope skills (+ hand-seed + the demo candidate's
capability skill) and drops out-of-scope rows, while copying candidate-side rows.
"""

from __future__ import annotations

from datetime import datetime

from scripts.build_scoped_seed import build_scoped
from sqlalchemy import create_engine, func, insert, select

from cv_bau_students.db_models import (
    Base,
    Candidate,
    JobAdRow,
    JobAdSkill,
    Occupation,
    Skill,
    SkillAlias,
    SkillIndustryMap,
    TranslatedCapabilityRow,
)

_NOW = datetime(2026, 1, 1, 12, 0, 0)
URI_KEEP = "uri:occ:keep"
URI_DROP = "uri:occ:drop"


def _seed_full(url: str) -> None:
    eng = create_engine(url, future=True)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(
            insert(Skill),
            [
                {"id": 1, "canonical_name": "data analysis", "esco_uri": "u:1"},  # in-scope
                {
                    "id": 2,
                    "canonical_name": "ETL",
                    "esco_uri": "u:2",
                },  # in-scope (other role uri but same kept occ)
                {"id": 3, "canonical_name": "welding", "esco_uri": "u:3"},  # OUT of scope
                {"id": 4, "canonical_name": "SQL", "esco_uri": None},  # hand-seed → always kept
                {"id": 5, "canonical_name": "thesis-skill", "esco_uri": "u:5"},  # via candidate cap
            ],
        )
        c.execute(
            insert(SkillAlias),
            [
                {"id": 1, "alias": "analýza dat", "canonical_id": 1},
                {"id": 2, "alias": "svařování", "canonical_id": 3},  # out-of-scope skill alias
            ],
        )
        c.execute(
            insert(Occupation),
            [
                {
                    "id": 1,
                    "occupation_uri": URI_KEEP,
                    "isco_code": "2511",
                    "preferred_label": "data analyst",
                    "lang": "en",
                },
                {
                    "id": 2,
                    "occupation_uri": URI_DROP,
                    "isco_code": "7212",
                    "preferred_label": "welder",
                    "lang": "en",
                },
            ],
        )
        c.execute(
            insert(SkillIndustryMap),
            [
                {
                    "id": 1,
                    "skill_id": 1,
                    "isco_code": "2511",
                    "occupation_uri": URI_KEEP,
                    "relation_type": "essential",
                },
                {
                    "id": 2,
                    "skill_id": 2,
                    "isco_code": "2511",
                    "occupation_uri": URI_KEEP,
                    "relation_type": "optional",
                },
                {
                    "id": 3,
                    "skill_id": 3,
                    "isco_code": "7212",
                    "occupation_uri": URI_DROP,
                    "relation_type": "essential",
                },
            ],
        )
        c.execute(
            insert(JobAdRow),
            [
                {
                    "id": 341,
                    "title": "Datový analytik",
                    "location": "Praha",
                    "remote_mode": "hybrid",
                    "level": "medior",
                    "domain": "data-analyst",
                    "source": "scraped",
                    "raw_text": ".",
                    "created_at": _NOW,
                },
                {
                    "id": 99,
                    "title": "Welder",
                    "location": "Brno",
                    "remote_mode": "onsite",
                    "level": "junior",
                    "domain": "welding",
                    "source": "scraped",
                    "raw_text": ".",
                    "created_at": _NOW,
                },
            ],
        )
        c.execute(
            insert(JobAdSkill), [{"id": 1, "ad_id": 341, "skill_id": 1, "requirement": "must"}]
        )
        c.execute(
            insert(Candidate),
            [{"id": 1, "cv_hash": "h", "language": "cs", "type": "student", "created_at": _NOW}],
        )
        c.execute(
            insert(TranslatedCapabilityRow),
            [
                {
                    "id": 1,
                    "candidate_id": 1,
                    "skill_canonical": "thesis",
                    "evidence_quote": "thesis EDA",
                    "confidence": 0.8,
                    "source_type": "thesis",
                    "relevance": "direct",
                    "esco_skill_id": 5,
                    "created_at": _NOW,
                }
            ],
        )


def _count(url: str, table) -> int:
    with create_engine(url, future=True).connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def _ids(url: str, table, col) -> set[int]:
    with create_engine(url, future=True).connect() as conn:
        return {r[0] for r in conn.execute(select(col))}


def test_scoped_keeps_data_role_family_plus_demo_skills(tmp_path):
    src = f"sqlite:///{tmp_path}/full.sqlite"
    out = tmp_path / "scoped.sqlite"
    _seed_full(src)

    build_scoped(src, out, ad_id=341, occ_uris=[URI_KEEP], domain="data-analyst", verbose=False)
    out_url = f"sqlite:///{out}"

    kept = _ids(out_url, Skill, Skill.id)
    # In-scope occupation skills (1,2) + hand-seed (4) + candidate cap (5); welding (3) dropped.
    assert kept == {1, 2, 4, 5}
    # Out-of-scope skill's alias is gone; in-scope alias kept.
    assert _count(out_url, SkillAlias) == 1
    # Only the kept occupation + the target ad survive.
    assert _ids(out_url, Occupation, Occupation.occupation_uri) == {URI_KEEP}
    assert _ids(out_url, JobAdRow, JobAdRow.id) == {341}
    # Candidate-side rows copied verbatim.
    assert _count(out_url, Candidate) == 1
    assert _count(out_url, TranslatedCapabilityRow) == 1
    # industry-map scoped to the kept occupation only.
    assert _count(out_url, SkillIndustryMap) == 2
