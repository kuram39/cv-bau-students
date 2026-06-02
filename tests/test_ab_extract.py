"""scripts.ab_extract.compare_profiles — offline set-diff math (no key)."""

from __future__ import annotations

from scripts.ab_extract import compare_profiles


def test_identical_profiles_jaccard_one():
    prof = {"hard_skills": ["SQL", "Python"], "soft_skills": ["communication"]}
    d = compare_profiles(prof, prof)
    assert d["jaccard"] == 1.0
    assert d["shared"] == 3
    assert d["only_baseline"] == [] and d["only_candidate"] == []


def test_partial_overlap_and_case_insensitive():
    base = {"hard_skills": ["SQL", "Python"], "explicit_skills": ["Excel"]}
    cand = {"hard_skills": ["sql", "Power BI"], "soft_skills": []}
    d = compare_profiles(base, cand)
    # base={sql,python,excel}, cand={sql,power bi}; ∩={sql}, ∪=4 → 0.25
    assert d["baseline_n"] == 3
    assert d["candidate_n"] == 2
    assert d["shared"] == 1
    assert d["jaccard"] == 0.25
    assert d["only_baseline"] == ["excel", "python"]
    assert d["only_candidate"] == ["power bi"]


def test_empty_both_is_jaccard_one():
    assert compare_profiles({}, {})["jaccard"] == 1.0
