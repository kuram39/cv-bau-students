"""Thin orchestrator — student / changer matching pipeline.

Per the design doc: this file is a table of contents, NOT a place for
logic. Each step is a single call into a domain module. The phases
are wired in as stubs in Phase 1 and filled in subsequent phases.
"""

import time

from cv_bau_students.extractors import document
from cv_bau_students.models import CandidateAnalysis, CandidateProfile


def analyze_candidate(
    file_bytes: bytes,
    filename: str,
) -> CandidateAnalysis:
    """Run the full matching pipeline for a student / changer / experienced CV.

    Phase 1 stub: extracts text, detects language, returns an empty
    CandidateAnalysis with the language + filename in metadata. The
    real pipeline steps (detector, profile extraction, completion
    loop, translator, matcher, reasoning) come online in Phases 2–7.
    """
    started = time.time()

    raw_text = document.extract_text(file_bytes, filename)
    language = document.detect_language(raw_text)

    # TODO Phase 2: profile extraction
    # TODO Phase 2: detector.classify()
    # TODO Phase 3: completion loop
    # TODO Phase 4: capability translator
    # TODO Phase 6: matcher
    # TODO Phase 7: reasoning

    profile = CandidateProfile(
        candidate_type="student",  # placeholder; detector overwrites in Phase 2
        language=language,  # type: ignore[arg-type]
    )

    return CandidateAnalysis(
        profile=profile,
        processing_metadata={
            "filename": filename,
            "elapsed_seconds": round(time.time() - started, 2),
            "raw_text_chars": len(raw_text),
            "pipeline_phase": "1-stub",
        },
    )
