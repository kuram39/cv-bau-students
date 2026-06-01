"""Boot-time bootstrap helpers.

Streamlit Cloud spawns a fresh container per deploy — the SQLite DB
ships empty. These helpers detect an empty taxonomy and seed it from:

  1. **`seed.sqlite.gz`** (preferred) — the ESCO + NSP snapshot built
     by `scripts/build_cloud_seed.py` and shipped via package-data.
     Gunzipped + copied to the runtime DB path in ~2 s.
  2. **CSV fallback** — when the seed is missing (dev with no build,
     legacy deploy), the slow CSV path takes over.

After taxonomy is in place we run the manual seed loader to overlay
the hand-edited `level_checklists.csv` and `taxonomy_seed.csv`. Those
are deliberately kept hand-editable for the bridge-plan rubric — the
seed snapshot doesn't own them.

Idempotent: re-running is a single `SELECT COUNT(*)` query when state
already exists.

Also exports `prewarm_llm()` so the first user analysis doesn't pay
the 60-second Anthropic SDK cold-import penalty.
"""

from __future__ import annotations

import gzip
import logging
import shutil
import threading
from pathlib import Path

from sqlalchemy import select

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, SCRAPED_ADS_DIR, TAXONOMY_SEED_CSV
from cv_bau_students.db import _engine, get_session, init_db
from cv_bau_students.db_models import JobAdRow, Occupation, Skill

log = logging.getLogger(__name__)

# Where the gzipped Cloud seed lives inside the package. MANIFEST.in
# ships it via setuptools package-data.
_PACKAGE_ROOT = Path(__file__).resolve().parent
SEED_SQLITE_GZ = _PACKAGE_ROOT / "data" / "seed.sqlite.gz"


def is_seeded() -> bool:
    """True when the taxonomy + at least one job ad already exist."""
    with get_session() as session:
        has_skills = session.execute(select(Skill).limit(1)).first() is not None
        has_ads = session.execute(select(JobAdRow).limit(1)).first() is not None
    return has_skills and has_ads


def _restore_from_seed_snapshot() -> bool:
    """If seed.sqlite.gz is present, gunzip it to the runtime DB path.

    Only fires when the runtime DB doesn't already exist or is empty.
    Returns True if the seed was restored, False otherwise.
    """
    if not SEED_SQLITE_GZ.exists():
        log.info("No seed.sqlite.gz at %s — falling back to CSV path.", SEED_SQLITE_GZ)
        return False

    # Get the runtime SQLite file path from the engine URL.
    engine = _engine()
    url = str(engine.url)
    if "sqlite" not in url:
        log.info("DB is not SQLite (%s) — skipping seed restore.", url)
        return False
    # Strip sqlite:/// prefix; engine.url.database is the cleaner accessor.
    runtime_db = engine.url.database
    if runtime_db is None or runtime_db == ":memory:":
        log.info("Runtime DB is in-memory — skipping seed restore.")
        return False
    runtime_path = Path(runtime_db).resolve()

    # If runtime DB exists and is non-trivial, don't overwrite.
    if runtime_path.exists() and runtime_path.stat().st_size > 64 * 1024:
        return False

    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Restoring seed snapshot: %s → %s", SEED_SQLITE_GZ, runtime_path)
    # Drop the existing engine so SQLAlchemy releases the file handle.
    engine.dispose()
    with gzip.open(SEED_SQLITE_GZ, "rb") as fin, runtime_path.open("wb") as fout:
        shutil.copyfileobj(fin, fout)
    # Force a new engine on next get_session() call.
    _engine.cache_clear()
    return True


def _backfill_occupations() -> None:
    """Copy ESCO occupation labels from the bundled seed into an already-
    seeded DB that predates the `occupations` table.

    Without this, an in-place upgraded DB (skills + ads present, so
    `is_seeded()` is True and no snapshot restore happens) keeps an empty
    `occupations` table and `resolve_isco_for_ad` returns unresolved for
    every ad. No-op when the table is already populated, the snapshot is
    missing, or the DB is in-memory.
    """
    if not SEED_SQLITE_GZ.exists():
        return
    try:
        with get_session() as session:
            if session.execute(select(Occupation).limit(1)).first() is not None:
                return  # already populated
        engine = _engine()
        if engine.url.database in (None, ":memory:"):
            return

        import tempfile

        from sqlalchemy import text

        tmp = Path(tempfile.mktemp(suffix=".sqlite"))
        with gzip.open(SEED_SQLITE_GZ, "rb") as fin, tmp.open("wb") as fout:
            shutil.copyfileobj(fin, fout)
        try:
            with engine.begin() as conn:
                conn.execute(text("ATTACH DATABASE :p AS seed"), {"p": str(tmp)})
                has_table = conn.execute(
                    text(
                        "SELECT name FROM seed.sqlite_master "
                        "WHERE type='table' AND name='occupations'"
                    )
                ).first()
                if has_table:
                    conn.execute(text("INSERT INTO occupations SELECT * FROM seed.occupations"))
                conn.execute(text("DETACH DATABASE seed"))
            if has_table:
                log.info("Backfilled occupation labels from seed snapshot.")
        finally:
            tmp.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        log.exception("Bootstrap: occupation backfill failed.")


