"""Tests for the Phase 12c CV-sourcing scripts.

`fetch_hf_resume_samples` is exercised with a mocked HTTP layer (no
network). `generate_student_cvs` is exercised with a mocked LLM client.
The fallback path is exercised against the in-repo fixtures.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts import fetch_hf_resume_samples as hf
from scripts import generate_student_cvs as gen

# --- HF fetch ---------------------------------------------------------------


def _fake_hf_payload(n_unique: int) -> dict:
    rows = []
    for i in range(n_unique):
        # Each body distinct (different prefix) and > 400 chars.
        body = f"RESUME NUMBER {i} " + ("Data analysis experience. " * 30)
        rows.append(
            {
                "row": {
                    "Resume_test": body,
                    "instruction": "Generate a Resume for a Data Science Job",
                }
            }
        )
    # Add a duplicate of row 0 to prove dedup.
    if rows:
        rows.append({"row": {"Resume_test": rows[0]["row"]["Resume_test"], "instruction": "x"}})
    return {"rows": rows}


def test_fetch_dedups_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(hf, "OUT_DIR", tmp_path / "experienced")
    with patch.object(hf, "_http_get_json", return_value=_fake_hf_payload(3)):
        bodies = hf._fetch_category("Data Science", want=3)
    # 3 unique despite the duplicate in the payload.
    assert len(bodies) == 3
    assert len({b[:40] for b in bodies}) == 3


def test_fetch_appends_cz_anchor(tmp_path, monkeypatch):
    out = tmp_path / "experienced"
    monkeypatch.setattr(hf, "OUT_DIR", out)
    bodies = ["A real-looking resume body " * 30]
    n = hf._write_samples(bodies)
    assert n == 1
    written = (out / "hf_sample_1.txt").read_text(encoding="utf-8")
    assert "Lokalita: Praha" in written
    assert "čeština" in written


def test_fetch_fallback_copies_fixtures(tmp_path, monkeypatch):
    out = tmp_path / "experienced"
    monkeypatch.setattr(hf, "OUT_DIR", out)
    monkeypatch.setattr(hf, "FALLBACK_DIR", Path("tests/fixtures/experienced_fallback"))
    n = hf._use_fallback(3)
    assert n == 3
    assert len(list(out.glob("*.txt"))) == 3


# --- Student generation -----------------------------------------------------


def test_generate_student_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "OUT_DIR", tmp_path / "students")
    (tmp_path / "students").mkdir(parents=True)
    with patch.object(gen, "_generate_cv", return_value="Anna Nováková\nCV text…"):
        # Build a one-persona run by patching PERSONAS.
        monkeypatch.setattr(gen, "PERSONAS", {"anna": "brief for anna"})
        rc = gen.main_for_test()
    assert rc == 0
    out = tmp_path / "students" / "persona_anna.txt"
    assert out.exists()
    assert "Anna" in out.read_text(encoding="utf-8")


def test_generate_skips_existing_without_force(tmp_path, monkeypatch):
    students = tmp_path / "students"
    students.mkdir(parents=True)
    (students / "persona_anna.txt").write_text("ORIGINAL", encoding="utf-8")
    monkeypatch.setattr(gen, "OUT_DIR", students)
    monkeypatch.setattr(gen, "PERSONAS", {"anna": "brief"})
    called = {"n": 0}

    def _fake_gen(_brief):
        called["n"] += 1
        return "NEW"

    with patch.object(gen, "_generate_cv", side_effect=_fake_gen):
        gen.main_for_test(force=False)
    assert called["n"] == 0  # skipped
    assert (students / "persona_anna.txt").read_text() == "ORIGINAL"
