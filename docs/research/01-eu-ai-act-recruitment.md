# Deep-research #1 — EU AI Act + GDPR for AI recruitment screening

**Run:** wf_b5cc5eec-f31 · 112 agents · ~24 min · 2026-05-31
**Bottom line:** cv-bau-students **IS HIGH-RISK** under the EU AI Act (Annex III §4(a), Art. 6(2)). Because it profiles/scores candidates, the Art. 6(3) "not significant risk" derogation is **unavailable**. A self-built tool makes you the **PROVIDER** (not just deployer) → heavier obligations.

## Key findings (all high-confidence, 3-0 verified)

1. **High-risk classification** — Annex III §4(a) covers AI to "filter applications, evaluate candidates". Matches us → Art. 6(2) high-risk. (artificialintelligenceact.eu/annex/3)
2. **No escape via Art. 6(3)** — the derogations (narrow procedural task etc.) are **void when the system profiles**. Skills-scoring = profiling → always high-risk. (ai-act-service-desk.ec.europa.eu/article-6)
3. **Self-built = PROVIDER** (Art. 3(3)/16, Art. 25). Obligations: QMS (Art. 17), technical documentation, **Annex VI internal-control conformity assessment** (self-assessment, no notified body for Annex III if standards followed), CE-marking, EU-database registration.
4. **Deployer duties (Art. 26)** even if internal: human oversight 26(2), **inform candidates** 26(11), inform workers/reps 26(7).
5. **GDPR overlap** — Art. 22 + CJEU **SCHUFA (C-634/21)**: even a *preparatory* score that a human rubber-stamps counts as an automated "decision" → needs lawful basis, **meaningful human review**, right to explanation, data minimization on CV data.
6. **Timeline** — Annex III high-risk obligations + Art. 50 transparency apply **2 Aug 2026** (Annex I embedded-product: 2027). *(One source claimed 2027 for Annex III — refuted 0-3; correct is 2026.)*

## Defensible MVP minimum (what to build + document)
- **Transparency notice** to candidates: AI is used, what it scores, logic in plain terms.
- **Human-in-the-loop**: recruiter must review; score is decision-support, never auto-reject. (We already hide auto-reject; recruiter sees scores.)
- **Right to explanation**: the per-candidate verdict + skill-coverage breakdown already serve this — keep it human-readable (the parse_reasoning work helps).
- **Bias monitoring**: log + periodically audit score distributions across groups (ties to research #3).
- **Audit logs**: who saw/decided what, when; model + version per score.
- **Model card / technical doc**: data sources (ESCO/NSP), scoring method, known limitations (vendor-tool gaps, Czech resolution), intended use.
- **Data governance**: CV data minimization, retention limits, lawful basis (consent or legitimate interest + balancing).

## Caveats
- Deadline **2 Aug 2026**. Harmonised standards (Art. 40/41) still developing → exact conformity bar may shift; Annex VII (notified-body) only if standards not followed.
- "Provider" burden is real for a productized tool; a pure **demo/case-study** (no real candidates, synthetic data) is lower-stakes but the *narrative* should show awareness.

## Top sources (primary)
- artificialintelligenceact.eu/annex/3 · /article/6 · /article/26 · /annex/6 · /article/113
- ai-act-service-desk.ec.europa.eu (Art. 6)
- gdpr-info.eu/art-22 · edpb.europa.eu ADM+profiling guidelines · CJEU SCHUFA C-634/21 (twobirds, iapp analyses)

**Interview value:** strong compliance slide — "we know this is Annex III high-risk; here's the human-oversight + transparency + audit design that addresses it."
