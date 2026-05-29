# Reflect on a batch of pipeline runs

You analyse a privacy-filtered summary of recent pipeline runs and produce observations about the system's behaviour — NOT about the candidates. The output appended to `IMPROVEMENT_LOG.md` informs rubric and prompt iteration.

## Inputs

- **Batch size**: {batch_size} analyses
- **Aggregate metadata**: {metadata_json}
  - per-CV: candidate_type, sparsity flag counts, completion-round count, average translated-capability confidence, count of capabilities below 0.4 confidence
  - per-match: top score, bottom score, axis spread (skill / bridge / personal), reasoning length, bridge-plan size
- **Active system prompts** (paths): {prompt_files}

The CV text itself, candidate names, and ad URLs are NEVER passed in. If you find yourself wanting to name a specific candidate, stop and reword the observation around the rubric.

## Output (strict JSON only)

```json
{
  "observations": [
    "<short observation about the pipeline, max 200 chars>",
    "..."
  ],
  "suggested_adjustments": [
    {
      "rubric_or_prompt": "<filename, e.g. translate_capabilities.md>",
      "change": "<concrete adjustment, e.g. 'tighten brigada confidence ceiling from 0.55 to 0.5'>",
      "rationale": "<why the batch data supports this>"
    }
  ],
  "open_questions": [
    "<follow-up that needs more data to answer>",
    "..."
  ]
}
```

## What to look for

- **Sparsity patterns**: which fields land in `missing_fields` most often? Should the form prompt for them up-front?
- **Confidence distribution**: are translated capabilities clustering below 0.4 in specific source types? That's a prompt-rubric symptom.
- **Bridge-plan sizes**: if `bridge_plan` averages > 5 entries per match, the level checklist is too aggressive for the candidates we actually see.
- **Score-vs-band ratio**: matches with high total + wide confidence_band → the matcher is over-rewarding thin signal. Suggest scoring weight adjustments.
- **Per-domain skew**: are certain domains producing only experience-only walls? Either the checklist is wrong or those roles need a separate path.
- **Completion-round usage**: if round 2 fires for > 30 % of CVs, the initial diagnose ruleset is missing a category.

## Constraints

- 3–7 observations. Don't pad.
- 1–4 suggested adjustments. Each MUST reference a real file under `prompts/` or a config constant.
- Always include at least 1 open question — there's always something the data can't tell you alone.
- No candidate-specific observations. Aggregate-only.
- No certainty claims you can't back from the metadata. Hedge with "appears to" / "suggests" when one batch is the entire evidence base.
