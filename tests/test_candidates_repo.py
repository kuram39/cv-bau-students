"""Tests for `cv_bau_students.candidates.repo` — Phase 12b.

Exercises the candidate persistence + recruiter-facing read paths
against the in-memory SQLite fixture from `conftest.py`.
"""

from __future__ import annotations

from pydantic import BaseModel

from cv_bau_students.candidates import repo
from cv_bau_students.db import get_session
from cv_bau_students.db_models import (
    Candidate,
    JobAdRow,
    Match,
)
from cv_bau_students.models import (
    CandidateProfile,
    GapItem,
    MatchScore,
    TranslatedCapability,
)


def _student_profile(name: str = "Anna") -> CandidateProfile:
    return CandidateProfile(
        candidate_type="student",
        language="cs",
        name=name,
        location="Praha",
    )


def _make_ad(title: str = "Datový analytik") -> int:
    with get_session() as session:
        ad = JobAdRow(
            title=title,
            employer="Test s.r.o.",
            location="Praha",
            remote_mode="hybrid",
            level="medior",
            domain="data-analyst",
            source="scraped",
            raw_text="lorem ipsum",
        )
        session.add(ad)
        session.flush()
        return ad.id


def _make_match(ad_id: int, total: float = 70.0) -> MatchScore:
    return MatchScore(
        ad_id=ad_id,
        skill_fit=80.0,
        bridge_fit=60.0,
        personal_fit=70.0,
        total=total,
        confidence_band=10.0,
        bridge_plan=[GapItem(skill="Power BI", bridgeable_in_months=2)],
        reasoning="Solid baseline; bridges via Power BI training.",
    )


def test_store_initial_candidate_dedups_by_cv_hash():
    profile = _student_profile()
    cap = TranslatedCapability(
        skill="Python",
        evidence_quote="Python coursework",
        confidence=0.7,
        source_type="school_project",
        relevance="must_have",
    )
    cid_1 = repo.store_initial_candidate(file_hash="hash-a", profile=profile, capabilities=[cap])
    cid_2 = repo.store_initial_candidate(file_hash="hash-a", profile=profile, capabilities=[cap])
    assert cid_1 == cid_2
    with get_session() as session:
        assert session.query(Candidate).count() == 1


def test_record_interest_upserts_and_validates_status():
    profile = _student_profile()
    cid = repo.store_initial_candidate(file_hash="h1", profile=profile, capabilities=[])
    ad_id = _make_ad()

    repo.record_interest(cid, ad_id, "wait")
    repo.record_interest(cid, ad_id, "interested")  # overwrite

    with get_session() as session:
        from cv_bau_students.db_models import CandidateInterest

        rows = session.query(CandidateInterest).all()
        assert len(rows) == 1
        assert rows[0].status == "interested"

    try:
        repo.record_interest(cid, ad_id, "bogus")
    except ValueError:
        return
    raise AssertionError("expected ValueError on invalid status")


class _StubQuestion(BaseModel):
    slot: str
    question_text: str
    extract_hint: str | None = None


def test_ensure_role_questions_generates_once_and_replays():
    ad_id = _make_ad()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return [
            _StubQuestion(
                slot="elevator_pitch",
                question_text="Why this role?",
                extract_hint="summary section",
            ),
            _StubQuestion(
                slot="bi_tool_experience",
                question_text="Which BI tool?",
                extract_hint="hard skills + work descriptions",
            ),
        ]

    qs_1 = repo.ensure_role_questions(ad_id, questions_factory=factory)
    qs_2 = repo.ensure_role_questions(ad_id, questions_factory=factory)

    assert len(qs_1) == 2
    assert {q.slot for q in qs_1} == {"elevator_pitch", "bi_tool_experience"}
    assert calls["n"] == 1  # second call hit the DB cache, did not regenerate
    assert {q.id for q in qs_1} == {q.id for q in qs_2}


