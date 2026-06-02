#!/usr/bin/env python3
"""A/B the profile extractor across two models (Sonnet vs Haiku).

Research #7 RANK 1 routes the mechanical calls to Haiku 4.5 (3× cheaper) behind
`CV_BAU_STUDENTS_TIER`. Before flipping that on, validate Haiku doesn't degrade
extraction on the committed CVs — ESPECIALLY the Czech ones (Czech skill
extraction is the pipeline's weak spot). This runs the SAME extract prompt
through both models and diffs the skills they pull, so the quality delta is
concrete, not assumed.

NEEDS A LIVE KEY (owner runs — the agent's subprocess has no ANTHROPIC_API_KEY).
Pure read otherwise; writes nothing to the DB.

Usage:
    ./venv/bin/python -m scripts.ab_extract                       # all committed CVs
    ./venv/bin/python -m scripts.ab_extract --dir data/raw_cv_samples/students
    ./venv/bin/python -m scripts.ab_extract --baseline claude-sonnet-4-6 \
                                            --candidate claude-haiku-4-5
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from cv_bau_students import config, llm


def _skill_set(profile: dict) -> set[str]:
    """Union of the skill-ish fields, lowercased + stripped — the comparison key."""
    out: set[str] = set()
    for field in ("hard_skills", "soft_skills", "explicit_skills"):
        for s in profile.get(field) or []:
            if isinstance(s, str) and s.strip():
                out.add(s.strip().lower())
    return out


def compare_profiles(baseline: dict, candidate: dict) -> dict:
    """Set-level diff of two extracted profiles. Pure — unit-testable offline."""
    a, b = _skill_set(baseline), _skill_set(candidate)
    union = a | b
    inter = a & b
    jaccard = round(len(inter) / len(union), 3) if union else 1.0
    return {
        "baseline_n": len(a),
        "candidate_n": len(b),
        "shared": len(inter),
        "jaccard": jaccard,
        "only_baseline": sorted(a - b),
        "only_candidate": sorted(b - a),
    }


def _extract_with(cv_text: str, model: str, current_year: int) -> dict:
    prompt = llm.render_prompt("extract_profile", cv_text=cv_text, current_year=current_year)
    return llm.call_json(prompt, model=model)


def _cv_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.txt"))


def main() -> int:
    p = argparse.ArgumentParser(description="A/B the extractor across two models.")
    p.add_argument("--dir", default="data/raw_cv_samples", help="Directory of .txt CVs.")
    p.add_argument("--baseline", default=config.LLM_MODEL, help="Reference model.")
    p.add_argument("--candidate", default=config.LLM_MODEL_CHEAP, help="Cheaper model to test.")
    args = p.parse_args()

    files = _cv_files(Path(args.dir))
    if not files:
        print(f"No .txt CVs under {args.dir}.")
        return 1
    current_year = date.today().year
    print(f"Baseline:  {args.baseline}\nCandidate: {args.candidate}\n")

    jaccards: list[float] = []
    for f in files:
        cv_text = f.read_text(encoding="utf-8")
        base = _extract_with(cv_text, args.baseline, current_year)
        cand = _extract_with(cv_text, args.candidate, current_year)
        d = compare_profiles(base, cand)
        jaccards.append(d["jaccard"])
        print(f"── {f.name}")
        print(
            f"   skills  baseline={d['baseline_n']}  candidate={d['candidate_n']}  "
            f"shared={d['shared']}  jaccard={d['jaccard']}"
        )
        if d["only_baseline"]:
            print(f"   only baseline:  {', '.join(d['only_baseline'])}")
        if d["only_candidate"]:
            print(f"   only candidate: {', '.join(d['only_candidate'])}")

    mean = round(sum(jaccards) / len(jaccards), 3) if jaccards else 0.0
    print(f"\nMean Jaccard over {len(files)} CVs: {mean}")
    print(
        "Rule of thumb: ≥0.85 = safe to enable Haiku; lower = inspect the diffs "
        "(esp. Czech CVs) before CV_BAU_STUDENTS_TIER=1."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
