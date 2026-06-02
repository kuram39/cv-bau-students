"""scripts.measure_resolution — resolution-rate summary math.

Isolates the arithmetic from the DB by monkeypatching the two resolvers, so the
test asserts runtime-effective %, raw % + the detectable-Czech subset.
"""

from __future__ import annotations

import scripts.measure_resolution as mr


def test_summarize_runtime_prefers_esco_term(monkeypatch):
    # Only English ESCO terms resolve here.
    resolvable = {"SQL", "data modelling", "Python"}
    monkeypatch.setattr(mr, "resolve_skill", lambda p: (1, p) if p in resolvable else None)
    monkeypatch.setattr(mr, "resolve_skill_esco", lambda p: None)

    rows = [
        ("SQL", None),  # resolves on canonical
        ("datové modelování", "data modelling"),  # canonical fails, esco_term wins
        ("dolování dat", None),  # czech, unresolved
        ("Python analysis", "Python"),  # ascii canonical; esco_term resolves
    ]
    s = mr.summarize(rows)

    # runtime = {SQL, data modelling, dolování dat, Python} → 3/4 resolve.
    assert s["runtime_total"] == 4
    assert s["runtime_resolved"] == 3
    assert s["runtime_pct"] == 75.0
    # raw skill_canonical = {SQL, datové modelování, dolování dat, Python pro analýzu}
    # only SQL resolves raw → 1/4.
    assert s["raw_total"] == 4
    assert s["raw_resolved"] == 1
    assert s["raw_pct"] == 25.0
    # detectable-Czech raw phrases: datové modelování, dolování dat → 2; 0 resolve raw.
    assert s["czech_total"] == 2
    assert s["czech_resolved"] == 0
    assert s["czech_pct"] == 0.0
    assert "datové modelování" in s["unresolved"]


def test_summarize_empty_is_safe():
    s = mr.summarize([])
    assert s["rows"] == 0
    assert s["runtime_pct"] == 0.0 and s["raw_pct"] == 0.0 and s["czech_pct"] == 0.0
    assert s["unresolved"] == []
