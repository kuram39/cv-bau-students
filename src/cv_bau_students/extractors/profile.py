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
    payload = llm.call_json(prompt, model=llm.mechanical_model())
    return CandidateProfile.model_validate(payload)
