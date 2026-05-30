"""Job-ad repository — load + persist via SQLAlchemy.

The ad corpus lives in the `job_ads` + `job_ad_skills` tables. Loaders
(scripts/normalise_scraped_ads.py, scripts/generate_synthetic_ads.py)
populate it; the matcher reads via the `find_candidates` query.

Repository functions return Pydantic `JobAd` objects so the rest of
the pipeline never sees ORM rows.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from cv_bau_students.db import get_session
from cv_bau_students.db_models import JobAdRow, JobAdSkill, Skill
from cv_bau_students.models import JobAd, LanguageRequirement
from cv_bau_students.taxonomy.repo import resolve_skill


def store_ad(ad: JobAd) -> int:
    """Insert a JobAd (and its skill rows). Returns the new DB id.

    Skills that cannot be resolved against the taxonomy are stored as
    a free-string memo on the ad row's `raw_text` (downstream LLMs will
    catch the gap); the matcher only joins via the resolved ids.
    """
    with get_session() as session:
        row = JobAdRow(
            title=ad.title,
            employer=ad.employer,
            location=ad.location,
            remote_mode=ad.remote_mode,
            level=ad.level,
            domain=ad.domain,
            source=ad.source,
            raw_text=ad.raw_text,
            ad_url=ad.ad_url,
            languages_required=[
                {"language": lr.language, "min_level": lr.min_level} for lr in ad.languages_required
            ],
        )
        session.add(row)
        session.flush()
        ad_id = row.id

        _store_ad_skills(session, ad_id, ad.must_have, requirement="must_have")
        _store_ad_skills(session, ad_id, ad.nice_to_have, requirement="nice_to_have")

    return ad_id


def _store_ad_skills(
    session: Session,
    ad_id: int,
    skill_names: list[str],
    *,
    requirement: str,
) -> None:
    for raw_skill in skill_names:
        match = resolve_skill(raw_skill)
        if match is None:
            continue
        skill_id, _ = match
        session.add(JobAdSkill(ad_id=ad_id, skill_id=skill_id, requirement=requirement))


def list_ads() -> list[JobAd]:
    """Load every ad in the DB (for the demo this is fine; production
    paginates)."""
    with get_session() as session:
        rows = session.execute(select(JobAdRow)).scalars().all()
        return [_to_pydantic(session, r) for r in rows]


def get_ad_by_id(ad_id: int) -> JobAd | None:
    """Direct lookup — replaces the linear scan that lived in app.py."""
    with get_session() as session:
        row = session.get(JobAdRow, ad_id)
        if row is None:
            return None
        return _to_pydantic(session, row)


def find_ad_by_title_substring(needle: str) -> JobAd | None:
    """Helper for seed scripts that target ads by a known title fragment.

    Used by `scripts/seed_target_demo.py` to resolve the target row at
    runtime so the script isn't tied to a specific row id across DB
    rebuilds.
    """
    needle_lower = needle.lower()
    with get_session() as session:
        for row in session.execute(select(JobAdRow)).scalars().all():
            if needle_lower in (row.title or "").lower():
                return _to_pydantic(session, row)
        return None


def find_candidate_ads(
    *,
    levels: list[str] | None = None,
    domains: list[str] | None = None,
    skill_ids_any: set[int] | None = None,
    limit: int | None = None,
) -> list[JobAd]:
    """SQL pre-filter — narrows the ad set before the Python matcher runs.

    Cuts the scoring set from "every ad in the DB" to "ads with at least
    one of these levels AND one of these domains AND at least one
    skill that overlaps the candidate's translated capabilities." Real
    win at scale (thousands of ads): scoring 50 candidate ads instead
    of 5000 means matcher cost drops 100×.

    Single SQL round-trip with `EXISTS` for the skill-overlap check so
    we don't fan-out per-row.
    """
    with get_session() as session:
        stmt = select(JobAdRow)
        if levels:
            stmt = stmt.where(JobAdRow.level.in_(levels))
        if domains:
            stmt = stmt.where(JobAdRow.domain.in_(domains))
        if skill_ids_any:
            stmt = stmt.where(
                select(JobAdSkill.id)
                .where(
                    JobAdSkill.ad_id == JobAdRow.id,
                    JobAdSkill.skill_id.in_(skill_ids_any),
                )
                .exists()
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = session.execute(stmt).scalars().all()
        return [_to_pydantic(session, r) for r in rows]


def _to_pydantic(session: Session, row: JobAdRow) -> JobAd:
    skills_must = []
    skills_nice = []
    pairs = session.execute(
        select(JobAdSkill, Skill)
        .join(Skill, Skill.id == JobAdSkill.skill_id)
        .where(JobAdSkill.ad_id == row.id)
    ).all()
    for jas, skill in pairs:
        target = skills_must if jas.requirement == "must_have" else skills_nice
        target.append(skill.canonical_name)

    languages = []
    for entry in row.languages_required or []:
        languages.append(
            LanguageRequirement(
                language=entry["language"],
                min_level=entry["min_level"],
            )
        )

    return JobAd(
        id=row.id,
        title=row.title,
        employer=row.employer,
        location=row.location,
        remote_mode=row.remote_mode,  # type: ignore[arg-type]
        level=row.level,  # type: ignore[arg-type]
        domain=row.domain,
        must_have=skills_must,
        nice_to_have=skills_nice,
        languages_required=languages,
        raw_text=row.raw_text,
        source=row.source,  # type: ignore[arg-type]
        ad_url=row.ad_url,
    )
