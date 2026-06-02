"""LLM #1 — extract a structured CandidateProfile from raw CV text.

Single LLM pass against `prompts/extract_profile.md`. Output validated
against the `CandidateProfile` Pydantic model; malformed JSON or a
profile missing a required field surfaces as an explicit error rather
than silently degrading downstream scoring.

The prompt also tags `candidate_type` (student / career_changer /
experienced) inline so the pipeline can branch without a second LLM
call. `detector.classify()` re-applies the same heuristics in Python
to keep the audit trail visible.
"""

from datetime import date

from cv_bau_students import llm
from cv_bau_students.models import CandidateProfile


def extract_profile(cv_text: str, *, today: date | None = None) -> CandidateProfile:
    """Run the profile extractor LLM and return a validated CandidateProfile.

    `today` is injected for testability; production code defaults to
    `date.today()` so the prompt's "current year" anchor stays in sync
    with reality (used by the `most_recent_grad_year >= currentYear - 1`
    fresh-graduate rule).
    """
    current_year = (today or date.today()).year
    prompt = llm.render_prompt(
        "extract_profile",
        cv_text=cv_text,
        current_year=current_year,
    )
    # Prompt caching: extract_profile.md is static-first (instructions/schema/
    # examples) with the variable CV text in the trailing "## CV TEXT" section.
    # Split there so the big static body is the cacheable prefix and only the CV
    # varies per call. No-op unless CV_BAU_STUDENTS_CACHE=1.
    static, marker, variable = prompt.partition("## CV TEXT")
    cache_prefix = static if marker else None
    suffix = (marker + variable) if marker else prompt
    payload = llm.call_json(
        suffix,
        model=llm.mechanical_model(),
        schema=CandidateProfile.model_json_schema(),
        cache_prefix=cache_prefix,
    )
    return CandidateProfile.model_validate(payload)