def ensure_seeded() -> None:
    """Restore from seed snapshot if available, then overlay hand-edited bits.

    Catches errors per-step so a single failure surfaces in logs but
    does not crash the Streamlit app — the recruiter sees an empty
    state instead of a stack trace.
    """
    # Step 0: try fast Cloud seed restore BEFORE init_db, so we don't
    # accidentally CREATE TABLE into an empty file that we then overwrite.
    seed_restored = False
    try:
        seed_restored = _restore_from_seed_snapshot()
    except Exception:  # noqa: BLE001
        log.exception("Bootstrap: seed snapshot restore failed.")

    init_db()
    # Occupation labels post-date the original seed; an in-place upgraded DB
    # has the (empty) table but no rows, leaving the ISCO resolver blind.
    # Self-guards: no-op when already populated or no snapshot present.
    _backfill_occupations()
    if seed_restored:
        # Snapshot already includes manual seed + ESCO + hierarchy +
        # industry map + NSP + checklists. We deliberately do NOT
        # re-run the manual overlay here — `_truncate_taxonomy()` in
        # load_seeds would wipe the 14k ESCO rows. Bridge-plan rubric
        # edits require rebuilding the seed (rare, intentional).
        _overlay_job_ads()
        return

    if is_seeded():
        return

    log.info("Empty DB detected, no seed snapshot — running CSV bootstrap.")
    _overlay_manual_seed()
    _overlay_legacy_esco_csv()
    _overlay_job_ads()
    _overlay_nsp()


def _overlay_manual_seed() -> None:
    """Re-load the hand-edited taxonomy + checklist CSVs over the snapshot.

    These rows are owned by humans (the bridge-plan rubric) and must
    stay editable without rebuilding the seed.
    """
    try:
        from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

        with get_session() as session:
            _truncate_taxonomy(session)
            canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
            _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)
        log.info("Manual taxonomy + checklists overlaid.")
    except Exception:  # noqa: BLE001
        log.exception("Bootstrap: manual seed overlay failed.")


def _overlay_legacy_esco_csv() -> None:
    """Slow fallback when seed.sqlite.gz is missing — reads exported CSVs."""
    try:
        esco_skills_csv = Path("src/cv_bau_students/data/esco_skills.csv")
        esco_aliases_csv = Path("src/cv_bau_students/data/esco_aliases.csv")
        if esco_skills_csv.exists():
            from scripts.load_esco_csv import load_csv_subset

            aliases_path = esco_aliases_csv if esco_aliases_csv.exists() else None
            counts = load_csv_subset(esco_skills_csv, aliases_path)
            log.info(
                "ESCO CSV fallback loaded: %d skills, %d aliases.",
                counts["skills"],
                counts["aliases"],
            )
    except Exception:  # noqa: BLE001
        log.exception("Bootstrap: ESCO CSV fallback failed.")


def _overlay_job_ads() -> None:
    """Ingest the scraped ad corpus from SCRAPED_ADS_DIR — ONLY when job_ads is
    empty. The (scoped) seed snapshot already ships the demo target ad, so on a
    seed restore this is a no-op; re-ingesting would wipe the prepared target ad
    (ApexFinance text + ISCO + curated skills) and re-add ~481 unused rows the
    single-target app never shows. The full-corpus load stays the from-scratch
    path (empty DB, no snapshot)."""
    try:
        with get_session() as session:
            if session.execute(select(JobAdRow.id).limit(1)).first() is not None:
                log.info("job_ads already populated — skipping scraped-ad overlay.")
                return
        if SCRAPED_ADS_DIR.exists() and any(SCRAPED_ADS_DIR.glob("*.json")):
            from scripts.normalise_scraped_ads import _truncate_job_ads
            from scripts.normalise_scraped_ads import main as normalise_main

            _truncate_job_ads()
            normalise_main()  # writes job_ads
            log.info("Scraped ads loaded.")
    except Exception:  # noqa: BLE001
        log.exception("Bootstrap: job-ad ingest failed.")


def _overlay_nsp() -> None:
    """NSP overlay only fires on the slow-path (no seed snapshot).

    When seed.sqlite.gz is present, NSP rows are already inside it.
    """
    try:
        nsp_seed = Path("data/raw_nsp/competencies_seed.json")
        if nsp_seed.exists():
            from scripts.load_nsp import _load_local, _persist_competency

            for comp in _load_local(nsp_seed):
                _persist_competency(comp)
            log.info("NSP competencies loaded from %s.", nsp_seed)
    except Exception:  # noqa: BLE001
        log.exception("Bootstrap: NSP overlay failed.")


def prewarm_llm() -> None:
    """Fire a background thread that imports the Anthropic SDK + builds
    the client. First analyze_candidate skips the ~60s cold import.

    Daemon thread so the Streamlit process can exit cleanly during dev.
    """

    def _warm() -> None:
        try:
            from cv_bau_students import llm

            llm._client()  # forces import + ANTHROPIC_API_KEY validation
            log.info("LLM client prewarmed.")
        except Exception:  # noqa: BLE001 — prewarm is best-effort
            log.exception("LLM prewarm failed; first user analysis will pay cold-start.")

    threading.Thread(target=_warm, name="llm-prewarm", daemon=True).start()
