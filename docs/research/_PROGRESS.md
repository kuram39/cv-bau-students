# Overnight deep-research queue (cv-bau-students)

Sequential — one finishes, next starts. Reports saved as `NN-slug.md` here.
(Uncommitted; review in the morning, PR what's useful.)

| # | Topic | Status | File |
|---|-------|--------|------|
| 1 | EU AI Act — recruitment AI high-risk + GDPR obligations | ✅ done | 01-eu-ai-act-recruitment.md |
| 2 | Skills-based hiring — calibrate junior vs senior on one comparable axis | ✅ done | 02-skills-calibration.md |
| 3 | Bias & fairness in skills-based matching | ✅ done | 03-bias-fairness.md |
| 4 | Czech NLP for skill resolution (lemmatization/stemming) | ✅ done | 04-czech-nlp-resolution.md |
| 5 | Self-reported skills — anti-gaming / verification | ✅ done | 05-self-report-verification.md |
| 6 | Vendor-tool skill taxonomies beyond ESCO | ✅ done | 06-vendor-tool-taxonomies.md |
| 7 | LLM cost & latency optimization for the pipeline | ✅ done | 07-llm-cost-latency.md |
| 8 | Explainability in recruiting UI / right-to-explanation | ✅ done | 08-explainability-ui.md |

Started: 2026-05-31 (overnight run). #6–8 run 2026-06-01 (wf_53437201-d95, 84
agents, multi-modal web sweep → synthesize → 3-voter adversarial verify). The
adversarial pass corrected several over-claims in #6–8 — corrections are baked
into each report and flagged in a "Verification" section. Headline reversals:
- #7: the "precompute ad-side calls" win was **refuted** (those calls are
  already off the per-applicant path) — the real lever is Haiku model-tiering;
  the 8→4 target is largely already met.
- #6: O*NET API is gated (not zero-friction), the ESCO↔O*NET crosswalk is
  occupation-level only, and Lightcast's native-Czech tagging is paid — so the
  cheap Czech fix is in-house alias/diacritics over ESCO's own Czech labels.
- #8: the compliance backbone (CJEU/GDPR/AI-Act) verified 3/3 and all
  code-grounded recommendations survived; several empirical citations were
  misattributed and are corrected.
