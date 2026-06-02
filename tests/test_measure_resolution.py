"""scripts.measure_resolution — resolution-rate summary math.

Isolates the arithmetic from the DB by monkeypatching the two resolvers, so the
test asserts overall %, the Czech-diacritic subset %, and the unresolved tail.
"""

from __future__ import annotations

import scripts.measure_resolution as mr


def test_summarize_overall_and_czech_split(monkeypatch):
    # "resolvable" phrases — everything else returns None from both resolvers.
    resolvable = {"SQL", "Python", "analýza dat"}
    monkeypatch.setattr(mr, "resolve_skill", lambda p: (1, p) if p in resolvable else None)
    monkeypatch.setattr(mr, "resolve_skill_esco", lambda p: None)

    phrases = [
        "SQL",  # ascii, resolves
        "Python",  # ascii, resolves
        "analýza dat",  # czech, resolves
        "dolování dat",  # czech, unresolved
        "řízení týmu",  # czech, unresolved
        "widgetcraft",  # ascii, unresolved
    ]
    s = mr.summarize(phrases)

    assert s["total"] == 6
    assert s["resolved"] == 3
    assert s["resolved_pct"] == 50.0
    # Czech-diacritic phrases: analýza, dolování, řízení = 3; only 1 resolves.
    assert s["czech_total"] == 3
    assert s["czech_resolved"] == 1
    assert s["czech_resolved_pct"] == 33.3
    assert set(s["unresolved"]) == {"dolování dat", "řízení týmu", "widgetcraft"}


def test_summarize_empty_is_safe():
    s = mr.summarize([])
    assert s == {
        "total": 0,
        "resolved": 0,
        "resolved_pct": 0.0,
        "czech_total": 0,
        "czech_resolved": 0,
        "czech_resolved_pct": 0.0,
        "unresolved": [],
    }


def test_esco_fallback_counts_as_resolved(monkeypatch):
    # Phrase resolves only via the ESCO namespace, not the seed namespace.
    monkeypatch.setattr(mr, "resolve_skill", lambda p: None)
    monkeypatch.setattr(mr, "resolve_skill_esco", lambda p: (9, p) if p == "ETL" else None)
    s = mr.summarize(["ETL", "nope"])
    assert s["resolved"] == 1
    assert s["resolved_pct"] == 50.0
