# RISKS.md — failure modes ordered by "first to break"

For the round-2 interview question *"Co jsou nejslabší místa projektu, která
by odešla jako první?"* — this document maps the known weaknesses
ordered by where the system would crack first, plus the quick fix vs
real fix split.

Status legend:
- ✅ Fixed in `main`
- 🟡 Documented mitigation but not yet wired
- ⏳ Future work

## Tier 1 — would fail in demo (up to 10 users)

| # | Failure | Symptom | Status | Real fix later |
|---|---|---|---|---|
| 1 | Empty DB at boot | UI shows 0 ads | ✅ `bootstrap.ensure_seeded()` runs taxonomy + ad load on first request when DB is empty | CI job seeds before first request |
| 2 | Streamlit Cloud single-process | 2 concurrent uploads → 2× 90s wait | 🟡 Quick fix accepts the limit; rebuild as FastAPI + Celery for prod | Worker queue (Redis + RQ/Celery) |
| 3 | Anthropic SDK cold import (~60s) | First analysis after idle = long spinner | ✅ `bootstrap.prewarm_llm()` daemon thread initializes the client at app start | Reserved instance |
| 4 | Anthropic rate limit (Tier 1 = 50 RPM) | 9+ concurrent → HTTP 429 | ⏳ Retry-with-backoff on `llm.call_json`; upgrade tier for prod | Batch API + tier upgrade |
| 5 | Completion loop has no UI dialog | Pipeline records open questions, recruiter can't answer them | ⏳ Multi-turn dialog component in the UI | Same |

## Tier 2 — would fail with real data scale (brief "tisíce inzerátů")

| # | Failure | Symptom | Status | Real fix later |
|---|---|---|---|---|
| 6 | Matcher iterated all ads per CV | 1000 ads × ~3 SQL/ad = 3000 queries / analysis | ✅ SQL pre-filter (`find_candidate_ads`) narrows to ads matching candidate's levels ∪ domains ∪ skill ids; one round-trip with `EXISTS` subquery | Vector search (pgvector) for semantic similarity |
| 7 | Domain detection at ingest is weak | 303/481 scraped ads classified `"general"` | ✅ `scripts/enrich_ad_domains.py` LLM-classifies in place; idempotent re-run | Trained classifier or LLM-only ingest |
| 8 | Skill taxonomy is mock (50 skills) | Many real CV skills miss the canonical name → 0 alias hits | 🟡 ESCO v1.2.1 documented in `docs/TAXONOMY_SOURCES.md` — 13 939 skills, native Czech, CC BY 4.0 download. Effort to load: ~8-12 h | Same |
| 9 | Bridge fit lied (100.0) when no rubric | Recruiter saw "perfect ready" on uncalibrated domain | ✅ `checklist_exists` + `-1.0` sentinel; matcher drops bridge axis from weighted sum when absent | Broaden checklists to cover every domain in corpus |
| 10 | Long ad / CV body fills the LLM context | Reasoning pass against 5 ads + profile approaches Claude's 200K token cap on extreme inputs | 🟡 Quick: truncate `raw_text` at ingest to 2000 chars. Real (planned): LLM-summarize each ad once at ingest, persist summary, reasoning reads summary | LLM summary at ingest (~$0.001 / ad one-time) |
| 22 | `skill_fit` resolves audit names per scored ad | `names_for_ids` round-trips for every ad in the pool before top-N is kept | 🟡 Batched to ~2 lookups/ad (was 5); SQL pre-filter bounds the pool | Score on ids only; resolve names once for the retained top-N matches (display layer) |

## Tier 3 — would fail in scale-up (100+ concurrent users)

| # | Failure | Symptom | Status | Real fix later |
|---|---|---|---|---|
| 11 | SQLite + StaticPool | Concurrent writes serialize | ⏳ | Postgres + pgvector (one env-var change thanks to SQLAlchemy) |
| 12 | Pipeline sync blocking | `analyze_candidate` holds worker 60-90s | ⏳ | Async pipeline + queue (FastAPI + Celery) |
| 13 | CV parsing accuracy (pypdf) | Multi-column / scanned CVs → empty text | ⏳ | Unstructured.io / AWS Textract |
| 14 | No observability | Don't know when LLM returned 500 | ⏳ | Structured logs + Sentry / Datadog |
| 15 | No DPA with Anthropic | CV text leaves the system without contract | ⏳ | Enterprise tier + DPA |

## Tier 4 — methodological / quality risks

Reviewed in Phase 10. Triage policy: fix what's free now, defer what
needs ground-truth data.

