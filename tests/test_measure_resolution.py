"""scripts.measure_resolution — resolution-rate summary math.

Isolates the arithmetic from the DB by monkeypatching the two resolvers, so the
test asserts runtime-effective %, raw % + the detectable-Czech subset.
"""

from __future__ import annotations

import scripts.measure_resolution as mr


def test_summarize_runtime_is_esco_only_and_per_row(monkeypatch):
    # ESCO (runtime) resolves the English terms; seed resolves only "SQL".
    monkeypatch.setattr(mr, "resolve_skill", lambda p: (1, p) if p == "SQL" else None)
    monkeypatch.setattr(
        mr,
        "resolve_skill_esco",
        lambda p: (2, p) if p in {"SQL", "data modelling", "Python"} else None,
    )

    # rows = (skill_canonical, esco_term, esco_skill_id)
    rows = [
        ("SQL", None, None),  # runtime "SQL" → ESCO ✓
        ("SQL", None, None),  # duplicate capability → counts AGAIN per row
        ("datové modelování", "data modelling", None),  # runtime esco_term ✓ (raw fails)
        ("dolování dat", None, None),  # czech, esco_term None, unresolved
        ("tunnel boring", None, 77),  # ascii; stored esco_skill_id → runtime ✓ though phrase fails
    ]
    s = mr.summarize(rows)

    # runtime = per ROW (5): SQL, SQL, data modelling, +stored-id row = 4/5
    # ("dolování dat" has no id and doesn't resolve).
    assert s["runtime_total"] == 5
    assert s["runtime_resolved"] == 4
    assert s["runtime_pct"] == 80.0
    # raw distinct skill_canonical = 4; only SQL resolves (seed OR esco) → 1/4.
    assert s["raw_total"] == 4
    assert s["raw_resolved"] == 1
    assert s["raw_pct"] == 25.0
    # detectable-Czech raw phrases: datové modelování, dolování dat → 2; 0 resolve.
    assert s["czech_total"] == 2
    assert s["czech_resolved"] == 0
    assert s["czech_pct"] == 0.0
    assert "datové modelování" in s["unresolved"]


def test_summarize_empty_is_safe():
    s = mr.summarize([])
    assert s["rows"] == 0
    assert s["runtime_pct"] == 0.0 and s["raw_pct"] == 0.0 and s["czech_pct"] == 0.0
    assert s["unresolved"] == []
