"""Tests for `roles.isco_resolver` — lexical hit, LLM fallback, unresolved.

Seeds the `occupations` table directly (the loader has its own test) and
exercises `resolve_isco_for_ad`. The LLM fallback is monkeypatched so no
key / network is needed (mirrors the conftest mock-by-substring pattern).
"""

from __future__ import annotations

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Occupation
from cv_bau_students.roles import isco_resolver


def _seed_occupations(rows: list[dict]) -> None:
    with get_session() as session:
        for r in rows:
            session.add(
                Occupation(
                    occupation_uri=r["uri"],
                    isco_code=r["isco"],
                    preferred_label=r["label"],
                    alt_labels=r.get("alt", []),
                    lang=r.get("lang", "en"),
                )
            )


def test_lexical_hit_resolves_without_llm(monkeypatch):
    # CS alt-label matches the ad title verbatim; en row supplies the display label.
    _seed_occupations(
        [
            {"uri": "uri:da", "isco": "2511", "label": "data analyst", "lang": "en"},
            {
                "uri": "uri:da",
                "isco": "2511",
                "label": "analytik dat",
                "alt": ["datový analytik", "datová analytička"],
                "lang": "cs",
            },
        ]
    )

    def _boom(*a, **k):  # the LLM must NOT be touched on a lexical hit
        raise AssertionError("LLM should not be called for a lexical hit")

    monkeypatch.setattr(isco_resolver.llm, "call_json", _boom)

    code, label, method = isco_resolver.resolve_isco_for_ad("Datový analytik", domain="data")
    assert code == "2511"
    assert label == "data analyst"  # english preferred label preferred for display
    assert method == "lexical"


def test_llm_fallback_when_no_lexical_match(monkeypatch):
    _seed_occupations(
        [{"uri": "uri:mkt", "isco": "2431", "label": "marketing specialist", "lang": "en"}]
    )
    captured = {}

    def _fake_call_json(prompt, **kwargs):
        captured["prompt"] = prompt
        return {"isco_code": "2431", "occupation_label": "marketing specialist"}

    monkeypatch.setattr(isco_resolver.llm, "call_json", _fake_call_json)

    # Shares the token "marketing" → shortlisted, but no verbatim label match.
    code, label, method = isco_resolver.resolve_isco_for_ad(
        "Growth hacker marketing", domain="growth", must_have=["SEO"]
    )
    assert code == "2431"
    assert method == "llm"
    assert "marketing specialist (2431)" in captured["prompt"]


def test_llm_pick_outside_shortlist_is_rejected(monkeypatch):
    _seed_occupations(
        [{"uri": "uri:mkt", "isco": "2431", "label": "marketing specialist", "lang": "en"}]
    )
    # Model hallucinates a code that isn't in the menu → treated as no pick.
    monkeypatch.setattr(isco_resolver.llm, "call_json", lambda *a, **k: {"isco_code": "9999"})
    code, label, method = isco_resolver.resolve_isco_for_ad("Growth marketing", domain="growth")
    assert code is None
    assert method == "unresolved"


def test_unresolved_when_no_occupations():
    code, label, method = isco_resolver.resolve_isco_for_ad("Anything", domain="x")
    assert (code, label, method) == (None, None, "unresolved")


def test_short_title_does_not_reverse_match_multiword_occupation(monkeypatch):
    # A one-word title "Data" must NOT trust-match "data analyst" via the
    # reverse (haystack-in-label) direction → falls through to LLM (mocked None).
    _seed_occupations([{"uri": "uri:da", "isco": "2511", "label": "data analyst", "lang": "en"}])
    monkeypatch.setattr(isco_resolver.llm, "call_json", lambda *a, **k: {"isco_code": None})
    code, _, method = isco_resolver.resolve_isco_for_ad("Data", domain="data")
    assert code is None
    assert method != "lexical"


def test_short_label_does_not_spuriously_substring_match(monkeypatch):
    # A 3-char label must not match via substring; only exact equality counts.
    _seed_occupations([{"uri": "uri:x", "isco": "1111", "label": "dat", "lang": "en"}])
    monkeypatch.setattr(isco_resolver.llm, "call_json", lambda *a, **k: {"isco_code": None})
    code, _, method = isco_resolver.resolve_isco_for_ad("Datový analytik", domain="data")
    assert code is None
    assert method == "unresolved"