| # | Risk | Worth fixing now? | Status |
|---|---|---|---|
| 16 | Detector rigid (MBA student → wrongly "experienced") | No — no real CV processed yet | Deferred |
| 17 | Skepticism was prompt-only with positive examples only | Yes — free quality win | ✅ Added 6 reject-examples to `translate_capabilities.md` covering title inflation, multi-domain hallucination, personality-as-capability, hobby promotion, peak metric without scope, brigada misalignment |
| 18 | Confidence band calibration | No — needs eval set with ground truth | Deferred |
| 19 | Bridge-months guesstimates | No — 8 hand-curated domains are defensible | Deferred until ESCO load |
| 20 | Two skill namespaces (hand-seed vs ESCO) | Yes — broke target-role enrichment | ✅ `resolve_skill_esco` (taxonomy/repo) resolves candidate skills into the ESCO namespace; translate emits an English `esco_term` per capability → stored ESCO `skill_id`. Enrichment now intersects the occupation's essential∪optional set. must/nice/bridge stay seed-space (works); full namespace unification (move job_ad_skills + level_checklists onto ESCO ids) deferred — needs a loader rewrite + seed rebuild |
| 21 | Skill resolution drop (~half of free-text phrases) | Partial | 🟡 Layer-1 = diacritics-strip + ESCO aliases + rapidfuzz (token_sort ≥92) + proficiency-qualifier/parenthetical strip + UK/US spelling. LLM `esco_term` handles cross-lingual/paraphrase (`datové modelování`→`data modelling`). Residual misses: vendor tools absent from ESCO (`Power BI`, `Tableau`), and phrases neither lexically nor LLM-mapped. |

### Phase C (embeddings) — measured decision: DEFERRED

Measured ESCO resolution on the 6 demo CVs (115 skill phrases): Layer-1 **21%** →
**33%** after the deterministic qualifier/spelling normalisation (shipped, +12pp,
zero infra). Decomposing the remaining 67% miss:

- **~30% vendor tools** (`Power BI`, `Tableau`, `Excel`, `pandas`) — absent/weak in
  ESCO. Embeddings map them only to vague generics → poor signal. Fix = recruiter
  manual-add (skill-picker follow-up) + NSP (Phase D).
- **~37% soft/transversal traits** (`vedení týmu`, `spolehlivost`, `analytické
  myšlení`) — should be **excluded** from hard-skill_fit (person ≠ role). Embeddings
  would *inject noise* here, not signal.
- **~33% real hard skills, cross-lingual/paraphrase** — the LLM `esco_term` layer
  (already built) covers ~all of these; embeddings' *unique* marginal gain over it
  is tiny.

So embeddings' net unique recovery ≈ a handful of phrases already caught by the LLM,
at the cost of a model/API + ~1 GB-RAM friction on Streamlit Cloud, plus soft-trait
noise. **ROI is bad for this case → deferred.** Revisit only if, after a keyed
`esco_term` re-translate, a material residual of *real hard skills* remains
unresolved. Cheaper higher-ROI levers shipped/queued first: deterministic
normalisation (done), LLM `esco_term` (built), recruiter skill-picker (Phase B),
NSP Czech aliases (Phase D).

### NSP / CZ-ISCO occupation→skill map — evaluated, REJECTED (data-backed)

This PR wires the NSP/CDK live API loader. We probed whether to go further and build
a **Czech-native occupation→skill map** keyed on CZ-ISCO (the obvious "use the Czech
labour-market data" move). The live API supports the chain —
`GET /api/v1.2/workUnit` (1,752 occupations) → `/workUnit/{slug}/isco` (CZ-ISCO, e.g.
`22629`) → `/workUnit/{slug}/competence` (`competences`/`softSkills`/`genericSkills`) —
but the **data doesn't fit the matcher**:

- NSP `competences` are granular, occupation-specific *descriptive phrases* (e.g.
  *"Zpracovávání metodik analýz v oboru farmacie a kontroly léčiv…"*) that resolve to
  neither ESCO skill ids nor candidate CV phrases.
- The reusable parts (`genericSkills`, `softSkills`) are the broad/soft signals we
  deliberately keep OUT of `skill_fit` (person ≠ role).
- **CZ-ISCO *is* ISCO-08** (5-digit Czech extension; truncate→4 = same unit group), so
  NSP adds no new occupation backbone — ESCO already supplies occupation→skill keyed on
  ISCO with a cleaner, reusable skill taxonomy.

**Decision:** keep NSP's real value — Czech skill-name **aliases** on ESCO skills (what
this loader does) — and keep the occupation→skill join ESCO-driven. Building the
CZ-ISCO map (~3,500 API calls for a granular, poorly-matching parallel skill set) is
not worth it. Revisit only if Czech resolution proves weak after a keyed `esco_term`
re-translate.

## Post-review recommendations (2026-05-31, PRs #7–#18)

Alignment: all 11 PRs stay tightly on-mission. No scope creep, no architectural drift.

### R5 — Vendor tool ESCO aliases (HIGH ROI, LOW EFFORT)

~30% of data-analyst CV phrases miss ESCO resolution because common tools (`Power BI`,
`Tableau`, `pandas`, `scikit-learn`, `matplotlib`, `SPSS`, `Excel`) are absent or only
weakly represented in ESCO v1.2. Since the demo is a data-analyst ad, this is the
single most impactful unaddressed resolution gap.

