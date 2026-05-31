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
from cv_bau_students.db_models import AdTargetSkill, JobAdRow, JobAdSkill, Skill
from cv_bau_students.models import JobAd, LanguageRequirement
from cv_bau_students.taxonomy.repo import (
    expected_skills_for_isco,
    names_for_ids,
    resolve_skill,
)


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
            isco_code=ad.isco_code,
            isco_occupation_label=ad.isco_occupation_label,
            isco_method=ad.isco_method,
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


def set_ad_fields_and_skills(
    ad_id: int,
    *,
    employer: str | None = None,
    raw_text: str | None = None,
    must_have: list[str] | None = None,
    nice_to_have: list[str] | None = None,
    languages_required: list[LanguageRequirement] | None = None,
    isco_code: str | None = None,
    isco_occupation_label: str | None = None,
    isco_method: str | None = None,
) -> None:
    """In-place edit of a single ad — used by the seed script to turn a
    scraped row into the demo target (rename employer, enrich skills).

    Only the provided fields are touched. When `must_have` /
    `nice_to_have` are given, the ad's existing skill rows for that
    requirement are replaced wholesale.
    """
    with get_session() as session:
        row = session.get(JobAdRow, ad_id)
        if row is None:
            raise LookupError(f"ad_id {ad_id} not found")
        if employer is not None:
            row.employer = employer
        if raw_text is not None:
            row.raw_text = raw_text
        if isco_code is not None:
            row.isco_code = isco_code
        if isco_occupation_label is not None:
            row.isco_occupation_label = isco_occupation_label
        if isco_method is not None:
            row.isco_method = isco_method
        if languages_required is not None:
            row.languages_required = [
                {"language": lr.language, "min_level": lr.min_level} for lr in languages_required
            ]
        if must_have is not None:
            session.execute(
                JobAdSkill.__table__.delete().where(
                    (JobAdSkill.ad_id == ad_id) & (JobAdSkill.requirement == "must_have")
                )
            )
            _store_ad_skills(session, ad_id, must_have, requirement="must_have")
        if nice_to_have is not None:
            session.execute(
                JobAdSkill.__table__.delete().where(
                    (JobAdSkill.ad_id == ad_id) & (JobAdSkill.requirement == "nice_to_have")
                )
            )
            _store_ad_skills(session, ad_id, nice_to_have, requirement="nice_to_have")


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
        isco_code=row.isco_code,
        isco_occupation_label=row.isco_occupation_label,
        isco_method=row.isco_method,
    )


def get_target_skills(ad_id: int) -> dict[str, set[int]] | None:
    """Recruiter-curated target skills for an ad → {'core': {...}, 'optional': {...}}.

    Returns None when the recruiter hasn't curated a set (matcher then falls
    back to the full ISCO essential∪optional list).
    """
    with get_session() as session:
        rows = session.execute(
            select(AdTargetSkill.skill_id, AdTargetSkill.tier).where(AdTargetSkill.ad_id == ad_id)
        ).all()
    if not rows:
        return None
    out: dict[str, set[int]] = {"core": set(), "optional": set()}
    for skill_id, tier in rows:
        out.setdefault(tier, set()).add(skill_id)
    return out


def set_target_skills(ad_id: int, *, core: list[int], optional: list[int]) -> None:
    """Replace the curated target set for an ad. core wins on overlap."""
    core_set = set(core)
    optional_set = set(optional) - core_set
    with get_session() as session:
        session.execute(AdTargetSkill.__table__.delete().where(AdTargetSkill.ad_id == ad_id))
        for sid in core_set:
            session.add(AdTargetSkill(ad_id=ad_id, skill_id=sid, tier="core"))
        for sid in optional_set:
            session.add(AdTargetSkill(ad_id=ad_id, skill_id=sid, tier="optional"))


def suggest_target_skills(ad_id: int) -> dict[str, list[tuple[int, str]]]:
    """Default picker contents from the ad's ISCO occupation: ESCO essential →
    `core`, optional → `optional`, each as sorted (skill_id, name) pairs.

    Empty lists when the ad has no resolved ISCO code (recruiter then has
    nothing to pick from — surfaced in the UI as "resolve ISCO first").
    """
    ad = get_ad_by_id(ad_id)
    if ad is None or not ad.isco_code:
        return {"core": [], "optional": []}
    essential = expected_skills_for_isco(ad.isco_code, "essential")
    optional = expected_skills_for_isco(ad.isco_code, "optional")
    names = names_for_ids([*essential, *optional])

    def _pairs(ids: list[int]) -> list[tuple[int, str]]:
        return sorted(((i, names[i]) for i in ids if i in names), key=lambda p: p[1])

    return {"core": _pairs(essential), "optional": _pairs(optional)}


def resolve_ad_isco(ad_id: int) -> tuple[str | None, str | None, str]:
    """Run the role→ISCO resolver for one ad and persist the result.

    Resolution is kept out of `store_ad` (bulk ad loads must not trigger
    per-row LLM calls); callers that want a target-role mapping — the
    seed script, primarily — invoke this once. Returns
    (isco_code, occupation_label, method). Lexical hits cost nothing;
    edge cases fall back to a single cheap LLM call.
    """
    from cv_bau_students.roles.isco_resolver import resolve_isco_for_ad

    ad = get_ad_by_id(ad_id)
    if ad is None:
        raise LookupError(f"ad_id {ad_id} not found")
    isco_code, label, method = resolve_isco_for_ad(ad.title, ad.domain, ad.must_have)
    # Always-write path: a re-resolution that now yields "unresolved" must
    # CLEAR a previously stored code, else the matcher keeps applying ESCO
    # enrichment for the stale role. `set_ad_fields_and_skills` skips None
    # values by design, so it can't clear — use the dedicated setter.
    set_ad_isco(ad_id, isco_code=isco_code, occupation_label=label, method=method)
    return isco_code, label, method


def set_ad_isco(
    ad_id: int,
    *,
    isco_code: str | None,
    occupation_label: str | None,
    method: str | None,
) -> None:
    """Overwrite an ad's ISCO fields unconditionally (None clears them)."""
    with get_session() as session:
        row = session.get(JobAdRow, ad_id)
        if row is None:
            raise LookupError(f"ad_id {ad_id} not found")
        row.isco_code = isco_code
        row.isco_occupation_label = occupation_label
        row.isco_method = method
