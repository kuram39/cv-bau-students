# Model / System Card — cv-bau-students

A transparency + governance summary for the CV↔role matching demo. Grounded in
the project's own deep-research (`docs/research/01` EU AI Act, `03` bias/fairness,
`02` calibration, `05` self-report/evidence).

## Intended use
Decision-**support** for a recruiter screening candidates (students / fresh
graduates / career-changers / experienced) against **one** target job ad. It
surfaces a skills-coverage score + an evidence breakdown to help a human decide
whom to interview. It is **not** an automated hiring decision and must not be
used to auto-reject.

## How it works (method)
- An LLM extracts a structured profile from the CV and translates artefacts
  (thesis, projects, brigády, work) into **capabilities** with an evidence quote.
- Capabilities resolve to **ESCO** skill ids (deterministic normalize + alias +
  fuzzy + an LLM `esco_term` cross-lingual hint).
- **Score = criterion-referenced skill coverage**: % of the recruiter-curated
  **target skill set** the candidate evidences. Validated by I/O research (#2):
  criterion-referencing is fairer than ranking juniors against peers, and tenure
  is a weak performance predictor — so we score skills, not years.
- **`bridge_fit`** is a *separate* "potential/growth" axis, shown beside the
  headline, never folded into it.
- **Doloženost** (evidence strength) per matched skill = how it was demonstrated
  (`source_type` → 🟢 work/internship · 🟡 project/thesis · ⚪ claimed-only).
  Reliability comes from evidence, not LLM self-confidence (#5, SFIA ladder).

## Data
- **ESCO v1.2** skills/occupations — CC BY 4.0 (see `NOTICES.md`).
- **NSP/CDK** Czech aliases — CC0.
- **Demo CVs** — synthetic, Apache-2.0. No real personal data is committed.
- Runtime CVs (live uploads) → private DB (Postgres/Neon or ephemeral SQLite),
  never GitHub.

## Fairness & bias
- **Skills-only scoring** — no demographic features (name/gender/age/nationality)
  enter the score; the extract + translate prompts are instructed to ignore them
  (name is kept for display only). [#3]
- **No proxy-downweighting layer**: there are no protected-attribute features to
  downweight (scoring is skills-only); blinding extraction is the correct lever.
- **Impossibility theorem** (Kleinberg–Mullainathan–Raghavan; Chouldechova): no
  scorer can satisfy all group-fairness metrics at once when base rates differ.
  We therefore do **not** claim "unbiased"; we choose evidenced-skills coverage +
  human oversight + an audit trail. [#3]
- **Ranking caveat**: list *position* (not just score) carries fairness load
  (Singh & Joachims) — the recruiter sees scores, not an auto-filtered list.

## Human oversight & explainability (GDPR Art. 22 / EU AI Act)
- A human recruiter makes every decision; the score is advisory.
- Each candidate has a human-readable **explanation**: verdict, matched/missing
  skills, per-skill evidence strength, bridge plan, and the **raw CV text** for
  audit.
- Each rationale records the model + thinking mode used (audit, in the stored
  reasoning payload).

## Known limitations
- **EU AI Act**: candidate screening is **high-risk** (Annex III §4a); a real
  deployment would owe provider obligations (QMS, conformity assessment, logging,
  registration) by 2 Aug 2026. This is a **demo/case-study** on synthetic data —
  designed *for* auditability, not formally audited/conformity-assessed. [#1]
- **No demographic data** in the demo → no real adverse-impact (four-fifths)
  audit can be run; the design supports it, the demo can't evidence it. [#3]
- **Resolution**: ~1/3 of Czech skill phrases resolve to ESCO ids today; vendor
  tools (Power BI/Excel/Tableau) are weak/absent in ESCO → covered via the
  recruiter's curated picks, not ESCO. (Lemmatization/embeddings = future work.)
- **Self-reported skills** are unverified; the questionnaire surfaces specifics
  but cannot detect fabrication — we never auto-accuse. [#5]
- **Single-target** demo: one ad; corpus-wide ranking is out of scope.

## Data governance
- CV text stored is **capped** (20k chars) = minimisation. Lawful basis for a
  real deployment: consent or legitimate interest (+ balancing). Retention limits
  + candidate notice + right to human review would be required in production.
