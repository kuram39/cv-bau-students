# PR Review & Recommendations — June 13, 2026

Generated after reviewing all merged PRs since project inception through PR #51.

---

## 1. Merged PR Inventory (June 1–2, 2026)

20 PRs merged in two days of concentrated development.

| # | Type | Title | One-line summary |
|---|------|-------|-----------------|
| #28 | feat | Evidence-strength + transparency + bias hardening | Replaces LLM self-confidence with `source_type → tier` (work/internship/cert = strong; thesis/project = medium; hobby/claimed = weak). Fixes the "everyone is střední" problem. |
| #29 | fix | Skip scraped-ad overlay when job_ads already seeded | Bootstrap idempotency: prevents 481-ad corpus from overwriting the prepared demo ad on cold start. |
| #30 | feat | Classify candidate type relative to target ad | `career_changer` now fires based on work history vs. ad domain, not a self-stated `target_domains` field that was always empty. |
| #31 | fix | No/low real experience → student, not experienced | `experienced` now requires ≥2y real (non-brigáda) work. Brigáda-only and gap re-entrants correctly land in the student/potential bucket. |
| #32 | docs | Rewrite README to current state | Synced README to the shipped system (single-target, criterion-referenced coverage, evidence tiers, 18-table schema, Postgres/Neon). |
| #33 | fix | Codex P2 edge-cases in evidence + classifier | 6 edge-case fixes: `real_work_years` field, `target_domains` seed fallback, evidence tier via esco_term fallback, strongest-tier-wins, unrescored Match → neurčeno. |
| #34 | chore | Rebake seed.sqlite.gz | Binary seed rebuilt after reseed; ships corrected demo to ephemeral Cloud deploys. |
| #35 | docs | Deep-research reports #6–8 | Adds vendor-taxonomy, LLM-cost, and explainability research reports to `docs/research/`. |
| #36 | chore | Research housekeeping + measure_resolution script | Corrects stale docstring/CLAUDE.md constants; adds `scripts/measure_resolution.py` to quantify Czech skill resolution %. |
| #37 | feat | Explainability — counterfactual recourse + honest precision | Deterministic `counterfactual_lifts()` ("Doložit X → pokrytí N%→M%"); low-doloženost warning; candidate-facing skill-only recourse. Zero extra LLM calls. |
| #38 | feat | Human oversight + bias-audit disclosure | Override checkbox + note per candidate (EU AI Act Art. 14); `audit_by_type()` four-fifths ratio; CSV export. Reads Match rows, no LLM. |
| #43 | docs | ARCHITECTURE.md — system study guide | Full system architecture doc: 4-layer flow, candidate journey sequence, LLM-call map, ER diagram, reading path. |
| #44 | feat | Reorder recruiter drill-in | AI verdict directly below score breakdown; questionnaire answers moved last. Better reading flow. |
| #45 | fix | Demo target ad domain → data-analyst | Target ad had `domain='general'`, so `bridge_fit` returned N/A sentinel. Fixed in seed; bridge_fit now computes (70.8–91.7) for 6 demo personas. |
| #46 | docs | Czech presentation README | `README.md` rewritten in Czech as the live presentation script; English moved to `docs/README.en.md`. |
| #47 | docs | Czech ARCHITECTURE.cs.md | Word-for-word Czech translation of `docs/ARCHITECTURE.md`. |
| #48 | feat | bridge_fit as months-to-ready estimate | Replaces abstract 0–100 index with `bridge_estimate()` in months + "only via experience" qualifier. Much more graspable for a recruiter. |
| #49 | fix | `work` evidence tier — real employment no longer weak | Critical bug: real employment was dumping into `other` → weak tier because `SourceType` had no `work` value. Markéta Horáková (3y analyst) was showing doloženost: nízká. Fixed + retag script + seed rebaked. |
| #50 | fix | Idempotent `_migrate_columns` — Postgres boot crash | `ALTER TABLE ADD COLUMN` now uses `IF NOT EXISTS` on Postgres + per-column transactions. Fixes DuplicateColumn crash on every boot of the Neon deploy. |
| #51 | feat | Audit threshold slider | Dynamic threshold (0–100 %, step 5) in the bias-audit panel. Adds saturation hint when all groups pass. |

---

## 2. Alignment with Core Assignment

Core assignment: AI platform that processes CVs from **students, fresh graduates, and career changers**, extracts personal data / education / work experience / skills / languages, and matches candidates to job postings fairly.

**All 20 PRs align.** No drift detected. Categorized:

- **Pipeline correctness (must-fix class):** #29, #31, #33, #45, #49, #50 — these were bugs that actively corrupted results (wrong candidate type, wrong evidence tier, Postgres crash). High priority; correctly shipped first.
- **Core feature quality:** #28, #30, #48 — improve the scoring signal itself.
- **Regulatory layer (table stakes for EU recruiting AI):** #37, #38 — GDPR Art. 22 counterfactual recourse + EU AI Act Art. 14 human oversight. Not scope creep; required for any commercial deployment in CZ/EU.
- **UX polish:** #44, #51 — recruiter-facing improvements. Proportionate.
- **Documentation / seed:** #32, #34, #35, #36, #43, #46, #47 — no code risk.

---

## 3. Flags

