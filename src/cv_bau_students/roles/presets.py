"""Base-skill presets per occupation (the recruiter's one-click starting set).

A *preset* is the position's "base case" — the skills shared by students and
experienced hires alike, so the recruiter can say "score everyone on these,
not just on years of experience". This is what makes a student and an
experienced candidate comparable on the same axis.

Presets are defined as **English ESCO skill terms** (the same phrasing the
translator emits as `esco_term`). They're resolved to skill ids via
`resolve_skill_esco` at apply time, which keeps the target ids in the *same*
namespace the candidate capabilities resolve to — so coverage actually matches.

Keyed by ISCO-08 code. Unknown occupations fall back to the ad's own
must_have/nice_to_have (see `jobads.repo.base_preset_ids`).
"""

from __future__ import annotations

# ISCO code → {"core": [...english terms...], "optional": [...]}.
BASE_SKILL_PRESETS: dict[str, dict[str, list[str]]] = {
    # 2511 — Systems analysts / data analyst family.
    "2511": {
        "core": ["SQL", "Python", "data analysis", "data visualisation"],
        "optional": ["statistics", "machine learning", "data cleansing", "reporting"],
    },
}


def preset_terms_for_isco(isco_code: str | None) -> dict[str, list[str]] | None:
    """English-term preset for an ISCO code, or None when none is defined."""
    if not isco_code:
        return None
    return BASE_SKILL_PRESETS.get(isco_code)
