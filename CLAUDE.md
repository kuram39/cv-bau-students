# cv-bau-students — working context

Round-2 AI matching platform for **students / fresh-graduates / career-changers**.
Translates CVs without years of work history (school projects, thesis, brigády,
courses, prior-domain achievements) into "experienced-equivalent" capabilities so
a recruiter can compare them fairly against job ads written for experienced hires.
Hybrid code-fork of the round-1 `cv-estimator` repo (separate repo, untouched).

GitHub: `buhlez31/cv-bau-students` (private, standalone — NOT a GitHub fork).

## Working conventions (IMPORTANT)

- **Branch → PR → merge. Never commit to `main` directly.** Typed prefixes:
  `feat/` `fix/` `docs/` `perf/` `chore/`. See `CONTRIBUTING.md`.
- The owner merges PRs themselves (solo repo). After a merge, sync local +
  delete the branch + `git remote prune origin`.
- CI gate `.github/workflows/ci.yml` runs `ruff check` + `black --check` +
  `pytest -q` on every push/PR. Run all three locally before pushing.
  Branch protection is NOT hard-enforced (free + private tier — needs GitHub Pro
  or a public repo); the convention is "don't merge a red PR".
- venv at `./venv`. Use `./venv/bin/<tool>` (pip install -e . hits an SSL cert
  error in this env — a `.pth` file or `pip install -e . --no-deps` is the workaround).
- **`ANTHROPIC_API_KEY` is scrubbed from agent subprocesses** — the agent cannot
  make live LLM calls. Any LLM-backed script (seed, CV generation) is run by the
  owner with their key. Tests mock `llm.call_json`, so CI needs no key.
- Caveman response mode is active in the owner's sessions (terse; full technical
  substance kept).

## Architecture (where things live)

- `src/cv_bau_students/`
  - `pipeline.py` — thin orchestrator. Two-pass candidate journey:
    `run_generic_pass` → `express_interest` → `submit_role_specific`
    (+ `ensure_role_specific_questions`). Legacy `analyze_candidate` kept for
    back-compat.
  - `llm.py` — single Anthropic entry point. `call_json(prompt, *, max_tokens,
    think=False)`; `think=True` enables adaptive thinking (only on the 2
    interpretive calls). Lazy `_client()` import (cold import ~60s).
  - `config.py` — `LLM_MODEL = "claude-sonnet-4-6"` (default). **Quality mode:**
    flip to `"claude-opus-4-8"` (one line, documented in the comment) to A/B.
    `LLM_THINK_MAX_TOKENS = 8000` headroom for thinking calls.
  - `db_models.py` — 16-table SQLAlchemy schema (candidates, taxonomy,
    skill_industry_map, level_checklists, job_ads, matches, role-specific Q&A,
    interests, reasoning_cache).
  - `translator/translate.py`, `explanation/reason.py` — the 2 interpretive LLM
    calls (`think=True`). Everything else (extraction, classify, prefill) is
    thinking-off to keep cost down.
  - `matcher/` — skill-coverage scoring (`total = skill_fit`; `bridge_fit` is
    a secondary months-to-ready signal; `personal_fit` retired to 0.0), SQL
    pre-filter + hard filter. `taxonomy/repo.py` has `resolve_skill` +
    `expected_skills_for_isco`.
  - `ui/app.py` + `ui/candidate_panel.py` + `ui/recruiter_panel.py` — two-tab
    Streamlit (Kandidát upload journey / Recruiter scored list). Candidate side
    hides the numeric score; only the recruiter sees scoring.
  - `bootstrap.py` — `ensure_seeded()` restores from `data/seed.sqlite.gz`
    (role-scoped ~2k rows, sub-second cold start) on cold start; `prewarm_llm()` daemon.
  - `prompts/*.md` — all LLM prompts (skepticism rules live in
    `translate_capabilities.md`).
- `scripts/` — loaders + seed: `load_esco_csv.py` (raw ESCO from
  `data/raw_esco/`), `load_esco_hierarchy.py`, `load_esco_occupations.py`,
  `load_nsp.py`, `build_cloud_seed.py`, `seed_target_demo.py` (the demo seed),
  `generate_student_cvs.py` / `fetch_hf_resume_samples.py` (CV sourcing).
- `data/raw_cv_samples/{students,experienced}/*.txt` — 6 committed demo CVs
  (3 data-analyst students + 3 experienced), all synthetic/Apache-2.0.