### Flag A — `personal_fit` is dead code in an active path
`total = skill_fit` (score.py line 69). `personal_fit` is hardcoded to `0.0` and no longer influences anything. Yet it still appears in `MatchScore`, `Match` schema, and likely in the recruiter drill-in JSON. This is misleading to future contributors and leaks a false signal that "three axes are scored."

**Recommendation:** Either remove `personal_fit` from the active scoring path entirely (schema migration: drop or archive the column), or explicitly rename it to `reserved_future` with a comment. A dead field named after an active concept erodes trust in the schema.

### Flag B — LLM call count claim is potentially stale
`CLAUDE.md` defers a `perf/llm-cost` branch targeting "8→4 calls per applicant." Deep-research #7 (PR #35) concluded the precompute optimization is already off the per-applicant path, and the call count per candidate is actually 4–6 depending on path (1 extract + 1 translate generic + 1 translate role-specific + 1 reason + optionally 1 classify + 1 generate_role_questions once per ad). The "8→4" framing may already be obsolete.

**Recommendation:** Update `CLAUDE.md` deferred items with the actual per-candidate call count and close or re-scope the `perf/llm-cost` branch. Keeping a stale deferral creates unnecessary planning debt.

### Flag C — Four-fifths audit is statistically meaningless at N=6
The bias-audit panel (PR #38, #51) implements the EEOC four-fifths ratio correctly. However, the demo has 6 candidates (3 student, 2 experienced, 1 career_changer). A four-fifths ratio computed on groups of 1–3 is not interpretable — a single flip from pass to fail swings the ratio from 1.0 to 0.0. The saturation hint (PR #51) partly addresses the all-pass case but not the small-N case.

**Recommendation:** Add a per-group minimum-N guard (e.g., `if group_count < 5: show "Příliš malý vzorek pro čtyři pětiny"` instead of the ratio). This prevents a recruiter from misinterpreting a demo artifact as a real signal. This is also the correct approach per EEOC guidance (which does not recommend applying four-fifths to pools under ~30 per group).

### Flag D — Czech resolution coverage is unmeasured
`scripts/measure_resolution.py` was added in PR #36 specifically to quantify the ~33% gap in Czech skill resolution before any further ESCO-alias loading work. As of this review, no output of that script has been committed to `docs/`. The deferred work ("ESCO Czech alias load / embeddings — gated on that number") is therefore still gated on a measurement that has not been taken.

**Recommendation:** Run `measure_resolution.py` against the committed seed, commit the output to `docs/resolution_baseline.txt` or similar, and use the number to decide whether to pursue the ESCO Czech alias load. If resolution is already >80%, the ESCO alias work may not be worth the complexity.

---

## 4. Concept Assessment

**The concept is intact and maturing correctly.**

The core thesis — replace "years of experience" with criterion-referenced skill coverage scored against the recruiter's explicit target skill set — is implemented cleanly. The two-pass pipeline (generic pass at upload, role-specific pass at interest) correctly defers expensive LLM work. The evidence-tier system (PR #28, #49) is a genuine differentiator: it lets a recruiter see *how* a skill was demonstrated, not just whether it was claimed.

The compliance layer (PRs #37, #38) is proportionate and code-grounded — counterfactual recourse uses zero extra LLM calls; the audit reads existing Match rows. This is the right way to add EU AI Act compliance without inflating cost or complexity.

**New directions (positive):**

- **Postgres is live** (Neon, evidenced by PR #50 prod-crash fix). Tier 3 risk "SQLite → Postgres" is effectively resolved.
- **Bridge_fit is now actionable** (PR #48): "~8 měs." is a recruiter-usable hiring decision input; "78.4" was not.
- **Czech-language-first documentation** (PRs #46, #47) signals readiness for a Czech-market audience, which is appropriate for the target demographic.

**Open directions (recommended next):**

1. **Minimum-N guard on four-fifths** (Flag C above) — one-liner, high trust impact.
2. **Run measure_resolution + commit result** (Flag D) — unblocks or closes the ESCO alias work.
3. **personal_fit cleanup** (Flag A) — lowers schema confusion for any future contributor.
4. **PDF parsing quality** — `pypdf` is Tier 3 risk in RISKS.md. For the student demographic (scanned PDFs, .docx exports), this is the most likely real-world failure mode. Unstructured.io or a simple `.docx` fallback would cover the majority of student CVs without heavyweight infrastructure.
5. **Completion loop UI** — the two-pass journey calls `ensure_role_specific_questions` but there is no multi-turn dialog UI for the mandatory-field completion loop. This is a known gap (RISKS.md Tier 1). It means a CV with missing mandatory BAU fields silently degrades rather than prompting the candidate.

---

## 5. Summary

| Status | Detail |
|--------|--------|
| Core concept | Intact. Criterion-referenced coverage + evidence tiers is a coherent, defensible approach. |
| Recent PRs | All aligned. No scope creep. |
| Critical bugs fixed | Yes — evidence tier for real work (#49), Postgres boot crash (#50), classifier defaults (#31). |
| Compliance layer | Proportionate, code-grounded, appropriately scoped. |
| Top technical debt | Dead `personal_fit` field, unmeasured Czech resolution, stale LLM-call-count claim. |
| Top product gap | No completion-loop UI, PDF parsing limited to pypdf. |
| Staging/prod | Neon deploy confirmed live (evidenced by #50 prod crash). |
