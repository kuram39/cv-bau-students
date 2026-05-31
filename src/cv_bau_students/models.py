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
    # BAU-mandatory identity fields (Phase 12). LLM extracts from CV
    # header; completion loop asks if missing. Email / phone go into
    # `contact` as a free-form string (no PII validation in MVP).
    name: str | None = None
    contact: str | None = None  # email / phone, free-form
    location: str | None = None  # city / region, e.g. "Praha"
    summary: str | None = None  # elevator pitch
    target_domains: list[str] = Field(default_factory=list)
    # Phase 12: hard vs soft separated. `explicit_skills` is the legacy
    # combined list — kept for back-compat with the translator. New
    # extractor populates both lists; legacy fallback fills
    # `explicit_skills` with `hard_skills + soft_skills`.
    explicit_skills: list[str] = Field(default_factory=list)
    hard_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
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
    # ESCO normalisation: the LLM emits `esco_term` (English ESCO label) so the
    # phrase can be linked to the European skills taxonomy across languages;
    # `skill_id` is the resolved ESCO skill id (None when unresolved). Used by
    # the target-role enrichment so candidate skills share the occupation map's
    # namespace. `skill` stays as the display name.
    esco_term: str | None = None
    skill_id: int | None = None


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
    # Target-role-first scoring: resolved ISCO-08 occupation (see
    # roles/isco_resolver.py). None = unresolved → matcher skips ESCO
    # enrichment. `isco_method` ∈ {"lexical", "llm", "unresolved"}.
    isco_code: str | None = None
    isco_occupation_label: str | None = None
    isco_method: str | None = None


class SkillFitDetail(BaseModel):
    """Audit trail for the skill_fit axis — what matched, what's missing,
    and how the ESCO target-role enrichment landed. Surfaced verbatim in
    the recruiter drill-in so a score is never a bare number.
    """

    matched_must: list[str] = Field(default_factory=list)
    missing_must: list[str] = Field(default_factory=list)
    matched_nice: list[str] = Field(default_factory=list)
    # ESCO target-role enrichment (only when the ad resolved to an ISCO code).
    isco_code: str | None = None
    occupation_label: str | None = None
    role_essential_total: int = 0  # |essential ESCO skills for this ISCO|
    role_essential_evidenced: int = 0  # how many the candidate demonstrates
    role_essential_matched: list[str] = Field(default_factory=list)
    role_essential_missing: list[str] = Field(default_factory=list)  # capped sample
    bonus_applied: float = 0.0  # points the enrichment added to base skill_fit


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
    skill_fit_detail: SkillFitDetail | None = None  # how skill_fit was computed
    reasoning: str | None = None  # filled by LLM #3


class CandidateAnalysis(BaseModel):
    """Top-level orchestrator output. One per analyze_candidate() call."""

    profile: CandidateProfile
    completion_rounds: list[CompletionRound] = Field(default_factory=list)
    translated_capabilities: list[TranslatedCapability] = Field(default_factory=list)
    matches: list[MatchScore] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    processing_metadata: dict = Field(default_factory=dict)


# --- Phase 12: two-pass candidate journey result models ---------------------


class RoleSpecificQuestionPydantic(BaseModel):
    """In-memory representation of a `RoleSpecificQuestion` ORM row."""

    slot: str
    question_text: str
    extract_hint: str | None = None


class PrefilledQuestion(BaseModel):
    """A role-specific question paired with the system's pre-fill suggestion.

    Returned from `express_interest('interested')` so the UI can render
    text-areas pre-populated with text the LLM extracted from the CV.
    User accepts or edits before submitting.
    """

    slot: str
    question_text: str
    extract_hint: str | None = None
    prefilled_answer: str | None = None  # None when LLM said `missing`
    prefilled_confidence: float = 0.0  # 0.0 when nothing was extracted


class GenericResult(BaseModel):
    """Output of Stage 1 (`run_generic_pass`).

    Status determines next step in the UI flow:
      - `needs_completion` → render BAU completion form
      - `matched` → render top-N match preview cards with interest buttons
    """

    status: Literal["needs_completion", "matched", "no_matches"]
    profile: CandidateProfile
    candidate_id: int | None = None
    completion_round: CompletionRound | None = None
    matches: list[MatchScore] = Field(default_factory=list)
    matched_ads: list[JobAd] = Field(default_factory=list)
    ko_eliminated: int = 0  # how many ads were dropped by hard-filter


class InterestResult(BaseModel):
    """Output of `express_interest()`.

    Status determines next step in the UI flow:
      - `wait` → show "we'll email you" mock-text and end
      - `interested` → render role-specific pre-filled form
    """

    status: Literal["wait", "interested"]
    candidate_id: int
    ad_id: int
    prefilled_questions: list[PrefilledQuestion] = Field(default_factory=list)


class RoleSpecificResult(BaseModel):
    """Output of `submit_role_specific()`. The final confirmation card."""

    candidate_id: int
    ad_id: int
    match: MatchScore
