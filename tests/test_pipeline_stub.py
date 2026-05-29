"""Smoke test for the Phase 1 pipeline stub.

Verifies that document extraction + language detection wire correctly
and that analyze_candidate returns a valid CandidateAnalysis even
before the LLM-driven phases are filled in.
"""

from cv_bau_students.models import CandidateAnalysis
from cv_bau_students.pipeline import analyze_candidate

CS_TXT = (
    "Jan Novák\n"
    "Student bakalářského studia Informatiky na ČVUT.\n"
    "\n"
    "Školy:\n"
    "- ČVUT FIT, Bakalář (2022 - dosud), průměr 1.5.\n"
    "\n"
    "Projekty:\n"
    "- Diplomová práce: analýza sentimentu tweetů pomocí Pythonu a BERT modelu.\n"
    "- Školní projekt: webová aplikace pro školní jídelnu, React + Django.\n"
    "\n"
    "Brigády:\n"
    "- McDonald's, obsluha, 2 roky.\n"
    "\n"
    "Jazyky: angličtina B2, němčina A2.\n"
).encode()


def test_analyze_candidate_returns_pipeline_skeleton():
    result = analyze_candidate(CS_TXT, "sample.txt")
    assert isinstance(result, CandidateAnalysis)
    assert result.profile.language == "cs"
    assert result.processing_metadata["raw_text_chars"] > 0
    assert result.processing_metadata["pipeline_phase"] == "1-stub"


def test_language_detection_falls_back_to_english_for_ascii():
    en_txt = b"John Doe, Computer Science student at Charles University."
    result = analyze_candidate(en_txt, "sample.txt")
    assert result.profile.language == "en"
