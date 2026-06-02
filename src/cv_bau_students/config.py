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
# Default to Sonnet 4.6 — ~40% cheaper than Opus 4.8 ($3/$15 vs $5/$25 per 1M)
# and the right tier for our mostly-extraction workload. The two interpretive
# calls (capability translation + recruiter reasoning) opt into adaptive
# thinking via `llm.call_json(..., think=True)`; the cheap extraction /
# classification calls stay thinking-off.
#
# QUALITY MODE: flip this to "claude-opus-4-8" to A/B the highest-ceiling model
# (Opus has a stronger ceiling on sparse-signal judgement — translator caveat /
# confidence calibration). No other change needed: both models take the same
# request surface (adaptive thinking, no sampling params).
LLM_MODEL = "claude-sonnet-4-6"
LLM_MAX_TOKENS = 4096
# Thinking calls: max_tokens is the TOTAL budget shared by the (hidden) thinking
# blocks and the JSON answer. With adaptive thinking the model can spend the
# whole budget thinking and never emit the answer (stop_reason=max_tokens,
# blocks=['thinking']). Cap thinking explicitly via `budget_tokens` to guarantee
# answer room: 8000 total = up to 4000 thinking + ≥4000 for the JSON answer.
# PR #19 reduced this from the original 12000/8000 split after demo latency issues.
LLM_THINK_MAX_TOKENS = 8000
LLM_THINK_BUDGET = 4000  # thinking cap; must be < LLM_THINK_MAX_TOKENS (leaves ≥4000 for answer)
# Master switch for extended thinking on the 2 interpretive calls (translate,
# reason). ON by default: the budget-overflow bug (PR #17) is fixed, so thinking
# is safe, and at demo volume (~tens of calls) the latency cost is acceptable for
# the quality gain. Set CV_BAU_STUDENTS_THINK=0 to disable (fastest upload /
# cost A-B). The per-call budget cap above bounds the thinking spend when on.
LLM_THINK_ENABLED = os.environ.get("CV_BAU_STUDENTS_THINK", "1") != "0"

# --- Pipeline budgets ---
COMPLETION_MAX_ROUNDS = 2
TRANSLATOR_CONFIDENCE_FLOOR = 0.3  # drop below this from scoring inputs
HIGH_CONFIDENCE_THRESHOLD = 0.7

# --- Matcher weights — UNUSED since PR #20 (total = skill_fit directly) ---
# Kept for reference / future multi-axis mode. Do NOT import these in
# score.py without updating the scoring formula and this comment.
WEIGHT_SKILL_FIT = 0.45
WEIGHT_BRIDGE_FIT = 0.35
WEIGHT_PERSONAL_FIT = 0.20  # personal_fit retired; value 0.0 hard-coded

# --- ESCO target-role enrichment (skill_fit) ---
# When an ad resolves to an ISCO occupation, skill_fit gets a capped bonus
# for demonstrating occupation-essential ESCO skills *beyond* the recruiter's
# hand-typed must-haves. Enrichment can only lift the base (recruiter must/nice
# coverage stays the authoritative, interpretable signal) — never deflate it.
# The ~300-skill ESCO essential set is deliberately NOT used as a denominator
# (that would crush every score to single digits); breadth is rewarded, capped.
ROLE_BONUS_CAP = 12.0  # max points the enrichment can add
ROLE_BONUS_PER = 3.0  # points per evidenced role-essential skill beyond must
ROLE_ESSENTIAL_GAP_SAMPLE = 8  # how many missing role-essential skills to surface

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
