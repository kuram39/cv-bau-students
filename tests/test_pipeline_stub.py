"""End-to-end pipeline tests with mocked LLM calls.

The orchestrator wires document extraction → profile extraction LLM →
Python detector → completion loop → translator LLM. We patch
`cv_bau_students.llm.call_json` with a dispatcher that returns the
right shape per prompt substring so tests run without network access.
"""

from unittest.mock import patch

from cv_bau_students.models import CandidateAnalysis
from cv_bau_students.pipeline import analyze_candidate
from cv_bau_students.translator.translate import _translate_raw


def _make_dispatcher(profile_payload: dict, translate_payload: dict | None = None):
    """Route mocked LLM calls by prompt-substring detection.

    Each call_json invocation gets matched against a marker fragment in
    the rendered prompt to decide which JSON shape to return.
    """
    translate_payload = translate_payload or {"translated_capabilities": []}

    def _dispatch(prompt: str) -> dict:
        if "Translate student / career-changer artefacts" in prompt:
            return translate_payload
        # Default: profile extraction prompt.
        return profile_payload

    return _dispatch


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


_STUDENT_PROFILE_PAYLOAD = {
    "candidate_type": "student",
    "language": "en",  # pipeline overrides with the language detector's verdict
    "summary": None,
    "target_domains": [],
    "explicit_skills": ["Python", "React", "Django"],
    "languages": [
        {"language": "English", "min_level": "B2"},
        {"language": "German", "min_level": "A2"},
    ],
    "education": [
        {
            "institution": "ČVUT FIT",
            "field_of_study": "Informatika",
            "degree": "Bachelor",
            "start_year": 2022,
            "in_progress": True,
        }
    ],
    "work_experience": [
        {
            "employer": "McDonald's",
            "role": "Obsluha",
            "is_brigada": True,
        }
    ],
    "school_projects": [
        {
            "title": "Sentiment analysis of tweets",
            "technologies": ["Python", "BERT"],
        },
        {
            "title": "School cafeteria web app",
            "technologies": ["React", "Django"],
        },
    ],
    "total_work_years": 0.6,
    "most_recent_grad_year": 2025,
    "studying_in_progress": True,
}


def test_analyze_candidate_runs_full_phase4_pipeline():
    _translate_raw.cache_clear()
    dispatcher = _make_dispatcher(
        profile_payload=_STUDENT_PROFILE_PAYLOAD,
        translate_payload={
            "translated_capabilities": [
                {
                    "skill": "Python",
                    "evidence_quote": "Sentiment analysis of tweets",
                    "confidence": 0.65,
                    "caveat": "Academic project",
                    "source_type": "school_project",
                    "relevance": "must_have",
                }
            ]
        },
    )
    with patch("cv_bau_students.llm.call_json", side_effect=dispatcher):
        result = analyze_candidate(CS_TXT, "sample.txt")

    assert isinstance(result, CandidateAnalysis)
    # Language always comes from the deterministic detector, never the LLM.
    assert result.profile.language == "cs"
    assert result.profile.candidate_type == "student"
    assert result.processing_metadata["pipeline_phase"] == "4-translator"
    assert result.processing_metadata["detector_llm_agrees"] is True
    assert result.processing_metadata["raw_text_chars"] > 0
    assert len(result.translated_capabilities) == 1
    assert result.translated_capabilities[0].skill == "Python"


def test_language_detection_falls_back_to_english_for_ascii():
    _translate_raw.cache_clear()
    en_txt = b"John Doe, Computer Science student at Charles University."
    dispatcher = _make_dispatcher(profile_payload=_STUDENT_PROFILE_PAYLOAD)
    with patch("cv_bau_students.llm.call_json", side_effect=dispatcher):
        result = analyze_candidate(en_txt, "sample.txt")
    assert result.profile.language == "en"


def test_pipeline_overrides_candidate_type_when_heuristic_disagrees():
    """LLM tags the candidate as `student`; force the heuristic to see an
    experienced candidate by providing enough work years + ended study.
    """
    _translate_raw.cache_clear()
    experienced_payload = _STUDENT_PROFILE_PAYLOAD | {
        "candidate_type": "student",  # LLM tag — should be overruled
        "total_work_years": 6.0,
        "studying_in_progress": False,
        "most_recent_grad_year": 2018,
        "work_experience": [{"employer": "Avast", "role": "Engineer", "domain": "cybersecurity"}],
    }
    dispatcher = _make_dispatcher(profile_payload=experienced_payload)
    with patch("cv_bau_students.llm.call_json", side_effect=dispatcher):
        result = analyze_candidate(CS_TXT, "sample.txt")
    assert result.profile.candidate_type == "experienced"
    assert result.processing_metadata["detector_llm_agrees"] is False
