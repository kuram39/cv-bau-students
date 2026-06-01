# Deep-research #5 — verifying self-reported skills / anti-gaming

**Run:** wf_267ae688-908 · 106 agents · ~17 min · 2026-06-01
**Bottom line:** CV/skill faking is the **norm, not the exception** (>90% use some faking; intensifies under stakes; targets the exact job-relevant skills). Remedy = an **evidence hierarchy** (self-report weak; structured-behavioral / work-sample strong + harder to fake) + question design that demands concrete specifics + honest "self-reported, not verified" framing.

## Key findings (high-confidence, 3-0)

1. **Faking is near-universal + targeted**: Levashina & Campion (2007, N=1,346) — >90% use some interview faking (mild embellishment dominates; outright lies 28–75%). Dunlop et al. (2020) — overclaiming **rises under high-stakes selection** AND concentrates on **job-relevant** content. → the recruiter's exact target skills draw the strongest faking.
2. **Faking damages construct validity** of self-report (rank-order distortion, inflated correlations). Criterion-validity impact contested (~⅓ decline in a 2025 meta), construct damage broadly agreed. → raw self-reported coverage is a weak signal.
3. **Evidence hierarchy** (Schmidt-Oh-Shaffer 2016): structured interview validity **.58** vs self-report conscientiousness **~.22**; SJT **.32** with incremental validity over cognition. Structured/behavioral methods **separate description from evaluation** → ~3× less fakeable than self-report (Van Iddekinge 2005).
4. **SFIA framework** = ready-made evidence-strength taxonomy: **knowledge < skill < competency**, graded by **tests < projects < delivered real-world outcomes**. → encode an evidence-strength tag per skill.
5. **Question design that resists gaming**: less-transparent items, **past-behavior questions demanding concrete specifics** (project, role, metrics), situational judgement, + **detection (not moral) warnings** all measurably cut distortion.

## Concrete design recommendations (for us)
- **Evidence-strength tag per skill** (we have `source_type` + `confidence` + `caveat` on capabilities): map to a SFIA-style ladder — `claimed` (CV self-report) < `project/thesis` < `work/delivered`. Weight evidenced > claimed in the verdict (display, not necessarily score).
- **Weight demonstrated > claimed**: our matcher scores coverage; the *reasoning/verdict* should foreground evidenced skills + flag claim-only ones. (skill_fit stays coverage; the recruiter sees evidence strength.)
- **Questionnaire = behavioral specifics**: our role questions already ask "describe a concrete situation where you used SQL — problem, approach, result". That's the gaming-resistant pattern — keep + lean into specifics (project, metrics, your role).
- **Honest framing**: label CV skills "self-reported, not verified" (already the principle). DON'T auto-accuse — fabrication detection is bias/false-accusation prone (see limits).
- **Inconsistency signals (use cautiously)**: claim-vs-evidence mismatch / vagueness can be surfaced as a *recruiter prompt to probe*, NOT an automated reject. Limits: false positives, bias against non-native/atypical writers.

## Caveats
- Most validity figures = Schmidt-Hunter lineage (overstated ~.10–.20 post-2022; see research #2) — rank order holds.
- Automated fabrication detection is risky (AI Act high-risk + bias, research #1/#3) → keep human-in-loop, frame as "probe", never accuse.

**Tie-in:** validates the questionnaire design (behavioral specifics) + the evidence/confidence tagging already in the schema. Concrete next step: surface evidence-strength (claimed vs evidenced) in the recruiter drill-in.
