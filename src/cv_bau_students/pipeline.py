"""Thin orchestrator — student / changer matching pipeline.

Per the design doc: this file is a table of contents, NOT a place for
logic. Each step is a single call into a domain module.

Two public surfaces:
  - `analyze_candidate()` — legacy one-shot (extract → match → reason).
    Kept for back-compat with the original single-page UI + tests.
  - The Phase 12 two-pass journey:
      run_generic_pass → express_interest → submit_role_specific
    plus `ensure_role_specific_questions` (generate-once per ad).
"""

import time

from cv_bau_students.candidates import repo as candidates_repo
from cv_bau_students.completion.ask import ask, fold_answers_into_profile
from cv_bau_students.completion.diagnose import diagnose_bau_mandatory, diagnose_missing
from cv_bau_students.config import COMPLETION_MAX_ROUNDS
from cv_bau_students.detector.classify import classify
from cv_bau_students.explanation.reason import reason_for_ranking
from cv_bau_students.extractors import document
from cv_bau_students.extractors.profile import extract_profile
from cv_bau_students.jobads.repo import get_ad_by_id
from cv_bau_students.matcher.rank import rank_candidate
from cv_bau_students.models import (
    CandidateAnalysis,
    CandidateProfile,
    CompletionRound,
    GenericResult,
    InterestResult,
    MatchScore,
    PrefilledQuestion,
    RoleSpecificResult,
)
from cv_bau_students.roles.generate import generate_role_questions
from cv_bau_students.translator.translate import translate

# --- Shared extraction step -------------------------------------------------


def _extract_and_classify(file_bytes: bytes, filename: str) -> tuple[CandidateProfile, dict]:
    """Document → text → LLM #1 → language override → Python detector.

    Returns (profile, meta) where meta carries detector audit fields the
    callers fold into their processing_metadata.
    """
    raw_text = document.extract_text(file_bytes, filename)
    language = document.detect_language(raw_text)

    profile = extract_profile(raw_text)
    profile = profile.model_copy(update={"language": language})

    classification = classify(profile)
    if classification.verdict != profile.candidate_type:
        profile = profile.model_copy(update={"candidate_type": classification.verdict})

    meta = {
        "filename": filename,
        "raw_text": raw_text,  # passed through so the candidate row can store it
        "raw_text_chars": len(raw_text),
        "detector_llm_agrees": classification.llm_agrees,
        "detector_reasons": classification.reasons,
    }
    return profile, meta


def _run_completion_loop(
    profile: CandidateProfile,
    *,
    answer_provider,
    diagnose_fn,
) -> tuple[CandidateProfile, list[CompletionRound]]:
    """Iterative completion using `diagnose_fn` to decide what's missing."""
    completion_rounds: list[CompletionRound] = []
    for round_no in range(1, COMPLETION_MAX_ROUNDS + 1):
        missing = diagnose_fn(profile)
        if not missing:
            break
        round_obj = ask(profile, missing, round_no=round_no)
        if not round_obj.questions:
            break
        if answer_provider is None:
            completion_rounds.append(round_obj)
            break
        answers = answer_provider(round_obj) or {}
        round_obj = round_obj.model_copy(update={"answers": answers})
        completion_rounds.append(round_obj)
        if not answers:
            break
        profile = fold_answers_into_profile(profile, round_obj)
    return profile, completion_rounds


# --- Legacy one-shot (back-compat) ------------------------------------------


def analyze_candidate(
    file_bytes: bytes,
    filename: str,
    *,
    answer_provider=None,
) -> CandidateAnalysis:
    """Legacy full pipeline — extract → complete → translate → match → reason.

    Preserved for the original single-page UI + tests. The Phase 12 UI
    uses the two-pass journey below instead.
    """
    started = time.time()
    profile, meta = _extract_and_classify(file_bytes, filename)
    profile, completion_rounds = _run_completion_loop(
        profile, answer_provider=answer_provider, diagnose_fn=diagnose_missing
    )

    translated = translate(profile)
    matches = rank_candidate(profile, translated)
    matches = reason_for_ranking(profile, translated, matches, top_n=5)
    final_missing = diagnose_missing(profile)

    return CandidateAnalysis(
        profile=profile,
        completion_rounds=completion_rounds,
        translated_capabilities=translated,
        matches=matches,
        missing_fields=final_missing,
        processing_metadata={
            **meta,
            "elapsed_seconds": round(time.time() - started, 2),
            "pipeline_phase": "7-reasoning",
            "completion_rounds_run": len(completion_rounds),
            "translated_capability_count": len(translated),
            "matched_ads": len(matches),
        },
    )


# --- Phase 12: two-pass candidate journey -----------------------------------


