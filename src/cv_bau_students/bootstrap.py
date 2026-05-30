"""Boot-time bootstrap helpers.

Streamlit Cloud spawns a fresh container per deploy — the SQLite DB
ships empty. These helpers detect an empty taxonomy and seed it from
the committed CSVs + scraped ad JSON. Idempotent: re-running is a
single `SELECT COUNT(*)` query when state already exists.

Also exports `prewarm_llm()` so the first user analysis doesn't pay
the 60-second Anthropic SDK cold-import penalty.
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from cv_bau_students.config import LEVEL_CHECKLISTS_CSV, SCRAPED_ADS_DIR, TAXONOMY_SEED_CSV
from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import JobAdRow, Skill

log = logging.getLogger(__name__)


def is_seeded() -> bool:
    """True when the taxonomy + at least one job ad already exist."""
    with get_session() as session:
        has_skills = session.execute(select(Skill).limit(1)).first() is not None
        has_ads = session.execute(select(JobAdRow).limit(1)).first() is not None
    return has_skills and has_ads


def ensure_seeded() -> None:
    """Run load_seeds + normalise_scraped_ads if the DB is empty.

    Catches errors so a bootstrap failure surfaces in logs but does not
    crash the Streamlit app — the recruiter sees the "no ads" empty
    state instead of a stack trace.
    """
    init_db()
    if is_seeded():
        return
    log.info("Empty DB detected — running bootstrap seed.")

    try:
        from scripts.load_seeds import _load_checklists, _load_taxonomy, _truncate_taxonomy

        with get_session() as session:
            _truncate_taxonomy(session)
            canonical_to_id = _load_taxonomy(session, TAXONOMY_SEED_CSV)
            _load_checklists(session, LEVEL_CHECKLISTS_CSV, canonical_to_id)
        log.info("Taxonomy + checklists loaded.")
    except Exception:  # noqa: BLE001 — log + continue so partial state still beats crash
        log.exception("Bootstrap: taxonomy seed failed.")

    try:
        if SCRAPED_ADS_DIR.exists() and any(SCRAPED_ADS_DIR.glob("*.json")):
            from scripts.normalise_scraped_ads import _truncate_job_ads
            from scripts.normalise_scraped_ads import main as normalise_main

            _truncate_job_ads()
            normalise_main()  # writes job_ads
            log.info("Scraped ads loaded.")
    except Exception:  # noqa: BLE001
        log.exception("Bootstrap: job-ad ingest failed.")

    # NSP Czech competency overlay — fast (~5-100 rows from local JSON).
    # ESCO full-load (14k+ rows) stays a manual CLI step — too long for
    # boot. Run `python -m scripts.load_esco` once after deploy.
    try:
        from pathlib import Path

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