Fix: `scripts/load_vendor_aliases.py` — a curated 20–30 entry dict mapping tool names
to their closest ESCO skill `uri`, inserted as `source="vendor"` aliases via the
existing `_persist_competency` path. Owner-run once; seed rebuild propagates it.
Effort: ~2h. No new deps, no schema change, no API calls.

### R6 — Postgres migration `--truncate` safety (LOW EFFORT, PRODUCTION RISK)

`scripts/migrate_sqlite_to_postgres.py --truncate` has no guard against accidentally
targeting the wrong (populated) production database. A table drop + re-insert on the
wrong Neon instance would silently wipe real candidate CVs.

Fix: require `--confirm-destroy` flag alongside `--truncate`, or prompt the user with
the target DB host + row count before proceeding. One-liner.

### R7 — Resolution rate re-measurement (DIAGNOSTIC, ~1h)

After PRs #9 (normalisation), #10 (diacritics), #12 (NSP hard-skills), #18 (memoize),
the resolution rate has not been re-measured against the demo CVs. PR #9 established
21% → 33% as a baseline; the current rate is likely higher but unknown.

A `scripts/measure_resolution.py` — run the 6 demo CVs through `resolve_skill_esco`
and count hits/misses by bucket (exact, alias, fuzzy, LLM-term, none) — would give
confidence and surface the next highest-ROI fix. Roughly 30 min to write.

## Recommended interview-answer order

> **"Co padne první?"**

1. Boot-seed missing on Cloud → fixed in 5 min, but proves we need a
   CI seed step in production.
2. Streamlit Cloud single-process → fine for demo, not for prod. The
   schema is Postgres-ready (1 env-var change); the pipeline is
   ready to be wrapped in a worker queue.
3. Matcher full-scan over all ads → SQL pre-filter pushes the
   feasible corpus from ~10k to ~1M ads in a single SQLite table.
   Path to vector search via pgvector is open (the same schema).

> **"Brief říká 'tisíce inzerátů' — proč ne miliony?"**

- Our ingest is batch (`scripts/normalise_scraped_ads.py`). BAU
  production needs continuous streaming ingest (Kafka or similar) +
  TTL on fresh ads + re-indexing on taxonomy change.
- Ad enrichment (domain + must-have skill extraction) should happen
  at ingest time, not match time. Phase 10c added that via
  `scripts/enrich_ad_domains.py`.
- Real scale needs semantic search (pgvector) for skill_ids that
  don't share exact taxonomy ids — already a slot in the schema,
  not implemented in the prototype.

## LLM cost at scale (Phase 12 two-pass journey)

> **"4+ LLM volání na uchazeče — není to drahé proti 'levnému řešení'?"**

Honest measurement of one *interested*-candidate journey ≈ **8 LLM
calls**:

| Stage | Calls | Detail |
|---|---|---|
| `run_generic_pass` | 5 | `extract_profile` (1) + `translate` (1) + `reason_for_ranking` over top-3 ads (3) |
| `express_interest` | 1 | `prefill_answers` (1). Role-question template is generated **once per ad**, amortised to ~0 per applicant. |
| `submit_role_specific` | 2 | `translate` again (1) + `reason_for_ranking` on the chosen ad (1) |

**Why it's acceptable today.** Quality-first per the owner's explicit
priority ("klidne za cenu toho, ze procesovani bude trvat o neco dele …
ale chci … verifikovane data vystupy"). The demo runs a fixed
~6-candidate seed (one-time ≈ $2). Two caches already cut repeats:
- `reasoning_cache` table dedups by `(candidate_id, ad_id, prompt_hash)`
  — re-opening the same candidate costs nothing.
- `translate` has an `lru_cache` keyed on profile content.

**Cheap-win optimisation — documented, deferred to a branch.** Two
changes halve the cost to **~4 calls with no quality loss**:

1. **Defer reasoning.** `run_generic_pass` reasons all 3 preview ads
   *before* the user picks one — 2 of 3 are wasted. Move full AI
   reasoning to the ad the user expresses interest in
   (`submit_role_specific` already reasons exactly that one). Preview
   cards show a cheap deterministic "proč ti sedne" line (skill-overlap
   count + bridge summary — pure Python). **Saves up to 3 calls.**
2. **Reuse translate.** The second `translate()` in
   `submit_role_specific` is redundant: the elevator pitch feeds only
   the personal-fit axis, and `_personal_fit(profile, ad)` is pure
   Python reading `profile.summary` directly. Fold the pitch into the
   summary and re-score without re-translating. **Saves 1 call.**

Net: **8 → 4** (extract, translate, prefill, reason) — the four being
the irreducible core of the value proposition.

**Scale path beyond that.** A fully deterministic *fast-match* mode
(0 LLM: taxonomy overlap + bridge only) for bulk pre-ranking, with the
LLM reserved for the recruiter-facing shortlist. Future option, not
built.

The optimisation itself is intentionally **not** applied here — it
lands on a `perf/llm-cost` branch as the first PR through the new CI
gate (see `CONTRIBUTING.md`), keeping the quality-tuned path on `main`
until measured.

This document is the answer key for the round-2 interview — not the
roadmap. The roadmap is whatever real users break first.
