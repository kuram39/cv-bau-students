# Generate targeted clarifying questions for a sparse CV

You receive a structured candidate profile that has been extracted from a CV but has missing-yet-matchable fields. Your job is to write **1–3 short clarifying questions** the candidate should answer so the matcher can do its work.

## Inputs

- **Candidate profile JSON**: {profile_json}
- **Missing fields list** (Python heuristic flagged these): {missing_fields}
- **Language** for the output questions: {language}

## Output (strict JSON only)

```json
{
  "questions": [
    {
      "field": "<which profile field the answer fills>",
      "question": "<short, direct, in the candidate's language>",
      "why_it_matters": "<one sentence explaining why the matcher needs this>"
    }
  ]
}
```

Maximum 3 questions per round. Pick the highest-leverage missing fields first. Prefer questions that unlock multiple downstream scoring axes over questions that fill one cell.

## Question style

- Direct, conversational, no jargon.
- One ask per question — don't bundle.
- Match the CV's language ({language}). Use formal you ("Vy" in cs).
- Reference the candidate's own CV facts when possible ("Pro pozici X uveďte..."). Concrete > generic.

## Priority order for missing fields

1. **`summary` (elevator pitch)** — unlocks `personal_fit` axis entirely. Without it, that axis is undefined.
   - Czech prompt example: "Napište prosím 3 věty o sobě: kdo jste, co vás baví v práci, co hledáte v další pozici."
   - English prompt example: "In 3 sentences: who you are, what you're excited by professionally, what you're looking for next."

2. **`target_domains`** — anchors which job ads to score against.
   - "Vyberte 2–3 oblasti, ve kterých byste rád pracoval (např. data analytika, frontend vývoj, marketing analytika)."

3. **Brigády / part-time roles without `description`** — translator can't extract transferable signal from a job title alone.
   - "U pozice na {employer} popište jednou větou: co jste se tam naučil nebo zařídil?"

4. **Thesis / school project listed by title only** — high-signal item that needs scope detail.
   - "O čem je vaše bakalářská práce a jaký je váš příspěvek (vs. téma, které zadal vedoucí)?"

5. **Skill listed without proof** — confidence is capped at 0.4 by the translator's skepticism rule until evidence appears.
   - "U dovednosti {skill} uveďte jeden konkrétní projekt, kde jste ji použil."

6. **Languages with no level** — hard filter on job ads often requires CEFR level.
   - "Na jaké úrovni mluvíte anglicky / německy (A2 / B1 / B2 / C1 / C2)?"

## Rules

- Never invent missing-field categories. Only ask about fields named in `missing_fields`.
- Never reveal scoring weights or the level-checklist mechanics. Questions are user-facing, not infrastructure-facing.
- If `missing_fields` is empty, return `{"questions": []}` — don't manufacture work.
- Respect the round limit: even if many fields are missing, cap at 3 questions per round. The pipeline runs at most 2 rounds.

## Examples

**Example 1.** Missing: `summary`, `target_domains`. Language: cs.
```json
{
  "questions": [
    {
      "field": "summary",
      "question": "Napište prosím 3 věty o sobě: kdo jste, co vás v práci baví a co hledáte v další pozici.",
      "why_it_matters": "Bez krátkého představení nelze posoudit kulturní soulad s týmem inzerátu."
    },
    {
      "field": "target_domains",
      "question": "Vyberte 2–3 oblasti, ve kterých byste rád pracoval (např. data analytika, frontend vývoj, marketing analytika).",
      "why_it_matters": "Bez cílových oblastí nevíme, na jaké typy inzerátů Vás navázat."
    }
  ]
}
```

**Example 2.** Missing: `thesis_summary` only. Language: en.
```json
{
  "questions": [
    {
      "field": "thesis_summary",
      "question": "What problem does your thesis tackle, and what's your specific contribution as opposed to the topic your supervisor proposed?",
      "why_it_matters": "Thesis is the strongest evidence of independent work — we need the scope to translate it into transferable capabilities."
    }
  ]
}
```