## Taxonomy / data

- **ESCO v1.2.x** (CC BY 4.0) is the primary skill taxonomy — the committed
  seed (`src/cv_bau_students/data/seed.sqlite.gz`, ~104 KB) is **role-scoped**
  to the data-analyst demo (~2k rows: data-role skill family ∪ demo CVs/ad).
  Full ESCO (~200k rows) lives in `data/raw_esco/` (gitignored). Rebuild:
  loaders → `scripts/build_scoped_seed.py`. `DATA_ROLE_URIS` controls the scope.
- **Czech NSP/CDK** (CC0) layered on top.
- Attribution required: see `NOTICES.md`; UI footer + README "Data Sources".

## Demo (run by the owner, needs the key)

```bash
rm -f data/cv_bau_students.sqlite
./venv/bin/python -c "from cv_bau_students.bootstrap import ensure_seeded; ensure_seeded()"
./venv/bin/python -m scripts.seed_target_demo      # ~40 LLM calls, one-time
./venv/bin/streamlit run src/cv_bau_students/ui/app.py
```
Target job = scraped "Datový analytik" ad, re-employer'd to "ApexFinance s.r.o.".
First Streamlit launch is slow (plotly cold import); if the window hangs with no
URL it's usually the Streamlit first-run email prompt — `~/.streamlit/credentials.toml`
with an empty `email` skips it.

## Current state / open items

**51 PRs merged as of 2026-06-17.** Platform is feature-complete for the
data-analyst demo. Test suite: **219 passing**. Postgres (Neon) + Streamlit
Cloud deploy live.

### What's shipped
- Single-target MVP: all CVs scored against one recruiter-curated ad.
  `total == skill_fit` = % coverage of the curated target skill set.
- Evidence tiers (`doloženost`): work > thesis/project > hobby/claimed.
  `work` source_type → strong tier (real employment is no longer shown weak).
- Candidate-type classifier vs the target ad: `student` / `career_changer` /
  `experienced` based on real (non-brigáda) work years + field alignment.
- Counterfactual recourse (GDPR Art. 22): "Add skill X → coverage N%→M%".
- Human oversight: recruiter override + decision log. Bias audit by candidate type.
- Bridge-fit as months-to-ready estimate (not an abstract index).
- Audit threshold slider for the recruiter's four-fifths fairness check.
- Role-scoped seed (data-analyst family): cold start sub-second on Neon.
- `docs/ARCHITECTURE.md` + `docs/ARCHITECTURE.cs.md` (Czech) + Czech README.
- Model Card (`docs/MODEL_CARD.md`): EU AI Act high-risk, GDPR, demographic-blind.

### Open PRs (flag-gated, need owner A/B)
- **#39 Haiku model-tiering** — mechanical calls at 3× lower cost. Blocked on
  `./venv/bin/python -m scripts.ab_extract` (needs key). If Jaccard ≥ 0.85 on
  Czech CVs → safe to enable `CV_BAU_STUDENTS_TIER=1`.
- **#40 Haiku A/B harness** — the script that validates the above.
- **#41 Structured output** — forced tool-use JSON (eliminates fence-strip).
- **#42 Prompt caching** — cache the static prefix of `extract_profile.md`.
  Merge order: #39 → #40 → #41 → #42 (retarget each to `main`).

### Key deferred / unconfirmed
- **`measure_resolution.py` not yet run** — script is committed (#36), but the
  actual Czech resolution % is still "estimated ~33%". Run:
  `./venv/bin/python -m scripts.measure_resolution` (no key needed). Result
  determines whether ESCO Czech-alias load is worth doing.
- **Second demo role** — `level_checklists` only covers `data-analyst`.
  Any other ad domain → `bridge_fit = N/A`. Documented in RISKS.md.
- **`WEIGHT_*` constants in `config.py`** — annotated as UNUSED since #22.
  Delete in a `chore/cleanup` PR when convenient.
- **Slide deck** — not started.
- `docs/RISKS.md` is the interview answer-key (failure tiers, cost, scale).

## Gotchas

- iCloud offloads files under `~/Documents` — if `import streamlit` hangs reading
  a `.pyc`, force-download the venv (`brctl download …/venv`) or move the project
  out of Documents.
- SQLite tests use in-memory `StaticPool` via `tests/conftest.py`; `_engine()`
  reads `config.DB_URL` lazily so `reset_engine_for_tests` works.
