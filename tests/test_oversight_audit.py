"""PR3 — recruiter override (human oversight) + bias-audit disclosure."""

from __future__ import annotations

from cv_bau_students.analytics.audit import audit_by_type, audit_csv
from cv_bau_students.candidates import repo
from cv_bau_students.jobads.repo import store_ad
from cv_bau_students.models import CandidateProfile, JobAd, MatchScore


def _ad() -> int:
    return store_ad(
        JobAd(
            title="Datový analytik",
            location="Praha",
            remote_mode="hybrid",
            level="medior",
            domain="data-analyst",
            must_have=["SQL"],
            nice_to_have=[],
            raw_text="…",
            source="scraped",
        )
    )


def _seed(ad_id: int, *, kind: str, total: float, tag: str) -> int:
    cid = repo.store_initial_candidate(
        file_hash=f"h-{tag}",
        profile=CandidateProfile(candidate_type=kind, language="cs", name=tag),
        capabilities=[],
    )
    repo.record_interest(cid, ad_id, "interested")
    repo.store_match(
        cid,
        ad_id,
        match=MatchScore(
            ad_id=ad_id,
            skill_fit=total,
            bridge_fit=0.0,
            personal_fit=0.0,
            total=total,
            confidence_band=10.0,
        ),
    )
    return cid


def test_override_round_trip():
    ad_id = _ad()
    cid = _seed(ad_id, kind="student", total=80.0, tag="anna")

    # No decision yet.
    d0 = repo.get_candidate_detail(cid, ad_id)
    assert d0.recruiter_override is None and d0.decision_at is None

    ok = repo.set_match_override(cid, ad_id, override=True, note="  zkušenost nesedí  ")
    assert ok is True

    d1 = repo.get_candidate_detail(cid, ad_id)
    assert d1.recruiter_override is True
    assert d1.override_note == "zkušenost nesedí"  # trimmed
    assert d1.decision_at is not None

    # A re-score must NOT wipe the override (separate write path).
    repo.rescore_ad(ad_id)
    d2 = repo.get_candidate_detail(cid, ad_id)
    assert d2.recruiter_override is True and d2.override_note == "zkušenost nesedí"


def test_override_missing_match_returns_false():
    ad_id = _ad()
    assert repo.set_match_override(99999, ad_id, override=True) is False


def test_blank_note_stored_as_none():
    ad_id = _ad()
    cid = _seed(ad_id, kind="student", total=60.0, tag="bob")
    repo.set_match_override(cid, ad_id, override=False, note="   ")
    assert repo.get_candidate_detail(cid, ad_id).override_note is None


def test_audit_by_type_rates_and_four_fifths():
    ad_id = _ad()
    # students: 2, one selected (≥50); experienced: 2, both selected.
    _seed(ad_id, kind="student", total=80.0, tag="s1")
    _seed(ad_id, kind="student", total=30.0, tag="s2")
    _seed(ad_id, kind="experienced", total=70.0, tag="e1")
    _seed(ad_id, kind="experienced", total=90.0, tag="e2")

    rep = audit_by_type(ad_id, threshold=50.0)
    assert rep["total"] == 4
    g = rep["groups"]
    assert g["student"]["n"] == 2 and g["student"]["selected"] == 1
    assert g["student"]["selection_rate"] == 0.5
    assert g["student"]["mean_coverage"] == 55.0
    assert g["experienced"]["selection_rate"] == 1.0
    assert g["career_changer"]["n"] == 0 and g["career_changer"]["selection_rate"] is None
    # min(0.5, 1.0) / max = 0.5 < 0.8 → adverse-impact flag (review prompt).
    assert rep["four_fifths_ratio"] == 0.5
    assert rep["adverse_impact"] is True


def test_audit_four_fifths_uses_unrounded_rates():
    """4/9 vs 5/9 = exactly 0.8 → NOT adverse. Computing from the rounded display
    rates (0.444/0.556 = 0.799) would falsely flag it."""
    ad_id = _ad()
    for i in range(9):
        _seed(ad_id, kind="student", total=(80.0 if i < 4 else 30.0), tag=f"s{i}")
    for i in range(9):
        _seed(ad_id, kind="experienced", total=(80.0 if i < 5 else 30.0), tag=f"e{i}")
    rep = audit_by_type(ad_id, threshold=50.0)
    # exact ratio = (4/9)/(5/9) = 0.8 → not < 0.80
    assert rep["four_fifths_ratio"] == 0.8
    assert rep["adverse_impact"] is False


def test_audit_single_group_ratio_undefined():
    ad_id = _ad()
    _seed(ad_id, kind="student", total=80.0, tag="only")
    rep = audit_by_type(ad_id)
    assert rep["four_fifths_ratio"] is None
    assert rep["adverse_impact"] is False


def test_audit_csv_shape():
    ad_id = _ad()
    _seed(ad_id, kind="student", total=80.0, tag="x")
    csv = audit_csv(audit_by_type(ad_id))
    assert csv.startswith("candidate_type,n,selected,selection_rate,mean_coverage")
    assert "student,1,1," in csv
    assert "adverse_impact," in csv
