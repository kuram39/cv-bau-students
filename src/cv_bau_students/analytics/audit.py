"""Bias-audit DISCLOSURE over the recruiter's scored candidates.

Research #8: regulators (NYC LL144, and the direction of EU AI Act audits) expect
selection-rate metrics across groups. Here the "groups" are the candidate types
the product already tags (student / career_changer / experienced) — the demo
deliberately collects NO protected attributes (race/gender/age), so this is an
input-fairness *disclosure metric*, NOT a pass/fail bar and NOT a true adverse-
impact audit. Computes per-type mean coverage + selection rate at a threshold and
the EEOC four-fifths ratio, reading existing Match rows only (no pipeline, no LLM).

The point is auditability-by-design: the artifact every HR-tech buyer eventually
asks for becomes a one-call query instead of a retrofit. Limits are documented in
docs/MODEL_CARD.md.
"""

from __future__ import annotations

import math

from cv_bau_students.candidates.repo import get_candidates_for_ad

# The candidate types we report on, in display order.
GROUPS = ("student", "career_changer", "experienced")
DEFAULT_THRESHOLD = 50.0


def audit_by_type(ad_id: int, *, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Selection-rate disclosure across candidate types for one ad.

    "Selected" = total score ≥ ``threshold``. Returns per-group counts, mean
    coverage and selection rate, plus the four-fifths ratio (lowest non-empty
    group's rate ÷ highest). ``adverse_impact`` flags ratio < 0.80 — surfaced as
    a *prompt to review*, never an automated action.
    """
    summaries = get_candidates_for_ad(ad_id)
    groups: dict[str, dict] = {}
    for g in GROUPS:
        members = [s for s in summaries if s.kind == g]
        n = len(members)
        selected = sum(1 for s in members if s.total >= threshold)
        groups[g] = {
            "n": n,
            "selected": selected,
            "selection_rate": round(selected / n, 3) if n else None,
            "mean_coverage": round(sum(s.total for s in members) / n, 1) if n else None,
        }

    # Compute the four-fifths ratio from UNROUNDED selected/n — comparing the
    # rounded display rates could flag (or clear) a near-0.80 case incorrectly.
    raw_rates = [g["selected"] / g["n"] for g in groups.values() if g["n"]]
    max_rate = max(raw_rates) if raw_rates else 0.0
    if len(raw_rates) >= 2 and max_rate > 0:
        ratio = min(raw_rates) / max_rate
        four_fifths = round(ratio, 3)
        # Exactly-0.80 is the boundary (the rule flags BELOW four-fifths); treat
        # it as compliant, and use isclose so a float artifact like
        # (4/9)/(5/9) = 0.7999999999999999 doesn't trip a false adverse flag.
        adverse = ratio < 0.80 and not math.isclose(ratio, 0.80, rel_tol=1e-9)
    else:
        # <2 non-empty groups, or every rate 0 → ratio undefined (not enough data).
        four_fifths = None
        adverse = False

    return {
        "ad_id": ad_id,
        "threshold": threshold,
        "total": len(summaries),
        "groups": groups,
        "four_fifths_ratio": four_fifths,
        "adverse_impact": adverse,
    }


def audit_csv(report: dict) -> str:
    """Flatten an ``audit_by_type`` report to CSV text (for st.download_button)."""
    lines = ["candidate_type,n,selected,selection_rate,mean_coverage"]
    for g, row in report["groups"].items():
        lines.append(
            f"{g},{row['n']},{row['selected']},"
            f"{row['selection_rate'] if row['selection_rate'] is not None else ''},"
            f"{row['mean_coverage'] if row['mean_coverage'] is not None else ''}"
        )
    ratio = report["four_fifths_ratio"]
    lines.append("")
    lines.append(f"threshold,{report['threshold']}")
    lines.append(f"four_fifths_ratio,{ratio if ratio is not None else ''}")
    lines.append(f"adverse_impact,{report['adverse_impact']}")
    return "\n".join(lines) + "\n"
