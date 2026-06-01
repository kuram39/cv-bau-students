# Deep-research #3 — bias & fairness in AI/skills-based candidate matching

**Run:** wf_a996cddd-1ab (relaunch; first run stalled) · 108 agents · ~19 min · 2026-06-01
**Bottom line:** Bias is real, measurable, and bounded by a **mathematical impossibility**: you can't satisfy all fairness metrics at once when group base rates differ — you must pick + document which you prioritize. Skills-based scoring reduces bias ONLY if the skill labels / target set aren't themselves proxies.

## Key findings (high-confidence, 3-0)

1. **Impossibility theorem** (Kleinberg-Mullainathan-Raghavan 2017; Chouldechova 2017): calibration + equal false-positive + equal false-negative rates are **mutually incompatible** unless prediction is perfect or base rates are equal — and *approximate* fairness doesn't escape it. → For a scoring tool, pick a fairness target, justify it, document the trade-off. Don't claim "unbiased".
2. **Calibrated ≠ equal error rates**: a predictively-unbiased score still produces disparate FPR/FNR across groups with different base rates (the COMPAS lesson). Disparate impact can arise from honest math — but that reopens whether the *labels* are biased.
3. **Ranking amplifies** (Singh & Joachims 2018): ranking by descending relevance = winner-take-all exposure. A 0.03 relevance gap → ~30% less exposure for the lower group (exposure ∝ 1/log(1+position)). → **our ranked recruiter list**: the *position*, not just the score, is the fairness-load-bearing output.
4. **Amazon (2018)**: tool learned to penalize "women's" + all-women colleges from 10y male-skewed data; removing known gendered terms **didn't guarantee** no new proxies. → an LLM translating CVs→skills can encode gender/age/prestige proxies with no explicit demographic field.
5. **HireVue (2021)**: dropped facial analysis after EPIC FTC complaint (unvalidated trait inference). → validity/job-relatedness burden; don't infer "capabilities" beyond evidenced.
6. **EEOC (2023 guidance)**: an AI tool is a "selection procedure" → Title VII adverse-impact applies; **employer liable even if a vendor built it**.
7. **NYC Local Law 144**: annual **independent bias audit** computing per-group selection-rate AND scoring-rate impact ratios, public summary posting, candidate notice.

## Formal metrics (pick + document)
- **Adverse impact / four-fifths (80%) rule** — EEOC threshold; selection-rate ratio < 0.8 = flag.
- **Demographic parity** vs **equalized odds** vs **calibration** — incompatible (above). For a ranked screen, exposure/selection-rate parity (LL144-style) is the auditable one.

## Practical mitigations (what the literature supports — for us)
- **Blind the obvious proxies**: don't feed name/age/gender/photo/nationality to the LLM. (CV upload → strip/ignore.)
- **Detect-then-downweight** features correlated with protected attributes (HireVue/pymetrics method) — but treated as **insufficient alone**, not a cure.
- **Monitor score + ranking distributions across groups** (when demographic data ethically available) — log selection-rate ratios.
- **Human-in-the-loop** (already: recruiter decides; score is decision-support).
- **Validity/job-relatedness**: score only on evidenced, role-relevant skills (our curated target set) — NOT inferred traits. Keep the audit trail (raw CV + breakdown).
- **Skills-based CAN reduce bias** (vs tenure/degree proxies — see research #2) **IF** the target skill set + labels aren't proxies. ESCO labels are occupation-neutral → helps.
- **Document everything** (model card, chosen fairness target, known limits) — feeds the EU AI Act high-risk obligations (research #1).

## Caveats
- Most metrics/law are US-framed (EEOC/LL144); EU side = AI Act + GDPR (research #1). Combine.
- We have **no demographic labels** in the demo → can't run a real adverse-impact audit; the honest claim is "designed for auditability + human oversight", not "audited unbiased".

**Interview value:** mature answer — name the impossibility theorem, show the design choices (blind proxies, evidenced-skills-only, human-in-loop, audit trail) + acknowledge limits, tie to AI Act #1.
