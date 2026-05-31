"""Tests for `scripts.load_esco_occupation_labels`.

Builds tiny en + cs occupations CSVs, runs the loader, and checks the
`occupations` table is populated (per language) with split altLabels and
dedupes on re-run.
"""

from __future__ import annotations

import csv
from pathlib import Path

from scripts.load_esco_csv import DEFAULT_CS_SUBDIR, DEFAULT_EN_SUBDIR
from scripts.load_esco_occupation_labels import load_occupation_labels

from cv_bau_students.db import get_session
from cv_bau_students.db_models import Occupation

HEADER = [
    "conceptType",
    "conceptUri",
    "iscoGroup",
    "preferredLabel",
    "altLabels",
    "hiddenLabels",
    "status",
    "modifiedDate",
    "regulatedProfessionNote",
    "scopeNote",
    "definition",
    "inScheme",
    "description",
    "code",
    "naceCode",
]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in HEADER})


def _make_raw(tmp_path: Path) -> Path:
    _write(
        tmp_path / DEFAULT_EN_SUBDIR / "occupations_en.csv",
        [
            {
                "conceptUri": "uri:da",
                "iscoGroup": "2511",
                "preferredLabel": "data analyst",
                "altLabels": "business data analyst\ndata warehouse analyst",
            }
        ],
    )
    _write(
        tmp_path / DEFAULT_CS_SUBDIR / "occupations_cs.csv",
        [
            {
                "conceptUri": "uri:da",
                "iscoGroup": "2511",
                "preferredLabel": "analytik dat",
                "altLabels": "datový analytik",
            }
        ],
    )
    return tmp_path


def test_loads_en_and_cs_with_split_alt_labels(tmp_path):
    counts = load_occupation_labels(_make_raw(tmp_path), verbose=False)
    assert counts == {"en": 1, "cs": 1}
    with get_session() as session:
        rows = session.query(Occupation).all()
        by_lang = {r.lang: r for r in rows}
    assert by_lang["en"].preferred_label == "data analyst"
    assert by_lang["en"].alt_labels == ["business data analyst", "data warehouse analyst"]
    assert by_lang["cs"].alt_labels == ["datový analytik"]
    assert {r.isco_code for r in rows} == {"2511"}


def test_idempotent_on_rerun(tmp_path):
    raw = _make_raw(tmp_path)
    load_occupation_labels(raw, verbose=False)
    load_occupation_labels(raw, verbose=False)
    with get_session() as session:
        assert session.query(Occupation).count() == 2  # one en + one cs, no dupes