def run_generic_pass(
    file_bytes: bytes,
    filename: str,
    *,
    answer_provider=None,
    top_n: int = 3,
) -> GenericResult:
    """Stage 1 — role-agnostic. Extract, BAU-complete, hard-filter, score.

    Persists the candidate + translated capabilities (NOT Match rows —
    those land only when the user expresses interest in a specific ad).

    When BAU-mandatory fields are missing and `answer_provider` can't
    fill them, returns `status="needs_completion"` with the open round
    so the UI can ask the candidate.
    """
    profile, meta = _extract_and_classify(file_bytes, filename)

    # BAU-mandatory completion (role-agnostic, strict minimums).
    profile, completion_rounds = _run_completion_loop(
        profile, answer_provider=answer_provider, diagnose_fn=diagnose_bau_mandatory
    )
    still_missing = diagnose_bau_mandatory(profile)
    if still_missing:
        # Translate + persist what we have so the candidate row exists,
        # but flag that we can't match yet.
        translated_partial = translate(profile)
        candidate_id = candidates_repo.store_initial_candidate(
            file_hash=candidates_repo.cv_hash(file_bytes),
            profile=profile,
            capabilities=translated_partial,
            raw_cv_text=meta.get("raw_text"),
        )
        open_round = completion_rounds[-1] if completion_rounds else None
        return GenericResult(
            status="needs_completion",
            profile=profile,
            candidate_id=candidate_id,
            completion_round=open_round,
        )

    # Translate + persist.
    translated = translate(profile)
    candidate_id = candidates_repo.store_initial_candidate(
        file_hash=candidates_repo.cv_hash(file_bytes),
        profile=profile,
        capabilities=translated,
        raw_cv_text=meta.get("raw_text"),
    )

    # Vrstva A (hard filter) + Vrstva B (scoring) live inside rank_candidate.
    # NO per-ad LLM reasoning here — preview cards use the deterministic
    # skill_fit_detail. The (think) reasoning fires once, later, only for the
    # ad the candidate actually expresses interest in (submit_role_specific).
    matches = rank_candidate(profile, translated, top_n=top_n)

    matched_ads = [get_ad_by_id(m.ad_id) for m in matches]
    matched_ads = [a for a in matched_ads if a is not None]

    status = "matched" if matches else "no_matches"
    return GenericResult(
        status=status,
        profile=profile,
        candidate_id=candidate_id,
        matches=matches,
        matched_ads=matched_ads,
    )


def ensure_role_specific_questions(ad_id: int):
    """Generate-once the fixed question template for an ad.

    Thin wrapper: `candidates.repo.ensure_role_questions` does the
    read-or-generate, this binds the LLM-backed factory.
    """
    ad = get_ad_by_id(ad_id)
    if ad is None:
        raise LookupError(f"ad_id {ad_id} not found")
    return candidates_repo.ensure_role_questions(
        ad_id, questions_factory=lambda: generate_role_questions(ad)
    )


def express_interest(candidate_id: int, ad_id: int, status: str) -> InterestResult:
    """Stage 2 — record the candidate's choice.

    `wait`  → just record, no further work.
    `interested` → ensure the AI-generated follow-up questions exist (the BAU
    questionnaire) and return them as a blank form. We do NOT pre-fill answers
    with an LLM — the candidate writes their own (more honest + cheaper); the
    questions themselves are the AI value, surfacing skills the CV alone misses.
    """
    candidates_repo.record_interest(candidate_id, ad_id, status)
    if status == "wait":
        return InterestResult(status="wait", candidate_id=candidate_id, ad_id=ad_id)

    questions = ensure_role_specific_questions(ad_id)
    prefilled = [
        PrefilledQuestion(
            slot=q.slot,
            question_text=q.question_text,
            extract_hint=q.extract_hint,
            prefilled_answer=None,  # candidate fills this in
            prefilled_confidence=0.0,
        )
        for q in questions
    ]
    return InterestResult(
        status="interested",
        candidate_id=candidate_id,
        ad_id=ad_id,
        prefilled_questions=prefilled,
    )


def submit_role_specific(
    candidate_id: int,
    ad_id: int,
    *,
    answers: dict[str, str],
    prefilled_set: set[str],
    edited_set: set[str],
) -> RoleSpecificResult:
    """Stage 3 — store answers, re-rank against the target ad, write Match.

    The role-specific answers (esp. the elevator pitch) feed the
    personal-fit axis via the translator's re-run with the enriched
    context. The Match row is what surfaces the candidate to the
    recruiter for this ad.
    """
    candidates_repo.store_role_answers(
        candidate_id,
        ad_id,
        answers=answers,
        prefilled_set=prefilled_set,
        edited_set=edited_set,
    )

    profile = _load_candidate_profile(candidate_id)
    # Fold the elevator pitch into the profile summary so personal-fit
    # scoring sees it (when the candidate didn't already have a summary).
    pitch = answers.get("elevator_pitch_for_role")
    if pitch and not (profile.summary and profile.summary.strip()):
        profile = profile.model_copy(update={"summary": pitch})

    translated = translate(profile)
    ad = get_ad_by_id(ad_id)
    if ad is None:
        raise LookupError(f"ad_id {ad_id} not found")

    match = _score_single_ad(profile, translated, ad)
    match_list = reason_for_ranking(
        profile, translated, [match], top_n=1, candidate_id=candidate_id
    )
    match = match_list[0] if match_list else match

    candidates_repo.store_match(candidate_id, ad_id, match=match)
    return RoleSpecificResult(candidate_id=candidate_id, ad_id=ad_id, match=match)


# --- Internal helpers -------------------------------------------------------


def _load_candidate_profile(candidate_id: int) -> CandidateProfile:
    """Latest persisted profile for a candidate."""
    from sqlalchemy import select

    from cv_bau_students.db import get_session
    from cv_bau_students.db_models import ProfileVersion

    with get_session() as session:
        row = session.execute(
            select(ProfileVersion)
            .where(ProfileVersion.candidate_id == candidate_id)
            .order_by(ProfileVersion.round.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row is None:
            raise LookupError(f"no profile for candidate_id {candidate_id}")
        return CandidateProfile.model_validate(row.profile_json)


def _score_single_ad(profile, translated, ad) -> MatchScore:
    """Score one ad directly (the target), bypassing the SQL pre-filter."""
    from cv_bau_students.matcher.score import score_match

    return score_match(profile, translated, ad)