def test_ensure_role_questions_fairness_two_candidates_see_same_qs():
    """Invariant: same ad => identical Qs across candidates."""
    ad_id = _make_ad()

    def factory():
        return [
            _StubQuestion(slot="slot_a", question_text="Q1"),
            _StubQuestion(slot="slot_b", question_text="Q2"),
        ]

    qs_for_a = repo.ensure_role_questions(ad_id, questions_factory=factory)
    qs_for_b = repo.ensure_role_questions(ad_id, questions_factory=factory)
    assert [q.slot for q in qs_for_a] == [q.slot for q in qs_for_b]


def test_store_role_answers_tracks_prefilled_and_edited():
    profile = _student_profile()
    cid = repo.store_initial_candidate(file_hash="h2", profile=profile, capabilities=[])
    ad_id = _make_ad()
    repo.ensure_role_questions(
        ad_id,
        questions_factory=lambda: [
            _StubQuestion(slot="elevator_pitch", question_text="Why?"),
            _StubQuestion(slot="bi_tool", question_text="Which BI?"),
            _StubQuestion(slot="long_term", question_text="Long-term?"),
        ],
    )

    answers = {
        "elevator_pitch": "I'm enthusiastic about data.",
        "bi_tool": "Power BI",
        "long_term": "Grow into a senior analyst role.",
    }
    repo.store_role_answers(
        cid,
        ad_id,
        answers=answers,
        prefilled_set={"elevator_pitch", "bi_tool"},
        edited_set={"elevator_pitch"},
    )

    with get_session() as session:
        from cv_bau_students.db_models import RoleSpecificAnswer

        rows = session.query(RoleSpecificAnswer).filter_by(candidate_id=cid, ad_id=ad_id).all()
        by_slot = {r.slot: r for r in rows}
    assert by_slot["elevator_pitch"].was_prefilled is True
    assert by_slot["elevator_pitch"].was_edited is True
    assert by_slot["bi_tool"].was_prefilled is True
    assert by_slot["bi_tool"].was_edited is False
    assert by_slot["long_term"].was_prefilled is False
    assert by_slot["long_term"].was_edited is False


def test_store_match_upserts():
    profile = _student_profile()
    cid = repo.store_initial_candidate(file_hash="h3", profile=profile, capabilities=[])
    ad_id = _make_ad()
    repo.store_match(cid, ad_id, match=_make_match(ad_id, total=60.0))
    repo.store_match(cid, ad_id, match=_make_match(ad_id, total=82.0))
    with get_session() as session:
        rows = session.query(Match).filter_by(candidate_id=cid, ad_id=ad_id).all()
        assert len(rows) == 1
        assert rows[0].total == 82.0


def test_get_candidates_for_ad_only_returns_interested_with_match():
    ad_id = _make_ad()

    # candidate 1: interested + match -> SHOULD appear
    cid_1 = repo.store_initial_candidate(
        file_hash="h-int", profile=_student_profile("Anna"), capabilities=[]
    )
    repo.record_interest(cid_1, ad_id, "interested")
    repo.store_match(cid_1, ad_id, match=_make_match(ad_id, total=75.0))

    # candidate 2: waited (no match yet) -> SHOULD NOT appear
    cid_2 = repo.store_initial_candidate(
        file_hash="h-wait", profile=_student_profile("Tereza"), capabilities=[]
    )
    repo.record_interest(cid_2, ad_id, "wait")

    # candidate 3: interested but no match row -> SHOULD NOT appear
    cid_3 = repo.store_initial_candidate(
        file_hash="h-no-match", profile=_student_profile("Jakub"), capabilities=[]
    )
    repo.record_interest(cid_3, ad_id, "interested")

    rows = repo.get_candidates_for_ad(ad_id)
    assert len(rows) == 1
    assert rows[0].candidate_id == cid_1
    assert rows[0].display_name == "Anna"


