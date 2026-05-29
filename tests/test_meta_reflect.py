"""Meta-reflection log tests."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session
from cv_bau_students.db_models import (
    Candidate,
    Match,
    ProfileVersion,
    TranslatedCapabilityRow,
)
from cv_bau_students.meta.reflect import reflect


@pytest.fixture(autouse=True)
def _seed_taxonomy():
    with get_session() as session:
        _truncate_taxonomy(session)
        canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
        _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)
    yield


def _seed_run(candidate_type: str = "student") -> int:
    with get_session() as session:
        cand = Candidate(
            cv_hash="abc",
            language="en",
            type=candidate_type,
            created_at=datetime.utcnow(),
        )
        session.add(cand)
        session.flush()
        session.add(
            ProfileVersion(candidate_id=cand.id, round=0, profile_json={"summary": "redacted"})
        )
        session.add(
            TranslatedCapabilityRow(
                candidate_id=cand.id,
                skill_canonical="Python",
                evidence_quote="...",
                confidence=0.6,
                source_type="school_project",
                relevance="must_have",
            )
        )
        session.add(
            Match(
                candidate_id=cand.id,
                ad_id=1,
                skill_fit=70,
                bridge_fit=60,
                personal_fit=55,
                total=64,
                confidence_band=18,
            )
        )
        return cand.id


_FAKE_REFLECTION = {
    "observations": [
        "Average translator confidence sits at 0.6 — consistent with mid-tier evidence quality.",
    ],
    "suggested_adjustments": [
        {
            "rubric_or_prompt": "translate_capabilities.md",
            "change": "tighten brigada ceiling from 0.55 to 0.5",
            "rationale": "no batch evidence yet, but matches plan intent",
        }
    ],
    "open_questions": [
        "Need more than one batch to see if students systematically miss target_domains."
    ],
}


def test_reflect_appends_to_improvement_log(tmp_path: Path):
    _seed_run("student")
    log_path = tmp_path / "IMPROVEMENT_LOG.md"
    with patch("cv_bau_students.llm.call_json", return_value=_FAKE_REFLECTION):
        payload = reflect(batch_size=5, log_path=log_path)
    assert payload["observations"]
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "## " in content
    assert "Observations" in content
    assert "Suggested adjustments" in content
    assert "Open questions" in content


def test_reflect_returns_empty_when_no_candidates(tmp_path: Path):
    with patch("cv_bau_students.llm.call_json") as mock_call:
        payload = reflect(batch_size=5, log_path=tmp_path / "log.md")
    assert payload == {"observations": [], "suggested_adjustments": [], "open_questions": []}
    assert mock_call.call_count == 0


def test_reflect_never_includes_candidate_specific_identifiers(tmp_path: Path):
    _seed_run("student")
    captured: dict[str, str] = {}

    def _capture(prompt: str) -> dict:
        captured["prompt"] = prompt
        return _FAKE_REFLECTION

    with patch("cv_bau_students.llm.call_json", side_effect=_capture):
        reflect(batch_size=5, log_path=tmp_path / "log.md")

    # Reflection prompt should NOT carry CV text or candidate identifiers
    # beyond aggregate counts.
    assert "abc" not in captured["prompt"]  # cv_hash
    assert "redacted" not in captured["prompt"]  # the seeded summary text
