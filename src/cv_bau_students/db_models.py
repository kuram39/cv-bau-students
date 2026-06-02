"""SQLAlchemy ORM models — 10 tables mirroring the Pydantic schema.

Repository functions in each domain module translate ORM rows ↔ Pydantic
objects. Pipeline code never imports from here directly; it always goes
through the repository surface.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- Candidates -------------------------------------------------------------


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    cv_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    language: Mapped[str] = mapped_column(String(2), default="en")
    type: Mapped[str] = mapped_column(String(32))  # student / career_changer / experienced
    # Original extracted CV text, so the recruiter can audit the source
    # behind every score. Truncated by the writer to bound row size.
    raw_cv_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    profile_versions: Mapped[list["ProfileVersion"]] = relationship(back_populates="candidate")


class ProfileVersion(Base):
    __tablename__ = "profile_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)  # 0 = initial, 1+ = post-completion
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    candidate: Mapped[Candidate] = relationship(back_populates="profile_versions")


class CompletionQuestionRow(Base):
    __tablename__ = "completion_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(128))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 12a: distinguish BAU-mandatory completion loop (default) from
    # other future kinds. Role-specific Q&A lives in its own pair of tables
    # below — not in CompletionQuestionRow.
    kind: Mapped[str] = mapped_column(String(16), default="bau_mandatory")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TranslatedCapabilityRow(Base):
    __tablename__ = "translated_capabilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    skill_canonical: Mapped[str] = mapped_column(String(255), index=True)
    evidence_quote: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    caveat: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))
    relevance: Mapped[str] = mapped_column(String(16))
    # ESCO normalisation (see models.TranslatedCapability): English label the
    # LLM mapped this capability to, and the resolved ESCO skill id. The id
    # lets the matcher compare candidate skills against an occupation's ESCO
    # skill set in one namespace. None when unresolved.
    esco_term: Mapped[str | None] = mapped_column(String(255), nullable=True)
    esco_skill_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# --- Skill taxonomy --------------------------------------------------------


class Skill(Base):
    __tablename__ = "skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    family: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ESCO enrichment (Phase 11)
    canonical_name_en: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    esco_uri: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    skill_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Czech NSP code (CZ-ISCO + competence linkage)
    nsp_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class SkillAlias(Base):
    __tablename__ = "skill_aliases"
    # Composite PK: same alias can exist in multiple langs / sources
    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(255), index=True)
    canonical_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)
    lang: Mapped[str] = mapped_column(String(8), default="en", index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")

    __table_args__ = (UniqueConstraint("alias", "lang", "source", name="uq_alias_lang_source"),)


class SkillHierarchy(Base):
    __tablename__ = "skill_hierarchy"
    parent_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), primary_key=True)


# --- Occupation → skill mapping (ESCO Phase 11c) ---------------------------


class SkillIndustryMap(Base):
    """Which skills are essential / optional for which ISCO occupations.

    Populated from ESCO's `occupationSkillRelations.csv` joined with
    `occupations.csv` to surface ISCO-08 4-digit codes. The matcher
    uses this for target-role-first scoring: pick an ISCO code, get
    the expected skill set, intersect with the candidate's translated
    capabilities, compute coverage + bridge gap.
    """

    __tablename__ = "skill_industry_map"
    id: Mapped[int] = mapped_column(primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)
    isco_code: Mapped[str] = mapped_column(String(8), index=True)
    occupation_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relation_type: Mapped[str] = mapped_column(String(16))  # 'essential' or 'optional'

    __table_args__ = (
        UniqueConstraint("skill_id", "isco_code", "relation_type", name="uq_skill_industry"),
    )


class Occupation(Base):
    """ESCO occupation labels keyed by ISCO-08 group — drives the
    role→ISCO resolver.

    Loaded from ESCO `occupations_{en,cs}.csv`. `data/raw_esco/` is
    gitignored (absent on Streamlit Cloud), so the labels must ride in
    `seed.sqlite.gz` — hence a DB table rather than a runtime CSV read.
    The resolver lexically matches an ad's title/domain against
    `preferred_label` + `alt_labels` (both languages) to land on the
    right `isco_code`, then `SkillIndustryMap` supplies the expected
    skill set for that code.
    """

    __tablename__ = "occupations"
    id: Mapped[int] = mapped_column(primary_key=True)
    occupation_uri: Mapped[str] = mapped_column(String(255), index=True)
    isco_code: Mapped[str] = mapped_column(String(8), index=True)
    preferred_label: Mapped[str] = mapped_column(String(255), index=True)
    alt_labels: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    lang: Mapped[str] = mapped_column(String(8), default="en", index=True)

    __table_args__ = (UniqueConstraint("occupation_uri", "lang", name="uq_occupation_lang"),)


# --- Role-specific Q&A + interest expression (Phase 12a) -------------------


class RoleSpecificQuestion(Base):
    """One row per fixed personalised question per job ad.

    Generated ONCE per ad (LLM call) and replayed identically for every
    candidate who expresses interest in that ad — guarantees fairness
    + consistency across applicants. `slot` is a stable string key
    (e.g. "elevator_pitch_for_role", "bi_tool_experience") used to
    join with `RoleSpecificAnswer` rows across candidates.
    """

    __tablename__ = "role_specific_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("job_ads.id"), index=True)
    slot: Mapped[str] = mapped_column(String(64))
    question_text: Mapped[str] = mapped_column(Text)
    extract_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("ad_id", "slot", name="uq_role_question"),)


class CandidateInterest(Base):
    """Candidate's choice when offered a match: 'interested' or 'wait'."""

    __tablename__ = "candidate_interests"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("job_ads.id"), index=True)
    status: Mapped[str] = mapped_column(String(16))  # 'interested' | 'wait'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("candidate_id", "ad_id", name="uq_candidate_interest"),)


