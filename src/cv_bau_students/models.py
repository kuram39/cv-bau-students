"""Pydantic schemas — single source of truth for the pipeline contract.

The DB layer (`db_models.py`) mirrors these shapes; repository functions
translate between ORM rows and Pydantic objects so the pipeline itself
never sees SQLAlchemy.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CandidateType = Literal["student", "career_changer", "experienced"]
SourceType = Literal[
    "thesis",
    "school_project",
    "internship",
    "brigada",
    "hobby",
    "open_source",
    "certification",
    "course",
    "language",
    "other",
]
Requirement = Literal["must_have", "nice_to_have"]
RemoteMode = Literal["onsite", "hybrid", "remote"]
Level = Literal["junior", "medior", "senior", "lead"]


class LanguageRequirement(BaseModel):
    language: str
    min_level: str  # "A2" | "B1" | "B2" | "C1" | "C2"


class EducationItem(BaseModel):
    institution: str
    field_of_study: str
    degree: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    in_progress: bool = False
    gpa: float | None = None
    awards: list[str] = Field(default_factory=list)
    thesis_title: str | None = None
    thesis_summary: str | None = None  # Filled by completion loop when missing


class WorkExperienceItem(BaseModel):
    employer: str
    role: str
    start_date: str | None = None  # ISO YYYY-MM
    end_date: str | None = None
    domain: str | None = None
    is_brigada: bool = False
    description: str | None = None


class SchoolProjectItem(BaseModel):
    title: str
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    team_size: int | None = None


class CandidateProfile(BaseModel):
    """Profile extracted from a CV, post-completion-loop.

    Type-tagged so the pipeline branches on `candidate_type`. Fields
    that the LLM can't fill stay as None / empty list — surfaced to the
    recruiter as "missing data" rather than silently fabricated.
    """

    candidate_type: CandidateType
    language: Literal["cs", "en"] = "en"
    summary: str | None = None  # elevator pitch
    target_domains: list[str] = Field(default_factory=list)
    explicit_skills: list[str] = Field(default_factory=list)
    languages: list[LanguageRequirement] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    work_experience: list[WorkExperienceItem] = Field(default_factory=list)
    school_projects: list[SchoolProjectItem] = Field(default_factory=list)
    open_source: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    hobbies: list[str] = Field(default_factory=list)
    # Detector audit
    total_work_years: float = 0.0
    most_recent_grad_year: int | None = None
    studying_in_progress: bool = False


class TranslatedCapability(BaseModel):
    """One inferred capability with verbatim CV evidence + skepticism caveat.

    Carried over directly from cv-estimator's SkillEvidence pattern — the
    schema discipline that lets recruiters audit any single inference.
    """

    skill: str  # canonical skill name (taxonomy-aligned when possible)
    evidence_quote: str  # verbatim substring from CV (≤200 chars)
    confidence: float = Field(ge=0.0, le=1.0)
    caveat: str | None = None  # short hedge in CV language
    source_type: SourceType
    relevance: Requirement = "nice_to_have"


class CompletionQuestion(BaseModel):
    """A targeted clarifying question generated when the profile is sparse."""

    field: str  # which profile field this targets
    question: str
    why_it_matters: str | None = None


class CompletionRound(BaseModel):
    round_no: int  # 1 or 2
    questions: list[CompletionQuestion]
    answers: dict[str, str] = Field(default_factory=dict)
    answered_at: datetime | None = None


class GapItem(BaseModel):
    """One skill the candidate lacks for the target ad's level."""

    skill: str
    bridgeable_in_months: int | None = None
    notes: str | None = None


class JobAd(BaseModel):
    """Job ad normalised from a scraped source or synthetic generation.

    Identity is `id` from the DB; `ad_url` is the public link when known.
    """

    id: int | None = None
    title: str
    employer: str | None = None
    location: str
    remote_mode: RemoteMode
    level: Level
    domain: str
    must_have: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    languages_required: list[LanguageRequirement] = Field(default_factory=list)
    raw_text: str
    source: Literal["scraped", "synthetic"]
    ad_url: str | None = None


class MatchScore(BaseModel):
    ad_id: int
    skill_fit: float = Field(ge=0.0, le=100.0)
    # -1.0 = no rubric for this (domain, level); UI maps to "N/A".
    # Real fix per Phase 11+ is to extend the level checklist to cover
    # every domain in the corpus.
    bridge_fit: float = Field(ge=-1.0, le=100.0)
    personal_fit: float = Field(ge=0.0, le=100.0)
    total: float = Field(ge=0.0, le=100.0)
    confidence_band: float  # ± points around total
    bridge_plan: list[GapItem] = Field(default_factory=list)
    reasoning: str | None = None  # filled by LLM #3


class CandidateAnalysis(BaseModel):
    """Top-level orchestrator output. One per analyze_candidate() call."""

    profile: CandidateProfile
    completion_rounds: list[CompletionRound] = Field(default_factory=list)
    translated_capabilities: list[TranslatedCapability] = Field(default_factory=list)
    matches: list[MatchScore] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    processing_metadata: dict = Field(default_factory=dict)
