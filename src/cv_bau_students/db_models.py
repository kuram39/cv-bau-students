"""SQLAlchemy ORM models — 10 tables mirroring the Pydantic schema.

Repository functions in each domain module translate ORM rows ↔ Pydantic
objects. Pipeline code never imports from here directly; it always goes
through the repository surface.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JobAdSkill(Base):
    __tablename__ = "job_ad_skills"
    id: Mapped[int] = mapped_column(primary_key=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("job_ads.id"), index=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"), index=True)
    requirement: Mapped[str] = mapped_column(String(16))  # must_have | nice_to_have


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
