"""Constants for the cv_bau_students pipeline.

Weights are documented in the README — do not tune without updating it.
"""

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
# REPO_ROOT only reliable when `pip install -e .` is in effect — for the
# installed-wheel deploy path we fall back to PACKAGE_ROOT for everything.
REPO_ROOT = PACKAGE_ROOT.parent.parent
PROMPTS_DIR = PACKAGE_ROOT / "prompts"
DATA_DIR = PACKAGE_ROOT / "data"

# --- Anthropic API ---
LLM_MODEL = "claude-sonnet-4-5"
LLM_MAX_TOKENS = 4096
LLM_TEMPERATURE = 0.0

# --- Pipeline budgets ---
COMPLETION_MAX_ROUNDS = 2
TRANSLATOR_CONFIDENCE_FLOOR = 0.3  # drop below this from scoring inputs
HIGH_CONFIDENCE_THRESHOLD = 0.7

# --- Matcher weights (sum = 1.0) ---
WEIGHT_SKILL_FIT = 0.45
WEIGHT_BRIDGE_FIT = 0.35
WEIGHT_PERSONAL_FIT = 0.20

# --- Database ---
# Default SQLite file is at `./data/cv_bau_students.sqlite` relative to
# the working directory — assumes scripts are run from the repo root.
# Production deploys override via `CV_BAU_STUDENTS_DB_URL` (Postgres DSN
# works without code changes; SQLAlchemy abstracts dialect differences).
# Note: the runtime DB is ephemeral state, NOT package data — CSV seeds
# in DATA_DIR are the human-edited source and rebuild the DB on startup.
DEFAULT_DB_URL = "sqlite:///./data/cv_bau_students.sqlite"
DB_URL = os.environ.get("CV_BAU_STUDENTS_DB_URL", DEFAULT_DB_URL)

# --- Seed file paths (CSV is the human-edited source of truth) ---
TAXONOMY_SEED_CSV = DATA_DIR / "taxonomy_seed.csv"
LEVEL_CHECKLISTS_CSV = DATA_DIR / "level_checklists.csv"
ROLE_FAMILIES_CSV = DATA_DIR / "role_families.csv"

# --- Scraped job ads (gitignored raw input) ---
# Resolved relative to CWD when running the loader script. Override via
# env in case the project root changes.
SCRAPED_ADS_DIR = Path(
    os.environ.get("CV_BAU_STUDENTS_SCRAPED_ADS_DIR", "data/raw_ads/scraped")
).resolve()

# --- Detector heuristics ---
STUDENT_MAX_WORK_YEARS = 2
RECENT_GRAD_LOOKBACK_YEARS = 1
