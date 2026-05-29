"""Thin orchestrator — student / changer matching pipeline.

Per the design doc: this file is a table of contents, NOT a place for
logic. Each step is a single call into a domain module. The phases are
wired in incrementally — Phase 2 adds profile extraction + detector;
later phases add completion loop, translator, matcher, reasoning.
"""

import time

from cv_bau_students.detector.classify import classify
from cv_bau_students.extractors import document
from cv_bau_students.extractors.profile import extract_profile
from cv_bau_students.models import CandidateAnalysis


def analyze_candidate(
    file_bytes: bytes,
    filename: str,
) -> CandidateAnalysis:
    """Run the full matching pipeline for a student / changer / experienced CV.

    Phase 2: PDF/DOCX → text → LLM #1 (extract_profile) → Python
    detector. Subsequent phases bolt on the completion loop, capability
    translator, matcher, and reasoning.
    """
    started = time.time()

    raw_text = document.extract_text(file_bytes, filename)
    language = document.detect_language(raw_text)

    # LLM #1 — extract structured profile (includes candidate_type tag).
    profile = extract_profile(raw_text)
    # Force language to whatever the language detector saw — the LLM may
    # disagree on a hybrid CV; the detector is the source of truth.
    profile = profile.model_copy(update={"language": language})

    # Python classifier re-applies the candidate-type heuristics so the
    # audit trail is visible if the LLM's tag disagrees.
    classification = classify(profile)
    if classification.verdict != profile.candidate_type:
        profile = profile.model_copy(update={"candidate_type": classification.verdict})

    # TODO Phase 3: completion loop
    # TODO Phase 4: capability translator
    # TODO Phase 6: matcher
    # TODO Phase 7: reasoning

    return CandidateAnalysis(
        profile=profile,
        processing_metadata={
            "filename": filename,
            "elapsed_seconds": round(time.time() - started, 2),
            "raw_text_chars": len(raw_text),
            "pipeline_phase": "2-detector",
            "detector_llm_agrees": classification.llm_agrees,
            "detector_reasons": classification.reasons,
        },
    )
