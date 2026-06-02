"""matcher.score.counterfactual_lifts — deterministic actionable recourse.

Pure arithmetic from SkillFitDetail counts; no DB, no LLM.
"""

from __future__ import annotations

from cv_bau_students.matcher.score import counterfactual_lifts
from cv_bau_students.models import SkillFitDetail


def _detail(total, evidenced, missing):
    return SkillFitDetail(
        role_essential_total=total,
        role_essential_evidenced=evidenced,
        role_essential_missing=missing,
    )


def test_none_and_empty_return_empty():
    assert counterfactual_lifts(None) == []
    assert counterfactual_lifts(_detail(0, 0, [])) == []


def test_full_coverage_has_no_recourse():
    assert counterfactual_lifts(_detail(5, 5, [])) == []


def test_lift_math_and_pairing():
    # 3/10 = 30 %; demonstrating one more → 4/10 = 40 %.
    lifts = counterfactual_lifts(_detail(10, 3, ["Power BI", "ETL"]))
    assert lifts == [("Power BI", 30, 40), ("ETL", 30, 40)]


def test_cap_limits_output():
    missing = [f"skill{i}" for i in range(9)]
    lifts = counterfactual_lifts(_detail(12, 1, missing), cap=3)
    assert len(lifts) == 3
    assert all(cur == 8 and new == 17 for _name, cur, new in lifts)  # 1/12=8.3→8, 2/12=16.7→17
