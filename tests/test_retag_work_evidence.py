"""scripts.retag_work_evidence — deterministic other→work backfill."""

from __future__ import annotations

from datetime import datetime

from scripts.retag_work_evidence import _work_descriptions, retag
from sqlalchemy import select

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Candidate, ProfileVersion, TranslatedCapabilityRow


def test_work_descriptions_excludes_brigada():
    profile = {
        "work_experience": [
            {"description": "Vedl analytický tým, psal SQL dotazy.", "is_brigada": False},
            {"description": "Pokladna McDonald's.", "is_brigada": True},
            {"description": None, "is_brigada": False},
        ]
    }
    descs = _work_descriptions(profile)
    assert descs == ["vedl analytický tým, psal sql dotazy."]


def _cap(cid, quote, src="other"):
    return TranslatedCapabilityRow(
        candidate_id=cid,
        skill_canonical=quote[:20],
        evidence_quote=quote,
        confidence=0.6,
        source_type=src,
        relevance="direct",
        created_at=datetime(2026, 1, 1),
    )


def test_retag_promotes_only_work_evidenced():
    with get_session() as s:
        c = Candidate(
            cv_hash="h1", language="cs", type="experienced", created_at=datetime(2026, 1, 1)
        )
        s.add(c)
        s.flush()
        cid = c.id
        s.add(
            ProfileVersion(
                candidate_id=cid,
                round=0,
                profile_json={
                    "work_experience": [
                        {
                            "description": "Psal SQL dotazy a stavěl dashboardy.",
                            "is_brigada": False,
                        },
                        {"description": "Brigáda v kavárně, obsluha.", "is_brigada": True},
                    ],
                    "summary": "Hledám roli datového analytika.",
                },
                created_at=datetime(2026, 1, 1),
            )
        )
        s.add(_cap(cid, "Psal SQL dotazy a stavěl dashboardy."))  # in work → work
        s.add(_cap(cid, "Brigáda v kavárně, obsluha."))  # in brigáda → stays other
        s.add(_cap(cid, "Hledám roli datového analytika."))  # summary claim → stays other

    n = retag()
    assert n == 1

    with get_session() as s:
        rows = {
            r.evidence_quote: r.source_type
            for r in s.execute(select(TranslatedCapabilityRow)).scalars().all()
        }
    assert rows["Psal SQL dotazy a stavěl dashboardy."] == "work"
    assert rows["Brigáda v kavárně, obsluha."] == "other"
    assert rows["Hledám roli datového analytika."] == "other"
