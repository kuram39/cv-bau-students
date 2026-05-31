"""Smoke tests for the Streamlit panels.

Streamlit isn't running here, so we replace the `st` module in each
panel with a MagicMock that supports the context-manager + columns
protocol the panels use. The goal is to catch attribute / data-shape
errors in the render path, not to assert pixels.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from cv_bau_students.candidates import repo as candidates_repo
from cv_bau_students.models import GapItem, JobAd, MatchScore
from cv_bau_students.ui import recruiter_panel


def _fake_st() -> MagicMock:
    st = MagicMock()

    @contextmanager
    def _cm(*_a, **_k):
        yield st

    st.container.side_effect = lambda *a, **k: _cm()
    st.expander.side_effect = lambda *a, **k: _cm()
    st.form.side_effect = lambda *a, **k: _cm()
    st.spinner.side_effect = lambda *a, **k: _cm()

    # columns(n) → n MagicMock columns that also act as context managers.
    def _columns(spec, **_k):
        n = spec if isinstance(spec, int) else len(spec)
        cols = []
        for _ in range(n):
            col = MagicMock()
            col.__enter__ = lambda *a, **k: st
            col.__exit__ = lambda *a, **k: False
            cols.append(col)
        return cols

    st.columns.side_effect = _columns
    st.button.return_value = False
    st.form_submit_button.return_value = False
    st.session_state = {}
    return st


def _seed_candidate_for_ad() -> tuple[int, JobAd]:
    from cv_bau_students.jobads.repo import get_ad_by_id, store_ad
    from cv_bau_students.models import CandidateProfile, TranslatedCapability

    ad_id = store_ad(
        JobAd(
            title="Datový analytik",
            employer="ApexFinance s.r.o.",
            location="Praha",
            remote_mode="hybrid",
            level="medior",
            domain="data-analyst",
            must_have=["SQL"],
            nice_to_have=["Power BI"],
            languages_required=[],
            raw_text="Hledáme analytika se znalostí SQL.",
            source="scraped",
        )
    )
    profile = CandidateProfile(
        candidate_type="student", language="cs", name="Anna", location="Praha"
    )
    cap = TranslatedCapability(
        skill="Python",
        evidence_quote="thesis",
        confidence=0.7,
        source_type="thesis",
        relevance="must_have",
    )
    cid = candidates_repo.store_initial_candidate(
        file_hash="ui-test", profile=profile, capabilities=[cap]
    )
    candidates_repo.record_interest(cid, ad_id, "interested")
    candidates_repo.ensure_role_questions(
        ad_id,
        questions_factory=lambda: [
            _Q(slot="elevator_pitch_for_role", question_text="Proč?"),
        ],
    )
    candidates_repo.store_role_answers(
        cid,
        ad_id,
        answers={"elevator_pitch_for_role": "Baví mě data."},
        prefilled_set={"elevator_pitch_for_role"},
        edited_set=set(),
    )
    candidates_repo.store_match(
        cid,
        ad_id,
        match=MatchScore(
            ad_id=ad_id,
            skill_fit=80.0,
            bridge_fit=60.0,
            personal_fit=70.0,
            total=72.0,
            confidence_band=10.0,
            bridge_plan=[GapItem(skill="Power BI", bridgeable_in_months=2)],
        ),
    )
    return ad_id, get_ad_by_id(ad_id)


class _Q:
    def __init__(self, slot, question_text, extract_hint=None):
        self.slot = slot
        self.question_text = question_text
        self.extract_hint = extract_hint


def test_recruiter_panel_renders_without_error(monkeypatch):
    ad_id, ad = _seed_candidate_for_ad()
    fake = _fake_st()
    monkeypatch.setattr(recruiter_panel, "st", fake)
    # Should walk the full path: header, stats, columns, candidate row,
    # drill-in detail, JD expander — no exceptions.
    recruiter_panel.render_recruiter_panel(ad)
    assert fake.markdown.called
    assert fake.progress.called  # at least one candidate row rendered


def test_recruiter_panel_handles_missing_ad(monkeypatch):
    fake = _fake_st()
    monkeypatch.setattr(recruiter_panel, "st", fake)
    recruiter_panel.render_recruiter_panel(None)
    fake.warning.assert_called()


def test_legacy_skill_fit_detail_still_shows_role_coverage(monkeypatch):
    """A pre-Phase-B detail (isco_code set, target_source=None) must still
    render its ESCO role coverage — not be hidden by the target_source guard."""
    from cv_bau_students.models import SkillFitDetail

    fake = _fake_st()
    monkeypatch.setattr(recruiter_panel, "st", fake)
    legacy = SkillFitDetail(
        isco_code="2511",
        occupation_label="data analyst",
        target_source=None,  # legacy row
        role_essential_total=10,
        role_essential_evidenced=3,
        role_essential_matched=["SQL"],
        bonus_applied=6.0,
    )
    recruiter_panel._render_skill_fit_detail(legacy)
    captions = " ".join(str(c.args[0]) for c in fake.caption.call_args_list if c.args)
    assert "Role coverage" in captions
    assert "ISCO 2511" in captions


def test_recruiter_detail_renders(monkeypatch):
    ad_id, ad = _seed_candidate_for_ad()
    fake = _fake_st()
    monkeypatch.setattr(recruiter_panel, "st", fake)
    summaries = candidates_repo.get_candidates_for_ad(ad_id, kind="student")
    assert summaries
    # Full drill-in render path: breakdown columns, bridge plan, role
    # answers (with audit-flag tags), capabilities, reasoning, raw JSON.
    # Asserting it completes without raising is the smoke value.
    recruiter_panel._render_detail(ad_id, summaries[0].candidate_id)
    assert fake.markdown.called
