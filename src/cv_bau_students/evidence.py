"""Evidence-strength tiers for translated capabilities (SFIA-style ladder).

A matched skill's *reliability* should come from HOW it is demonstrated
(`source_type`), not the translator LLM's self-confidence. Research #5 (faking
is the norm; structured/behavioral evidence > self-report) + #2 (calibration).

Tier ladder: delivered/real-world > academic/learning project > side/claimed.
A skill matched only via `explicit_skills` (a bare CV list, no backing
capability) has no source_type → treated as the weakest ("claimed").
"""

from __future__ import annotations

# source_type → tier.
# NOTE: "work" (regular full-time/part-time professional job) must be "strong".
# Without it, experienced candidates' skills fallthrough to "other" → "weak",
# meaning a data analyst with 5 years of professional SQL work scores the same
# evidence tier as a hobby. Added alongside the SourceType literal (models.py)
# and the translator prompt after PR #28 introduced the evidence system without
# a "work" type in the enum.
_TIER: dict[str, str] = {
    "work": "strong",
    "internship": "strong",
    "open_source": "strong",
    "certification": "strong",
    "thesis": "medium",
    "school_project": "medium",
    "course": "medium",
    "brigada": "weak",
    "hobby": "weak",
    "language": "weak",
    "other": "weak",
}

TIER_EMOJI = {"strong": "🟢", "medium": "🟡", "weak": "⚪"}
TIER_LABEL_CS = {
    "strong": "prokázané praxí",
    "medium": "projekt/studium",
    "weak": "jen uvedeno",
}


def evidence_tier(source_type: str | None) -> str:
    """Map a capability source_type to 'strong' | 'medium' | 'weak'.
    Unknown / missing (explicit-skill-only matches) → 'weak'."""
    return _TIER.get(source_type or "", "weak")


def doloznost_label(tiers: list[str]) -> str:
    """Overall evidence-strength of a candidate's matched skills, in Czech.

    'vysoká' when at least half the matched skills are strong-evidenced;
    'nízká' when most are claim-only; else 'střední'. Empty → 'nízká'."""
    if not tiers:
        return "nízká"
    n = len(tiers)
    strong = sum(t == "strong" for t in tiers)
    weak = sum(t == "weak" for t in tiers)
    if strong * 2 >= n:
        return "vysoká"
    if weak * 2 > n:
        return "nízká"
    return "střední"
