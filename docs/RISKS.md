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

## Known gap — corpus prefilter ignores curated target skills (deferred)

`rank_candidate`'s SQL prefilter (`find_candidate_ads`) builds `skill_ids_any`
from the candidate's seed-namespace skill names and joins only `job_ad_skills`
— it does NOT consult `ad_target_skills` (the recruiter-curated set) or the
candidates' ESCO capability `skill_id`s. So in a *multi-ad corpus*, an ad a
candidate matches ONLY through its curated ESCO target skills can be filtered
out before `score_match` ever sees it (when other ads keep the prefilter
result non-empty, so the full-list fallback doesn't trigger).

**Why deferred:** the single-target MVP scores the one target ad *directly*
(`pipeline._score_single_ad`, bypassing the prefilter), so this never bites the
demo. It only matters once corpus-wide ranking against curated sets is a
product feature. Fix when that lands: union `ad_target_skills` skill_ids +
capability esco ids into the prefilter's overlap check.

---

## PR Review 2026-06-30 — alignment check + new risk register entries

**Review scope:** PRs #1–#51 (45 merged, 2 closed-not-merged).
**Core assignment check:** AI matching platform processing CVs (extraction of
personal data, education, work experience, skills, languages) → match to job ads.

### Alignment verdict: INTACT

All shipped features map to the core pipeline or responsible-AI obligations.
No scope creep detected. Three-axis scoring (skill_fit / bridge_fit /
personal_fit), ESCO namespace, and the two-panel Streamlit UI are coherent
and consistent with the brief.

### New risks introduced by PRs #28–#51

| # | Risk | Tier | Status |
|---|---|---|---|
| 23 | `bridge_estimate` months are hand-curated for 8 domains only | Tier 2 | 🟡 Expand rubrics or suppress display for uncovered domains |
| 24 | Detector thresholds (brigáda 0.3×, 2y real-work gate) are heuristic | Tier 4 | ⏳ Calibrate on first real-CV batch |
| 25 | Human-override UX not tested with a real recruiter | Tier 2 | ⏳ User test before presenting override as a safety feature |
| 26 | Counterfactual recourse shows per-skill lift but not whether the skill is acquirable by this candidate | Tier 4 | 🟡 Add disclaimer in UI or scope to bridge-plan skills only |
| 27 | Czech README primary + EN secondary → English-only readers miss key info | Low | ✅ `docs/README.en.md` exists; pointer in Czech README |

### Recommended next PRs (priority order)

1. **`perf/llm-cost`** — 8→4 calls (defer 3 preview-ad reasoning calls + reuse
   translate). Documented in the "LLM cost at scale" section above. Highest ROI,
   no quality loss. Estimate: ~4h.
2. **`feat/bridge-rubrics`** — expand `level_checklists` beyond the 8 shipped
   domains so bridge_fit months never shows N/A on a real ad. Or gate display
   on checklist coverage.
3. **`chore/measure-resolution`** — run `scripts/measure_resolution.py` on the
   demo CVs with the final pipeline (NSP aliases + LLM esco_term). Record the
   number; gates the embeddings decision.
4. **`feat/multi-ad-prefilter`** — fix the corpus prefilter gap (item #22 above)
   before the single-target MVP becomes a multi-ad product.
5. **`feat/vendor-tool-aliases`** — Power BI / Tableau / Excel / pandas are absent
   from ESCO; add a small curated alias table so they resolve to the nearest ESCO
   skill rather than falling through to `other`. Low effort, high demo impact.

### What NOT to build next (anti-drift guard)

- Embeddings / pgvector — ROI is bad until measure_resolution confirms a real gap
  that the LLM esco_term layer doesn't cover (see Phase C decision above).
- NSP occupation→skill map — evaluated, rejected (data doesn't fit matcher; see
  Tier 2 risk #8 analysis above).
- Multi-tenant / auth — out of scope for round-2 demo.
- Real-time ingest / Kafka — premature. Batch ingest is fine for demo scale.
