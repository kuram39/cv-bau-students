# Deep-research #4 — Czech NLP for skill-phrase → ESCO resolution

**Run:** wf_0e46ffc3-ba3 · 103 agents · ~16 min · 2026-06-01
**Bottom line:** Two-tier. (1) **Lemmatization is a cheap, low-risk first step before embeddings — use `simplemma`** (pure Python, permissive, 0.89 Czech). (2) **Multilingual embeddings give the bigger lift, especially cross-lingually** — but footprint-gated on a ~1GB Streamlit container.

## Key findings (high-confidence, 3-0)

1. **simplemma = lowest-footprint Czech lemmatizer**: pure Python, no required runtime deps, pip-installable, **0.89** accuracy on UD CS-PDT; single Czech dict loads lazily. → drop-in before the fuzzy resolver.
2. **MorphoDiTa/UDPipe (ÚFAL)** reach ~0.95–0.98 but models are **CC BY-NC-SA (non-commercial)** — a real license blocker for a deployed/commercial app (library code is MPL-2.0, fine; the *models* aren't). → prefer simplemma unless genuinely non-commercial.
3. **Lemmatization is the right retrieval lever for inflected languages** (Czech: cases/declension), but IR studies (Finnish) show normalization methods converge on average P-R → **choose on footprint/integration, not raw accuracy**. (A claim that gains are "only marginal" was REFUTED 1-2 — don't over-discount lemmatization.)
4. **Multilingual dense bi-encoders >> lexical/fuzzy** on ESCO linking, gap **most pronounced cross-lingually** (lexical degrades far more when query lang ≠ label lang). MELO benchmark (ESCO-endorsed): E5 / text-embedding-3-large highest; multilingual-E5-large Recall@10 0.88–0.92 (IT/ES→EN).
5. **Best pipelines = embeddings-for-recall + LLM/cross-encoder rerank** (+14–22 RP@10 over embedding-only; Clavié & Soulié 2023). We already do LLM normalization (esco_term in translate) — that's the rerank-ish step.
6. **ESCO is natively multilingual (28 langs incl. Czech)** — EC best practice: match over ESCO's **own Czech labels**, don't translate to English. → load ESCO `cs` labels as aliases (we partly do via NSP aliases).

## Footprint on ~1GB Streamlit Cloud
- `paraphrase-multilingual-MiniLM` (0.1B, 384-dim, **~470MB**) → **fits**.
- `multilingual-E5-large` (~560M, ~2.2GB) / `LaBSE` (~471M, ~1.8GB) → **tight/infeasible** without quantization.
- So if embeddings: MiniLM tier only, or quantized E5.

## Ranked recommendation for us (ROI)
1. **simplemma lemmatization** before fuzzy — cheap, permissive, no infra. Lemmatize the candidate phrase + the canonical/alias labels, then exact/fuzzy. Expect a real lift on inflected Czech CV phrases (current ~33% baseline). **Do this first.**
2. **Load ESCO native Czech labels as aliases** (if not already full) — free recall, no model.
3. **LLM esco_term** (already shipped) covers cross-lingual/paraphrase — keep.
4. **Embeddings (MiniLM tier)** only if 1–3 leave a real hard-skill residual — adds ~470MB + infra; defer (matches the Phase C "bad ROI for this case" decision until measured).

## Caveats
- Benchmarks are mostly occupation linking + IT/ES/EN, not Czech *skill-phrase* linking specifically → supportive-by-analogy.
- simplemma single-word accuracy 0.89; multi-word skill phrases need per-token lemmatization + rejoin.
- Measure first (research #7 / a `measure_resolution.py`) — quantify the current 33% before/after simplemma to justify embeddings.

**Action tie-in:** simplemma is the concrete next resolver improvement (cheap, permissive). The earlier roadmap deferred lemmatization "until measured" — this says: add simplemma, measure lift, only then consider MiniLM embeddings.
