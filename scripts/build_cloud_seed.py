#!/usr/bin/env python3
"""Build a gzipped SQLite seed file for Streamlit Cloud cold-start parity.

Pipeline: live local SQLite → VACUUM INTO clean snapshot → gzip →
`src/cv_bau_students/data/seed.sqlite.gz` (committed to git, shipped
via package-data).

On Cloud cold start, bootstrap.py gunzips the seed and copies it to
the runtime DB path. This gives Cloud the same 14k ESCO skills + 19k
hierarchy edges + 70k occupation-skill rows that local dev has — no
30-min API fetch, no collection filter, full universal coverage.

Run AFTER full local ingest:
    python -m scripts.load_seeds                # manual seed
    python -m scripts.load_esco_csv --raw-dir data/raw_esco
    python -m scripts.load_esco_hierarchy
    python -m scripts.load_esco_occupations
    python -m scripts.load_nsp --source data/raw_nsp/competencies_seed.json
    python -m scripts.build_cloud_seed          # then this

Output: src/cv_bau_students/data/seed.sqlite.gz (~10-15 MB).
Re-run after any ESCO version bump.

License of bundled data: ESCO is CC BY 4.0 — see NOTICES.md.
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from cv_bau_students.config import DB_URL

# Default output is inside the package so MANIFEST.in / package-data
# ships it on pip install.
DEFAULT_OUT = Path("src/cv_bau_students/data/seed.sqlite.gz")


def _sqlite_path_from_url(url: str) -> Path:
    """Extract the file path from a `sqlite:///./data/foo.sqlite` URL."""
    if not url.startswith("sqlite:///"):
        raise ValueError(f"Not a SQLite URL: {url!r}")
    return Path(url.removeprefix("sqlite:///")).resolve()


def build_seed(out_path: Path, *, verbose: bool = True) -> dict[str, int]:
    """VACUUM INTO a clean snapshot, then gzip.

    Returns counts: {"raw_bytes": N, "gz_bytes": M}.
    """
    db_path = _sqlite_path_from_url(DB_URL)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Live SQLite missing at {db_path}. "
            f"Run the load scripts first (see this file's module docstring)."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cloud_seed_") as tmpdir:
        clean_path = Path(tmpdir) / "seed.sqlite"
        if verbose:
            print(f"  VACUUM INTO {clean_path} (from {db_path})...")
        # VACUUM INTO produces a defragmented copy without WAL/journal noise.
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("VACUUM INTO ?", (str(clean_path),))
        raw_bytes = clean_path.stat().st_size

        if verbose:
            print(f"  gzip → {out_path}...")
        with clean_path.open("rb") as fin, gzip.open(out_path, "wb", compresslevel=9) as fout:
            shutil.copyfileobj(fin, fout)
        gz_bytes = out_path.stat().st_size

    if verbose:
        print(
            f"\nDone. Raw {raw_bytes / 1024 / 1024:.1f} MB → "
            f"gzipped {gz_bytes / 1024 / 1024:.1f} MB ({gz_bytes / raw_bytes:.1%})."
        )

    # Smoke: verify the gz file rehydrates correctly.
    with tempfile.TemporaryDirectory(prefix="cloud_seed_verify_") as tmpdir:
        check_path = Path(tmpdir) / "rehydrated.sqlite"
        with gzip.open(out_path, "rb") as fin, check_path.open("wb") as fout:
            shutil.copyfileobj(fin, fout)
        with sqlite3.connect(str(check_path)) as conn:
            n_skills = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            n_aliases = conn.execute("SELECT COUNT(*) FROM skill_aliases").fetchone()[0]
            n_hier = conn.execute("SELECT COUNT(*) FROM skill_hierarchy").fetchone()[0]
            n_industry = conn.execute("SELECT COUNT(*) FROM skill_industry_map").fetchone()[0]
        if verbose:
            print(
                f"  rehydrate check: {n_skills} skills, {n_aliases} aliases, "
                f"{n_hier} hierarchy, {n_industry} industry-map."
            )

    return {"raw_bytes": raw_bytes, "gz_bytes": gz_bytes}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Cloud seed.sqlite.gz.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    try:
        counts = build_seed(args.out)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Wrote {args.out} ({counts['gz_bytes'] / 1024 / 1024:.1f} MB gzipped).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
