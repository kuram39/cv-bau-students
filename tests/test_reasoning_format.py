"""parse_reasoning tolerates valid, truncated, and non-JSON rationale strings."""

from __future__ import annotations

import json

from cv_bau_students.explanation.format import parse_reasoning


def test_valid_json_parses_all_fields():
    raw = json.dumps(
        {
            "verdict": "Pravděpodobně ne — chybí Power BI.",
            "strengths": ["Python z bakalářky", "SQL základy"],
            "gaps": ["Power BI chybí"],
            "interview_prompts": ["Ukaž SQL projekt"],
        },
        ensure_ascii=False,
    )
    r = parse_reasoning(raw)
    assert r["verdict"].startswith("Pravděpodobně ne")
    assert r["strengths"] == ["Python z bakalářky", "SQL základy"]
    assert r["gaps"] == ["Power BI chybí"]
    assert r["interview_prompts"] == ["Ukaž SQL projekt"]
    assert r["truncated"] is False


def test_truncated_json_salvages_verdict_and_arrays():
    # Cut off mid-"gaps" — strict json.loads fails; we still salvage fields.
    raw = (
        '{"verdict": "Pravděpodobně ne — chybí Power BI a SQL praxe.", '
        '"strengths": ["Python pipeline", "GPA 1,4"], '
        '"gaps": ["Power BI zcela chybí", "SQL jen základy'
    )
    r = parse_reasoning(raw)
    assert r["truncated"] is True
    assert "Power BI" in r["verdict"]
    assert "Python pipeline" in r["strengths"]
    # The complete array item before the cut is recovered.
    assert "Power BI zcela chybí" in r["gaps"]
    # No raw JSON braces leak into any field.
    assert "{" not in r["verdict"]


def test_plain_text_becomes_verdict():
    r = parse_reasoning("Jen prostý text bez JSON.")
    assert r["verdict"] == "Jen prostý text bez JSON."
    assert r["truncated"] is True


def test_empty_returns_blank():
    r = parse_reasoning(None)
    assert r["verdict"] == ""
    assert r["strengths"] == []
