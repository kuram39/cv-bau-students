"""Tests for the Cloud-parity seed.sqlite.gz pipeline.

`scripts.build_cloud_seed` produces a gzipped SQLite snapshot of the
live DB. `cv_bau_students.bootstrap._restore_from_seed_snapshot`
gunzips it onto a fresh runtime DB on Cloud cold start. These tests
exercise both halves end-to-end with tiny fixtures.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

from cv_bau_students.db import get_session, init_db, reset_engine_for_tests
from cv_bau_students.db_models import Skill


def _build_tiny_seed_gz(out_path: Path, *, n_skills: int = 3) -> Path:
    """Create a minimal seed.sqlite.gz with full Skill schema + N rows."""
    raw = out_path.parent / "raw_for_seed.sqlite"
    # Build the schema via the ORM so all columns match — direct
    # `CREATE TABLE skills (id, canonical_name)` would miss the
    # canonical_name_en / esco_uri / skill_type / nsp_code / family
    # columns the live model expects.
    reset_engine_for_tests(f"sqlite:///{raw}")
    init_db()
    with get_session() as s:
        for i in range(n_skills):
            s.add(Skill(canonical_name=f"seeded_skill_{i}"))
    # Close the engine so the file isn't locked, then gzip it.
    reset_engine_for_tests("sqlite:///:memory:")
    with raw.open("rb") as fin, gzip.open(out_path, "wb") as fout:
        shutil.copyfileobj(fin, fout)
    raw.unlink()
    return out_path


def test_restore_from_seed_copies_gzipped_snapshot_to_runtime(tmp_path):
    """Bootstrap's `_restore_from_seed_snapshot` rehydrates a fresh DB."""
    runtime_db = tmp_path / "runtime.sqlite"
    seed_gz = tmp_path / "seed.sqlite.gz"
    _build_tiny_seed_gz(seed_gz, n_skills=3)

    # Point engine at a non-existent runtime path, patch SEED_SQLITE_GZ.
    reset_engine_for_tests(f"sqlite:///{runtime_db}")
    from cv_bau_students import bootstrap

    with patch.object(bootstrap, "SEED_SQLITE_GZ", seed_gz):
        restored = bootstrap._restore_from_seed_snapshot()
    assert restored is True
    assert runtime_db.exists()

    # Re-point engine at the restored DB and query it.
    reset_engine_for_tests(f"sqlite:///{runtime_db}")
    init_db()
    with get_session() as s:
        names = [row.canonical_name for row in s.query(Skill).all()]
    assert {"seeded_skill_0", "seeded_skill_1", "seeded_skill_2"}.issubset(names)


def test_restore_skips_when_seed_missing(tmp_path):
    """No seed.sqlite.gz → restore returns False without touching runtime."""
    runtime_db = tmp_path / "runtime.sqlite"
    reset_engine_for_tests(f"sqlite:///{runtime_db}")
    from cv_bau_students import bootstrap

    with patch.object(bootstrap, "SEED_SQLITE_GZ", tmp_path / "nonexistent.gz"):
        restored = bootstrap._restore_from_seed_snapshot()
    assert restored is False


def test_restore_skips_when_runtime_already_populated(tmp_path):
    """Existing runtime DB with content > 64KB is left alone."""
    runtime_db = tmp_path / "runtime.sqlite"
    # Build a fake "existing" DB larger than the 64 KB threshold.
    with sqlite3.connect(str(runtime_db)) as conn:
        conn.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY, blob BLOB)")
        # Pad to >64 KB so it looks like a real DB.
        conn.execute("INSERT INTO marker (blob) VALUES (?)", (b"x" * 80_000,))
    pre_size = runtime_db.stat().st_size
    assert pre_size > 64_000

    seed_gz = tmp_path / "seed.sqlite.gz"
    _build_tiny_seed_gz(seed_gz, n_skills=5)

    reset_engine_for_tests(f"sqlite:///{runtime_db}")
    from cv_bau_students import bootstrap

    with patch.object(bootstrap, "SEED_SQLITE_GZ", seed_gz):
        restored = bootstrap._restore_from_seed_snapshot()
    assert restored is False
    # Runtime DB still has the original marker table, not the seed's skills.
    with sqlite3.connect(str(runtime_db)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "marker" in tables


def test_build_cloud_seed_roundtrips(tmp_path):
    """End-to-end: live → VACUUM INTO → gzip → ungzip → query."""
    # Use the autouse in-memory engine via reset_engine_for_tests to a
    # tmp file (so VACUUM INTO has a real file to read from).
    live_db = tmp_path / "live.sqlite"
    reset_engine_for_tests(f"sqlite:///{live_db}")
    init_db()
    with get_session() as s:
        s.add(Skill(canonical_name="roundtrip-marker"))

    # Patch DB_URL inside the build script to point at our tmp live DB.
    seed_out = tmp_path / "seed.sqlite.gz"
    from scripts import build_cloud_seed

    with patch.object(build_cloud_seed, "DB_URL", f"sqlite:///{live_db}"):
        counts = build_cloud_seed.build_seed(seed_out, verbose=False)
    assert seed_out.exists()
    assert counts["gz_bytes"] < counts["raw_bytes"]

    # Rehydrate the gz into another file and query for the marker row.
    rehy_path = tmp_path / "rehydrated.sqlite"
    with gzip.open(seed_out, "rb") as fin, rehy_path.open("wb") as fout:
        shutil.copyfileobj(fin, fout)
    with sqlite3.connect(str(rehy_path)) as conn:
        rows = conn.execute("SELECT canonical_name FROM skills").fetchall()
    assert ("roundtrip-marker",) in rows
