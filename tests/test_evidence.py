"""Evidence-strength tier mapping + aggregate doloženost label."""

from __future__ import annotations

from cv_bau_students.evidence import doloznost_label, evidence_tier


def test_tier_mapping():
    assert evidence_tier("work") == "strong"  # real non-brigáda employment — strongest
    assert evidence_tier("internship") == "strong"
    assert evidence_tier("open_source") == "strong"
    assert evidence_tier("certification") == "strong"
    assert evidence_tier("thesis") == "medium"
    assert evidence_tier("school_project") == "medium"
    assert evidence_tier("course") == "medium"
    assert evidence_tier("brigada") == "weak"
    assert evidence_tier("hobby") == "weak"
    # Unknown / explicit-only (no source_type) → weak.
    assert evidence_tier(None) == "weak"
    assert evidence_tier("nonsense") == "weak"


def test_doloznost_label():
    assert doloznost_label([]) == "nízká"
    assert doloznost_label(["strong", "strong", "weak"]) == "vysoká"  # ≥half strong
    assert doloznost_label(["strong", "medium"]) == "vysoká"  # 1/2 strong
    assert doloznost_label(["medium", "medium", "weak"]) == "střední"
    assert doloznost_label(["weak", "weak", "medium"]) == "nízká"  # >half weak
