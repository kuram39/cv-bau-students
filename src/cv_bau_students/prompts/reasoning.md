# Generate a recruiter-facing rationale for a single (candidate, ad) match

You receive a candidate profile, the translator's capability list, the
matcher's score breakdown, and the job ad. You write a short narrative
that helps the recruiter decide whether to invite the candidate to an
interview.

## Inputs

- **Candidate type**: {candidate_type} (`student` / `career_changer` / `experienced`)
- **Candidate profile** (JSON): {profile_json}
- **Translated capabilities** (JSON): {capabilities_json}
- **Match score breakdown** (skill_fit, bridge_fit, personal_fit, total, confidence_band, bridge_plan): {match_json}
- **Job ad** (JSON): {ad_json}
- **Output language**: {language} (`cs` or `en`)

## Output (strict JSON only)

```json
{
  "verdict": "<one-liner in {language}: should the recruiter invite to interview? Yes / probably yes / probably no / no, with one-sentence why>",
  "strengths": ["<short bullet, in {language}, 5-15 words>", "..."],
  "gaps": ["<short bullet, in {language}, 5-15 words>", "..."],
  "interview_prompts": ["<concrete interview question that probes the strongest open uncertainty>", "..."]
}
```

- 2–4 strengths.
- 1–3 gaps. If `bridge_plan` is non-empty, surface the most actionable item first.
- 2–3 interview prompts. Reference specific projects / thesis / brigády from the profile so the candidate sees you read their CV.

## Reasoning style per candidate type

### Student (`candidate_type == "student"`)

- Lead with the strongest project / thesis evidence.
- Acknowledge limited work history explicitly. Don't pretend the
  candidate has experience they don't have — instead point at the
  bridge plan (e.g. "would reach medior in ~3 months with Python
  course + Power BI cert").
- Interview prompts should ask the candidate to walk through a
  project's ownership scope (who did what), not just confirm they
  used a tool.

### Career-changer (`candidate_type == "career_changer"`)

- Lead with transferable signals from the prior domain (stakeholder
  management, P&L ownership, project execution).
- Surface the domain-specific gap clearly — the recruiter needs to know
  what onboarding looks like.
- Recommend pairing with a mentor in the first weeks; ask interview
  questions that probe motivation + concrete preparation steps already
  taken.

### Experienced (`candidate_type == "experienced"`)

- Standard recruiter rationale — match against must_have, surface
  nice_to_have wins, flag concrete gaps. No special framing needed
  (the BAU pipeline produces these in production; this prompt is
  here so the matcher can still rationalise an experienced
  candidate that lands in our pipeline by mistake).

## Confidence + skepticism

- Reference the `confidence_band` explicitly. A wide band (≥20) means
  the recruiter should treat the score as advisory only — say so.
- If any translated_capability carries a `caveat`, mention the
  relevant ones in the gaps section (e.g. "Python evidence from a
  team project — verify individual contribution in interview").
- Don't restate the score numbers literally; describe their meaning
  ("strong skill match, modest personal fit gap").

## Examples

### Czech student → junior Data Analyst ad

```json
{
  "verdict": "Pravděpodobně ano: silný technický profil s konkrétními projektovými výsledky; doporučujeme krátký technický pohovor + ověření individuálního přínosu.",
  "strengths": [
    "Diplomová práce na NLP (BERT) ukazuje samostatnou implementaci preprocesingu",
    "Pokrývá všechny must-have dovednosti pro juniorní data analyst pozici",
    "Sebevedení v Pythonu doložené konkrétním projektem"
  ],
  "gaps": [
    "Žádná praxe v BI nástrojích (Power BI nebo Tableau) — most asi 2 měsíce přes certifikaci",
    "Týmový projekt React + Django — nejasný individuální scope"
  ],
  "interview_prompts": [
    "Projděte nás krok po kroku jeho roli v projektu školní jídelny — co konkrétně psal a co řešil tým.",
    "Jakým způsobem by přistoupil k novému BI nástroji (Power BI), pokud by si ho potřeboval naučit za 2 měsíce?"
  ]
}
```
