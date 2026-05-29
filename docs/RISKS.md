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

This document is the answer key for the round-2 interview — not the
roadmap. The roadmap is whatever real users break first.
