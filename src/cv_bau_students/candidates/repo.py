"""Candidate persistence + recruiter-facing queries (Phase 12b).

Single source of truth for writing analyses to and reading them out of
the DB. Both the live UI (candidate upload + recruiter dashboard) and
the seed script call this module.

Identity dedup: a `Candidate` row is keyed by `cv_hash`. Same CV
uploaded twice updates the existing candidate rather than spawning a
duplicate, so the recruiter list stays clean during the demo.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from cv_bau_students.db import get_session
from cv_bau_students.db_models import (
    Candidate,
    CandidateInterest,
    Match,
    ProfileVersion,
    RoleSpecificAnswer,
    RoleSpecificQuestion,
    TranslatedCapabilityRow,
)
from cv_bau_students.models import (
    CandidateProfile,
    GapItem,
    MatchScore,
    SkillFitDetail,
    TranslatedCapability,
)

# Cap stored CV text so a pathological upload can't bloat a row.
_RAW_CV_MAX_CHARS = 20_000

# --- Recruiter-facing view models ------------------------------------------


class CandidateSummary(BaseModel):
    """One row in the recruiter ranked list."""

    candidate_id: int
    kind: str  # 'student' | 'career_changer' | 'experienced'
    display_name: str  # "Anonymous #N" or candidate.profile.name
    total: float
    confidence_band: float
    top_skills: list[str] = Field(default_factory=list)
    headline: str  # first sentence of Match.reasoning


class RoleAnswerView(BaseModel):
    """One Q + answer pair in the drill-in panel."""

    slot: str
    question_text: str
    answer_text: str
    was_prefilled: bool
    was_edited: bool


class CandidateDetail(BaseModel):
    """Full payload for the drill-in expander."""

    candidate_id: int
    kind: str
    profile: CandidateProfile
    capabilities: list[TranslatedCapability] = Field(default_factory=list)
    match: MatchScore
    role_answers: list[RoleAnswerView] = Field(default_factory=list)
    raw_cv_text: str | None = None  # original extracted CV text, for audit


# --- Helpers ---------------------------------------------------------------


def cv_hash(file_bytes: bytes) -> str:
    """Stable identity key for a CV; dedup at the Candidate row level."""
    return hashlib.sha256(file_bytes).hexdigest()


def _display_name_for(profile: CandidateProfile, candidate_id: int) -> str:
    if profile.name and profile.name.strip():
        return profile.name.strip()
    return f"Kandidát #{candidate_id}"


# --- Persistence ------------------------------------------------------------


def store_initial_candidate(
    *,
    file_hash: str,
    profile: CandidateProfile,
    capabilities: Iterable[TranslatedCapability],
    raw_cv_text: str | None = None,
) -> int:
    """Upsert a Candidate row + replace ProfileVersion + TranslatedCapability.

    `raw_cv_text` is the original extracted CV text (truncated), persisted
    so the recruiter can audit the source behind a score. Returns the
    `Candidate.id` (existing on dedup, new otherwise).
    """
    capabilities = list(capabilities)
    cv_text = raw_cv_text[:_RAW_CV_MAX_CHARS] if raw_cv_text else None
    with get_session() as session:
        existing = session.execute(
            select(Candidate).where(Candidate.cv_hash == file_hash)
        ).scalar_one_or_none()
        if existing is None:
            cand = Candidate(
                cv_hash=file_hash,
                language=profile.language,
                type=profile.candidate_type,
                raw_cv_text=cv_text,
            )
            session.add(cand)
            session.flush()
            candidate_id = cand.id
        else:
            existing.language = profile.language
            existing.type = profile.candidate_type
            if cv_text is not None:
                existing.raw_cv_text = cv_text
            candidate_id = existing.id

        # ProfileVersion: append a new row with round=N so re-uploads keep history.
        existing_versions = (
            session.execute(
                select(ProfileVersion).where(ProfileVersion.candidate_id == candidate_id)
            )
            .scalars()
            .all()
        )
        next_round = max((v.round for v in existing_versions), default=-1) + 1
        session.add(
            ProfileVersion(
                candidate_id=candidate_id,
                round=next_round,
                profile_json=profile.model_dump(),
            )
        )

        # TranslatedCapabilities: drop + reinsert (re-extracts can shift).
        session.execute(
            TranslatedCapabilityRow.__table__.delete().where(
                TranslatedCapabilityRow.candidate_id == candidate_id
            )
        )
        for cap in capabilities:
            session.add(
                TranslatedCapabilityRow(
                    candidate_id=candidate_id,
                    skill_canonical=cap.skill,
                    evidence_quote=cap.evidence_quote,
                    confidence=cap.confidence,
                    caveat=cap.caveat,
                    source_type=cap.source_type,
                    relevance=getattr(cap, "relevance", "direct"),
                    esco_term=cap.esco_term,
                    esco_skill_id=cap.skill_id,
                )
            )

    return candidate_id


def record_interest(candidate_id: int, ad_id: int, status: str) -> None:
    """Insert or update a CandidateInterest row (one per candidate × ad)."""
    if status not in ("interested", "wait"):
        raise ValueError(f"invalid interest status: {status!r}")
    with get_session() as session:
        session.execute(
            sqlite_insert(CandidateInterest)
            .values(candidate_id=candidate_id, ad_id=ad_id, status=status)
            .on_conflict_do_update(
                index_elements=["candidate_id", "ad_id"],
                set_={"status": status},
            )
        )


def ensure_role_questions(
    ad_id: int,
    *,
    questions_factory,
) -> list[RoleSpecificQuestion]:
    """Read-or-generate-once: load existing Qs for this ad, else generate.

    `questions_factory` is a callable returning
    `list[RoleSpecificQuestionPydantic]` (an LLM-backed generator in
    production; a stub in tests).
    """
    with get_session() as session:
        existing = (
            session.execute(select(RoleSpecificQuestion).where(RoleSpecificQuestion.ad_id == ad_id))
            .scalars()
            .all()
        )
        if existing:
            return list(existing)

    # Generate fresh outside the transaction so the LLM call doesn't hold a
    # connection during latency.
    generated = questions_factory()
    with get_session() as session:
        for q in generated:
            session.add(
                RoleSpecificQuestion(
                    ad_id=ad_id,
                    slot=q.slot,
                    question_text=q.question_text,
                    extract_hint=q.extract_hint,
                )
            )
        session.flush()
        rows = (
            session.execute(select(RoleSpecificQuestion).where(RoleSpecificQuestion.ad_id == ad_id))
            .scalars()
            .all()
        )
    return list(rows)


def store_role_answers(
    candidate_id: int,
    ad_id: int,
    *,
    answers: dict[str, str],
    prefilled_set: set[str],
    edited_set: set[str],
) -> None:
    """Replace the candidate's role answers for this ad.

    Replace-semantics (delete-then-insert), NOT upsert: each submit carries
    the full answer set, so a slot omitted this time must disappear. An upsert
    left stale rows behind — e.g. a blank submit (`answers={}`) would keep a
    previous run's AI-drafted answers visible in the recruiter drill-in.
    """
    with get_session() as session:
        session.execute(
            RoleSpecificAnswer.__table__.delete().where(
                (RoleSpecificAnswer.candidate_id == candidate_id)
                & (RoleSpecificAnswer.ad_id == ad_id)
            )
        )
        for slot, text in answers.items():
            if not text:
                continue
            session.add(
                RoleSpecificAnswer(
                    candidate_id=candidate_id,
                    ad_id=ad_id,
                    slot=slot,
                    answer_text=text,
                    was_prefilled=(slot in prefilled_set),
                    was_edited=(slot in edited_set),
                )
            )


def store_match(
    candidate_id: int,
    ad_id: int,
    *,
    match: MatchScore,
) -> None:
    """Upsert a Match row keyed by (candidate_id, ad_id)."""
    with get_session() as session:
        existing = session.execute(
            select(Match).where(Match.candidate_id == candidate_id, Match.ad_id == ad_id)
        ).scalar_one_or_none()
        detail_json = match.skill_fit_detail.model_dump() if match.skill_fit_detail else None
        if existing is None:
            session.add(
                Match(
                    candidate_id=candidate_id,
                    ad_id=ad_id,
                    skill_fit=match.skill_fit,
                    bridge_fit=match.bridge_fit,
                    personal_fit=match.personal_fit,
                    total=match.total,
                    confidence_band=match.confidence_band,
                    bridge_plan_json=[g.model_dump() for g in match.bridge_plan],
                    skill_fit_detail_json=detail_json,
                )
            )
        else:
            existing.skill_fit = match.skill_fit
            existing.bridge_fit = match.bridge_fit
            existing.personal_fit = match.personal_fit
            existing.total = match.total
            existing.confidence_band = match.confidence_band
            existing.bridge_plan_json = [g.model_dump() for g in match.bridge_plan]
            existing.skill_fit_detail_json = detail_json


def rescore_ad(ad_id: int) -> int:
    """Re-run the deterministic matcher for every candidate with a Match on
    this ad and upsert the new scores. NO LLM — `score_match` is pure Python,
    so the recruiter's target-skill edit is reflected instantly and for free.

    The LLM reasoning text is NOT touched (`store_match` never writes it); a
    stale verdict stays until the candidate re-submits. Returns the count
    re-scored.
    """
    from cv_bau_students.jobads.repo import get_ad_by_id
    from cv_bau_students.matcher.score import score_match

    ad = get_ad_by_id(ad_id)
    if ad is None:
        return 0
    with get_session() as session:
        cand_ids = list(
            session.execute(select(Match.candidate_id).where(Match.ad_id == ad_id)).scalars().all()
        )
    n = 0
    for cid in cand_ids:
        detail = get_candidate_detail(cid, ad_id)
        if detail is None:
            continue
        match = score_match(detail.profile, detail.capabilities or [], ad)
        store_match(cid, ad_id, match=match)
        n += 1
    return n


# --- Recruiter-facing read paths --------------------------------------------


def get_candidates_for_ad(
    ad_id: int,
    *,
    kind: str | None = None,
) -> list[CandidateSummary]:
    """Ordered ranked list of interested candidates for one ad.

    Only candidates whose `CandidateInterest.status='interested'` AND
    who have a corresponding `Match` row show up. Sorted by Match.total
    descending.
    """
    with get_session() as session:
        # Join: Candidate × Match × CandidateInterest filtered by ad.
        stmt = (
            select(Candidate, Match)
            .join(Match, Match.candidate_id == Candidate.id)
            .join(
                CandidateInterest,
                (CandidateInterest.candidate_id == Candidate.id)
                & (CandidateInterest.ad_id == Match.ad_id),
            )
            .where(Match.ad_id == ad_id)
            .where(CandidateInterest.status == "interested")
            .order_by(Match.total.desc())
        )
        if kind is not None:
            stmt = stmt.where(Candidate.type == kind)

        results: list[CandidateSummary] = []
        for cand, m in session.execute(stmt).all():
            profile = _load_latest_profile(session, cand.id)
            caps = (
                session.execute(
                    select(TranslatedCapabilityRow)
                    .where(TranslatedCapabilityRow.candidate_id == cand.id)
                    .order_by(TranslatedCapabilityRow.confidence.desc())
                    .limit(3)
                )
                .scalars()
                .all()
            )
            top_skills = [c.skill_canonical for c in caps]
            results.append(
                CandidateSummary(
                    candidate_id=cand.id,
                    kind=cand.type,
                    display_name=_display_name_for(profile, cand.id),
                    total=m.total,
                    confidence_band=m.confidence_band,
                    top_skills=top_skills,
                    headline=_reasoning_headline(_load_match_reasoning(session, cand.id, ad_id)),
                )
            )
        return results


def get_candidate_detail(candidate_id: int, ad_id: int) -> CandidateDetail | None:
    """Full drill-in payload for one candidate × ad pair."""
    with get_session() as session:
        cand = session.get(Candidate, candidate_id)
        if cand is None:
            return None
        m = session.execute(
            select(Match).where(Match.candidate_id == candidate_id, Match.ad_id == ad_id)
        ).scalar_one_or_none()
        if m is None:
            return None
        profile = _load_latest_profile(session, candidate_id)
        cap_rows = (
            session.execute(
                select(TranslatedCapabilityRow).where(
                    TranslatedCapabilityRow.candidate_id == candidate_id
                )
            )
            .scalars()
            .all()
        )
        capabilities = [
            TranslatedCapability(
                skill=c.skill_canonical,
                evidence_quote=c.evidence_quote,
                confidence=c.confidence,
                caveat=c.caveat,
                source_type=c.source_type,
                relevance=c.relevance,
                esco_term=c.esco_term,
                skill_id=c.esco_skill_id,
            )
            for c in cap_rows
        ]

        # Join RoleSpecificQuestion ↔ RoleSpecificAnswer for this candidate/ad.
        qa_rows = session.execute(
            select(RoleSpecificQuestion, RoleSpecificAnswer)
            .join(
                RoleSpecificAnswer,
                (RoleSpecificAnswer.slot == RoleSpecificQuestion.slot)
                & (RoleSpecificAnswer.ad_id == RoleSpecificQuestion.ad_id),
            )
            .where(RoleSpecificQuestion.ad_id == ad_id)
            .where(RoleSpecificAnswer.candidate_id == candidate_id)
        ).all()
        role_answers = [
            RoleAnswerView(
                slot=q.slot,
                question_text=q.question_text,
                answer_text=a.answer_text,
                was_prefilled=a.was_prefilled,
                was_edited=a.was_edited,
            )
            for q, a in qa_rows
        ]

        match = MatchScore(
            ad_id=m.ad_id,
            skill_fit=m.skill_fit,
            bridge_fit=m.bridge_fit,
            personal_fit=m.personal_fit,
            total=m.total,
            confidence_band=m.confidence_band,
            bridge_plan=[GapItem(**g) for g in (m.bridge_plan_json or [])],
            skill_fit_detail=(
                SkillFitDetail(**m.skill_fit_detail_json) if m.skill_fit_detail_json else None
            ),
            reasoning=_load_match_reasoning(session, candidate_id, ad_id),
        )

        return CandidateDetail(
            candidate_id=cand.id,
            kind=cand.type,
            profile=profile,
            capabilities=capabilities,
            match=match,
            role_answers=role_answers,
            raw_cv_text=cand.raw_cv_text,
        )


def stats_for_ad(ad_id: int) -> dict[str, int | float]:
    """Quick summary row for the recruiter panel header."""
    summaries = get_candidates_for_ad(ad_id)
    students = [s for s in summaries if s.kind == "student"]
    experienced = [s for s in summaries if s.kind == "experienced"]
    return {
        "total": len(summaries),
        "students": len(students),
        "experienced": len(experienced),
        "avg_student_total": (
            round(sum(s.total for s in students) / len(students), 1) if students else 0.0
        ),
        "avg_experienced_total": (
            round(sum(s.total for s in experienced) / len(experienced), 1) if experienced else 0.0
        ),
    }


# --- Internal helpers -------------------------------------------------------


def _load_latest_profile(session, candidate_id: int) -> CandidateProfile:
    row = session.execute(
        select(ProfileVersion)
        .where(ProfileVersion.candidate_id == candidate_id)
        .order_by(ProfileVersion.round.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"no profile_versions for candidate_id={candidate_id}")
    return CandidateProfile.model_validate(row.profile_json)


def _load_match_reasoning(session, candidate_id: int, ad_id: int) -> str | None:
    """reasoning_cache may hold MULTIPLE rows per (candidate, ad) — the key
    includes prompt_hash, so each re-run with a different prompt adds one.
    Take the most recent; scalar_one_or_none() would raise MultipleResultsFound."""
    from cv_bau_students.db_models import ReasoningCache

    row = (
        session.execute(
            select(ReasoningCache)
            .where(
                ReasoningCache.candidate_id == candidate_id,
                ReasoningCache.ad_id == ad_id,
            )
            .order_by(ReasoningCache.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return row.rationale if row else None


def _first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    for sep in (". ", "! ", "? "):
        if sep in text:
            return text.split(sep, 1)[0].strip() + sep.strip()
    return text.strip()


def _reasoning_headline(raw: str | None) -> str:
    """One-line recruiter headline = first sentence of the parsed verdict
    (never the raw JSON string, even when the stored rationale is truncated)."""
    from cv_bau_students.explanation.format import parse_reasoning

    verdict = parse_reasoning(raw)["verdict"]
    return _first_sentence(verdict) or "(zatím bez zdůvodnění)"
