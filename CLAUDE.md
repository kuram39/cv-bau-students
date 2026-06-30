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
  - `matcher/` — 3-axis scoring (skill_fit / bridge_fit / personal_fit), SQL
    pre-filter + hard filter. `taxonomy/repo.py` has `resolve_skill` +
    `expected_skills_for_isco`.
  - `ui/app.py` + `ui/candidate_panel.py` + `ui/recruiter_panel.py` — two-tab
    Streamlit (Kandidát upload journey / Recruiter scored list). Candidate side
    hides the numeric score; only the recruiter sees scoring.
  - `bootstrap.py` — `ensure_seeded()` restores from `data/seed.sqlite.gz` (full
    ESCO) on cold start; `prewarm_llm()` daemon.
  - `prompts/*.md` — all LLM prompts (skepticism rules live in
    `translate_capabilities.md`).
- `scripts/` — loaders + seed: `load_esco_csv.py` (raw ESCO from
  `data/raw_esco/`), `load_esco_hierarchy.py`, `load_esco_occupations.py`,
  `load_nsp.py`, `build_cloud_seed.py`, `seed_target_demo.py` (the demo seed),
  `generate_student_cvs.py` / `fetch_hf_resume_samples.py` (CV sourcing).
- `data/raw_cv_samples/{students,experienced}/*.txt` — 6 committed demo CVs
  (3 data-analyst students + 3 experienced), all synthetic/Apache-2.0.

## Taxonomy / data

- **ESCO v1.2.x** (CC BY 4.0) is the primary skill taxonomy — full set lives in
  `src/cv_bau_students/data/seed.sqlite.gz` (~9.2 MB, committed). ~14k skills +
  19k hierarchy edges + 70k occupation→skill rows + ~6k occupation labels
  (en+cs, `occupations` table, drives the role→ISCO resolver). Universal
  coverage (every field, not just IT). Rebuild loaders incl.
  `scripts/load_esco_occupation_labels.py`, then `scripts/build_cloud_seed.py`.
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

PRs #1–#51 merged (2 closed without merge: #11 review-doc, #13 superseded by #12).
Last routine review: 2026-06-30.

### Shipped (PRs #1–#51)

- **Model + thinking** — Sonnet 4.6 default; selective `think=True` on 2 interpretive
  calls (translate, reason). Budgeted thinking + timeout guard (#17, #19).
- **Target-role-first scoring** — ads resolve to ISCO; `expected_skills_for_isco()`
  feeds skill_fit enrichment bonus + gap surface; recruiter audit drill-in shows
  breakdown + raw CV text (#5).
- **ESCO namespace** — candidate skills resolved into ESCO ids via layered resolver
  (diacritics → aliases → rapidfuzz → LLM esco_term) (#6, #10).
- **NSP/CDK Czech aliases** — live API loader for Czech skill-name aliases (#7, #12).
- **Evidence-strength tiers (doloženost)** — replaces coarse LLM-confidence; tiers
  mapped from source_type (thesis > internship > school > brigáda > other) with a
  `work` tier fix so real employment isn't weak (#28, #49).
- **Candidate type detector** — classifies relative to the target ad (student /
  fresh-grad / career-changer / experienced) with ad-relative thresholds; brigáda
  weighted 0.3× toward real_work_years (#30, #31, #33).
- **Explainability** — counterfactual recourse: per-missing-skill coverage lift shown
  to recruiter; honest precision disclosure (#37).
- **Human oversight** — recruiter override + override_note + decision_at schema cols;
  bias-audit panel with selection counts per candidate type (#38).
- **Bridge_fit as months-to-ready** — `bridge_estimate()` sums per-gap
  `bridgeable_in_months` from the rubric; N/A guarded when no rubric exists (#48).
- **Audit threshold slider** — 0–100 % step-5 slider in the Audit tab; replaces
  hard-coded 50 % cutoff (#51).
- **Postgres path** — Cloud-safe persistence; idempotent `_migrate_columns` (no
  DuplicateColumn crash on restart) (#16, #50).
- **Perf** — memoized skill resolvers, role-scoped seed (~2k rows vs 200k),
  smaller thinking budget, request timeout (#18, #19, #24).
- **Docs** — ARCHITECTURE.md + Czech translation, Czech primary README, deep-research
  reports #1–#8 (#32, #43, #46, #47, #35).

### Deferred (priority order)

1. **LLM-cost 8→4 calls** — documented in `docs/RISKS.md`; planned `perf/llm-cost`
   branch. Highest ROI before any real-user volume.
2. **Bridge rubric coverage** — only 8 domains have `level_checklists`; expand to
   cover remaining corpus domains or surface N/A transparently.
3. **Czech resolution measurement** — `scripts/measure_resolution.py` ready but not
   run on final pipeline. Gate embeddings / extra alias work on this number.
4. **Detector calibration** — brigáda 0.3× and 2y real-work thresholds are heuristic;
   revisit once real CVs are processed.
5. **Multi-ad corpus ranking** — prefilter ignores curated target skills (see RISKS.md
   "Known gap"); acceptable for single-target MVP, breaks for multi-ad ranking.
6. **Slide deck / demo script** update to reflect dual-panel flow and new scoring UX.

- `docs/RISKS.md` is the interview answer-key (failure tiers, cost trade-off, scale).

## Gotchas

- iCloud offloads files under `~/Documents` — if `import streamlit` hangs reading
  a `.pyc`, force-download the venv (`brctl download …/venv`) or move the project
  out of Documents.
- SQLite tests use in-memory `StaticPool` via `tests/conftest.py`; `_engine()`
  reads `config.DB_URL` lazily so `reset_engine_for_tests` works.
