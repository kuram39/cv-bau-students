"""Thin orchestrator — student / changer matching pipeline.

Per the design doc: this file is a table of contents, NOT a place for
logic. Each step is a single call into a domain module. The phases are
wired in incrementally — Phase 2 adds profile extraction + detector;
later phases add completion loop, translator, matcher, reasoning.
"""

import time

from cv_bau_students.completion.ask import ask, fold_answers_into_profile
from cv_bau_students.completion.diagnose import diagnose_missing
from cv_bau_students.config import COMPLETION_MAX_ROUNDS
from cv_bau_students.detector.classify import classify
from cv_bau_students.extractors import document
from cv_bau_students.extractors.profile import extract_profile
from cv_bau_students.matcher.rank import rank_candidate
from cv_bau_students.models import CandidateAnalysis, CompletionRound
from cv_bau_students.translator.translate import translate


def analyze_candidate(
    file_bytes: bytes,
    filename: str,
    *,
    answer_provider=None,
) -> CandidateAnalysis:
    """Run the full matching pipeline for a student / changer / experienced CV.

    Phase 3: PDF/DOCX → text → LLM #1 (extract_profile) → Python
    detector → iterative completion loop (up to `COMPLETION_MAX_ROUNDS`
    rounds). Subsequent phases bolt on capability translation, matcher,
    and reasoning.

    `answer_provider` is a callable `(CompletionRound) -> dict[str, str]`
    mapping `question.field` to the candidate's text answer. The pipeline
    keeps running the question-generator while it returns questions; if
    `answer_provider` is `None` we record the open questions and stop
    (recruiter / UI handles the back-and-forth).
    """
    started = time.time()

    raw_text = document.extract_text(file_bytes, filename)
    language = document.detect_language(raw_text)

    # LLM #1 — extract structured profile (includes candidate_type tag).
    profile = extract_profile(raw_text)
    # Language detector is the source of truth — LLM may disagree on
    # hybrid CVs.
    profile = profile.model_copy(update={"language": language})

    # Python classifier re-applies the candidate-type heuristics so the
    # audit trail is visible if the LLM's tag disagrees.
    classification = classify(profile)
    if classification.verdict != profile.candidate_type:
        profile = profile.model_copy(update={"candidate_type": classification.verdict})

    # Iterative completion — up to COMPLETION_MAX_ROUNDS rounds.
    completion_rounds: list[CompletionRound] = []
    for round_no in range(1, COMPLETION_MAX_ROUNDS + 1):
        missing = diagnose_missing(profile)
        if not missing:
            break
        round_obj = ask(profile, missing, round_no=round_no)
        if not round_obj.questions:
            break
        if answer_provider is None:
            # No interactive answer source — keep the open round so the
            # UI / recruiter can ask the candidate.
            completion_rounds.append(round_obj)
            break
        answers = answer_provider(round_obj) or {}
        round_obj = round_obj.model_copy(update={"answers": answers})
        completion_rounds.append(round_obj)
        if not answers:
            break
        profile = fold_answers_into_profile(profile, round_obj)

    # LLM #3 — translate student / changer artefacts into experienced-
    # language capabilities. Confidence floor + dedup happen inside.
    translated = translate(profile)

    # Phase 6 — rank ads via hard filter + 3-axis scoring.
    matches = rank_candidate(profile, translated)

    # TODO Phase 7: reasoning

    final_missing = diagnose_missing(profile)

    return CandidateAnalysis(
        profile=profile,
        completion_rounds=completion_rounds,
        translated_capabilities=translated,
        matches=matches,
        missing_fields=final_missing,
        processing_metadata={
            "filename": filename,
            "elapsed_seconds": round(time.time() - started, 2),
            "raw_text_chars": len(raw_text),
            "pipeline_phase": "6-matcher",
            "detector_llm_agrees": classification.llm_agrees,
            "detector_reasons": classification.reasons,
            "completion_rounds_run": len(completion_rounds),
            "translated_capability_count": len(translated),
            "matched_ads": len(matches),
        },
    )
