"""matcher.score.counterfactual_lifts — deterministic actionable recourse.

Pure arithmetic from SkillFitDetail counts; no DB, no LLM.
"""

from __future__ import annotations

from cv_bau_students.matcher.score import bridge_estimate, counterfactual_lifts
from cv_bau_students.models import GapItem, SkillFitDetail


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


def test_bridge_estimate_sums_months_and_flags_experience_walls():
    gaps = [
        GapItem(skill="Power BI", bridgeable_in_months=2),
        GapItem(skill="advanced SQL", bridgeable_in_months=6),
        GapItem(skill="team leadership", bridgeable_in_months=None),  # experience-only wall
    ]
    e = bridge_estimate(gaps)
    assert e["months"] == 8  # 2 + 6 (None excluded)
    assert e["bridgeable"] == 2
    assert e["experience_only"] == 1
    assert e["gaps"] == 3


def test_bridge_estimate_empty_is_ready_now():
    e = bridge_estimate([])
    assert e == {"months": 0, "bridgeable": 0, "experience_only": 0, "gaps": 0}


def test_bridge_estimate_all_experience_only():
    gaps = [GapItem(skill="5y stakeholder mgmt", bridgeable_in_months=None)]
    e = bridge_estimate(gaps)
    assert e["months"] == 0 and e["bridgeable"] == 0 and e["experience_only"] == 1