def test_get_candidates_for_ad_filters_by_kind():
    ad_id = _make_ad()
    cid_stud = repo.store_initial_candidate(
        file_hash="h-stud", profile=_student_profile("Anna"), capabilities=[]
    )
    cid_exp = repo.store_initial_candidate(
        file_hash="h-exp",
        profile=CandidateProfile(
            candidate_type="experienced", language="cs", name="Petr", location="Brno"
        ),
        capabilities=[],
    )
    repo.record_interest(cid_stud, ad_id, "interested")
    repo.record_interest(cid_exp, ad_id, "interested")
    repo.store_match(cid_stud, ad_id, match=_make_match(ad_id, total=70.0))
    repo.store_match(cid_exp, ad_id, match=_make_match(ad_id, total=90.0))

    students = repo.get_candidates_for_ad(ad_id, kind="student")
    experienced = repo.get_candidates_for_ad(ad_id, kind="experienced")
    assert [s.candidate_id for s in students] == [cid_stud]
    assert [s.candidate_id for s in experienced] == [cid_exp]


def test_get_candidates_for_ad_orders_by_total_desc():
    ad_id = _make_ad()
    ids = []
    for label, total in [("low", 55.0), ("high", 88.0), ("mid", 71.0)]:
        cid = repo.store_initial_candidate(
            file_hash=f"h-{label}",
            profile=_student_profile(label.capitalize()),
            capabilities=[],
        )
        repo.record_interest(cid, ad_id, "interested")
        repo.store_match(cid, ad_id, match=_make_match(ad_id, total=total))
        ids.append((label, cid))
    by_label = dict(ids)
    sorted_rows = repo.get_candidates_for_ad(ad_id)
    assert [r.candidate_id for r in sorted_rows] == [
        by_label["high"],
        by_label["mid"],
        by_label["low"],
    ]


def test_get_candidate_detail_joins_role_answers_with_audit_flags():
    profile = _student_profile()
    cap = TranslatedCapability(
        skill="Python",
        evidence_quote="thesis on regression",
        confidence=0.7,
        source_type="thesis",
        relevance="must_have",
    )
    cid = repo.store_initial_candidate(file_hash="h-detail", profile=profile, capabilities=[cap])
    ad_id = _make_ad()
    repo.record_interest(cid, ad_id, "interested")
    repo.ensure_role_questions(
        ad_id,
        questions_factory=lambda: [
            _StubQuestion(slot="why_role", question_text="Why this?"),
        ],
    )
    repo.store_role_answers(
        cid,
        ad_id,
        answers={"why_role": "I love data and would grow fast."},
        prefilled_set={"why_role"},
        edited_set=set(),
    )
    repo.store_match(cid, ad_id, match=_make_match(ad_id, total=72.0))

    detail = repo.get_candidate_detail(cid, ad_id)
    assert detail is not None
    assert detail.candidate_id == cid
    assert detail.kind == "student"
    assert detail.match.total == 72.0
    assert len(detail.capabilities) == 1
    assert detail.capabilities[0].skill == "Python"
    assert len(detail.role_answers) == 1
    answer = detail.role_answers[0]
    assert answer.slot == "why_role"
    assert answer.was_prefilled is True
    assert answer.was_edited is False


def test_stats_for_ad_aggregates():
    ad_id = _make_ad()

    def _add(file_hash: str, kind: str, name: str, total: float):
        profile = CandidateProfile(candidate_type=kind, language="cs", name=name, location="Praha")
        cid = repo.store_initial_candidate(file_hash=file_hash, profile=profile, capabilities=[])
        repo.record_interest(cid, ad_id, "interested")
        repo.store_match(cid, ad_id, match=_make_match(ad_id, total=total))

    _add("s1", "student", "A", 60.0)
    _add("s2", "student", "B", 70.0)
    _add("x1", "experienced", "C", 80.0)
    _add("x2", "experienced", "D", 90.0)

    s = repo.stats_for_ad(ad_id)
    assert s["total"] == 4
    assert s["students"] == 2
    assert s["experienced"] == 2
    assert s["avg_student_total"] == 65.0
    assert s["avg_experienced_total"] == 85.0