class RoleSpecificAnswer(Base):
    """Candidate's answer to one role-specific question for one ad.

    `was_prefilled` = the system suggested an answer extracted from CV.
    `was_edited` = the user changed the suggestion before submitting.
    Both flags surface in the recruiter drill-in so they see how much
    deliberate effort each candidate put in.
    """

    __tablename__ = "role_specific_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("job_ads.id"), index=True)
    slot: Mapped[str] = mapped_column(String(64))
    answer_text: Mapped[str] = mapped_column(Text)
    was_prefilled: Mapped[bool] = mapped_column(default=False)
    was_edited: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("candidate_id", "ad_id", "slot", name="uq_role_specific_answer"),
    )


# --- Level checklists (junior / medior / senior per domain) -----------------


class LevelChecklist(Base):
    __tablename__ = "level_checklists"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)
    bridgeable_in_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("domain", "level", "skill_id", name="uq_level_checklist"),)


# --- Job ads ---------------------------------------------------------------


class JobAdRow(Base):
    __tablename__ = "job_ads"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    employer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str] = mapped_column(String(128))
    remote_mode: Mapped[str] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(16), index=True)
    domain: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16))
    raw_text: Mapped[str] = mapped_column(Text)
    ad_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    languages_required: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Target-role-first scoring: ISCO occupation this ad maps to, resolved
    # once (lexical or LLM fallback). Feeds expected_skills_for_isco() in
    # the matcher. None = unresolved → enrichment silently skipped.
    isco_code: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    isco_occupation_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # isco_method ∈ {lexical, llm, unresolved}
    isco_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JobAdSkill(Base):
    __tablename__ = "job_ad_skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("job_ads.id"), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)
    requirement: Mapped[str] = mapped_column(String(16))  # must_have | nice_to_have


class AdTargetSkill(Base):
    """Recruiter-curated target skill set for an ad (Phase B skill-picker).

    The recruiter picks, from the ad's ISCO occupation skills (ESCO), a small
    explicit target set tagged `core` or `optional`. When present, the matcher
    scores role coverage against THIS curated set instead of the full ~500
    essential∪optional ESCO list — so coverage is interpretable (e.g. 4/10
    core) and reflects what the recruiter actually wants, not auto-inference.
    """

    __tablename__ = "ad_target_skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("job_ads.id"), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)
    tier: Mapped[str] = mapped_column(String(16))  # 'core' | 'optional'

    __table_args__ = (UniqueConstraint("ad_id", "skill_id", name="uq_ad_target_skill"),)


# --- Matches + reasoning cache ---------------------------------------------


class Match(Base):
    __tablename__ = "matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("job_ads.id"), index=True)
    skill_fit: Mapped[float] = mapped_column(Float)
    bridge_fit: Mapped[float] = mapped_column(Float)
    personal_fit: Mapped[float] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)
    confidence_band: Mapped[float] = mapped_column(Float)
    bridge_plan_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Audit trail for skill_fit: matched/missing must+nice, the ISCO role
    # match, and which role-essential ESCO skills the candidate evidenced.
    # Mirrors models.SkillFitDetail. None for legacy/no-isco matches.
    skill_fit_detail_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Human oversight (EU AI Act Art. 14 / GDPR Art. 22 meaningful-involvement):
    # the recruiter can override / contest a score. Nullable → auto-ALTERed onto
    # existing DBs by db._auto_add_missing_columns; never touched by rescore_ad.
    recruiter_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    override_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReasoningCache(Base):
    __tablename__ = "reasoning_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("job_ads.id"), index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    rationale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("candidate_id", "ad_id", "prompt_hash", name="uq_reasoning"),
    )
