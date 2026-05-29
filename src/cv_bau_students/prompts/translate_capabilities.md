# Translate student / career-changer artefacts into experienced-language capabilities

You analyse a candidate's structured profile and produce a list of **capabilities** — concrete skills the candidate has demonstrated — in the vocabulary a hiring manager for an experienced role would recognise. Where direct work experience is thin, you lean on school projects, thesis work, internships, brigády, certifications, hobbies, and open-source contributions.

The same capability list is matched against job ads downstream. **Honesty + skepticism + evidence quotes** matter more than padded output. Producing 12 confident-but-fabricated capabilities is worse than producing 5 evidenced ones.

## Inputs

- **Candidate type**: {candidate_type} (`student`, `career_changer`, `experienced`)
- **Target domains** (what the candidate is applying to): {target_domains}
- **Candidate profile JSON**: {profile_json}

## Output (strict JSON only)

Return a single JSON object — no prose, no markdown fences:

```json
{
  "translated_capabilities": [
    {
      "skill": "<short canonical name, lower-case, prefer existing taxonomy terms>",
      "evidence_quote": "<verbatim substring from the profile JSON (project description, brigada description, summary, thesis_summary) that justifies this — max 200 chars>",
      "confidence": <float 0.0 - 1.0>,
      "caveat": "<short hedge in profile language, or null>",
      "source_type": "thesis" | "school_project" | "internship" | "brigada" | "hobby" | "open_source" | "certification" | "course" | "language" | "other",
      "relevance": "must_have" | "nice_to_have"
    }
  ]
}
```

## Skepticism principles (carry over from cv-estimator)

1. **Anchor confidence at 0.5.** Move up to 0.7+ only with concrete numeric / role-scoped evidence (employee count, project metric, named system, transaction volume). Below 0.4 should mean *"weak signal, recruiter should probe"*.
2. **Cap title-only inferences at 0.4.** A degree title alone does not prove the underlying skill — the thesis summary or project description does.
3. **Reject second-order leaps.** If reaching the capability needs more than one inferential step from the profile fields, don't emit it.
4. **Sequential exposure ≠ synthesis.** A candidate who worked at one fintech then later at one e-commerce shop is NOT "cross-industry synthesis" — drop multi-domain integration capabilities unless one role explicitly combined the domains.
5. **Person ≠ role.** Personality traits ("intellectually curious", "polymath", "open-minded") describe the person, not professional capability. Drop them.
6. **Peak ≠ steady state.** "Processed 4M transactions/day" → record as peak in the caveat.
7. **Team output ≠ individual ownership.** When team_size > 1 and the contribution split is unclear, record in the caveat.

## Source-type specific calibration

| Source | Default confidence range | Typical caveat |
|---|---|---|
| `thesis` (with summary) | 0.6 – 0.75 | "academic project — production maturity not demonstrated" |
| `school_project` (capstone, semester project) | 0.5 – 0.7 | "team project — individual scope unclear" (when team_size > 1) |
| `internship` | 0.55 – 0.7 | "short tenure — exposure rather than ownership" |
| `brigada` (in target domain) | 0.4 – 0.55 | "part-time + parallel to studies" |
| `brigada` (outside target domain, e.g. McDonald's → data analyst target) | 0.3 – 0.45 | "cross-domain — soft signal only" |
| `open_source` (PR linked) | 0.65 – 0.8 | "verify PR scope" |
| `certification` | 0.6 – 0.7 | "credential — practical depth not demonstrated" |
| `course` (completed, with project deliverable) | 0.5 – 0.65 | "course-led project, no production exposure" |
| `hobby` / interests | 0.3 – 0.5 | "soft signal — hobby-derived" |

## Career-changer overlay

For `candidate_type == "career_changer"`, ALSO surface prior-domain achievements that translate to the target domain:

- "5 years ops management" → `project management`, `stakeholder management`, `cross-functional coordination` (confidence 0.55 – 0.65, caveat: "industry-different but skill-transferable").
- Quantified prior-role outputs (budget owned, team size, regions covered) are stronger signal than role titles. Use them in evidence_quote.

## Output constraints

- **5 – 12 capabilities is the expected range.** Below 5 is fine if the profile is truly sparse — don't pad. Above 12 is over-fitting.
- **`evidence_quote` MUST be a verbatim substring** of one of: `summary`, `thesis_summary`, `school_projects[*].description`, `work_experience[*].description`, `certifications`, or `open_source`. If you cannot quote, do not emit the capability.
- **Drop capabilities outside the candidate's `target_domains`.** A backend-developer-target student who mentioned a marketing club does NOT get a `marketing` capability — even if the source quote supports it. (The matcher would have to score it anyway.) Exception: cross-domain capabilities that are genuinely transferable to any target ("technical writing", "stakeholder management").
- **`relevance: must_have`** is reserved for capabilities a hiring manager for the candidate's `target_domains` would list as required. Everything else is `nice_to_have`.

## Examples

**Example A — student with thesis + school project + brigada.**

Profile excerpt:
- target_domains: `["data-analyst"]`
- thesis: `"Klasifikace sentimentu českých tweetů s využitím transformeru BERT; můj příspěvek je preprocesing dat a srovnání BERT vs. logistická regrese."`
- school_project: title `"Webová aplikace pro školní jídelnu"`, description `"Postavili jsme s 4 spolužáky React + Django, já implementoval backend REST API."`, technologies `["React", "Django"]`, team_size 5
- brigada: McDonald's `"Pokladna, koordinace s kuchyní, řešení reklamací."`

Output:

```json
{
  "translated_capabilities": [
    {
      "skill": "Python",
      "evidence_quote": "Klasifikace sentimentu českých tweetů s využitím transformeru BERT; můj příspěvek je preprocesing dat",
      "confidence": 0.65,
      "caveat": "Academic project — production maturity not demonstrated",
      "source_type": "thesis",
      "relevance": "must_have"
    },
    {
      "skill": "data preprocessing",
      "evidence_quote": "můj příspěvek je preprocesing dat a srovnání BERT vs. logistická regrese",
      "confidence": 0.6,
      "caveat": "Academic scope — single dataset",
      "source_type": "thesis",
      "relevance": "must_have"
    },
    {
      "skill": "Django",
      "evidence_quote": "postavili jsme s 4 spolužáky React + Django, já implementoval backend REST API",
      "confidence": 0.5,
      "caveat": "Team project — owns the backend slice only",
      "source_type": "school_project",
      "relevance": "nice_to_have"
    },
    {
      "skill": "REST API",
      "evidence_quote": "já implementoval backend REST API",
      "confidence": 0.55,
      "caveat": "Course project — small surface area",
      "source_type": "school_project",
      "relevance": "nice_to_have"
    },
    {
      "skill": "customer interaction",
      "evidence_quote": "Pokladna, koordinace s kuchyní, řešení reklamací",
      "confidence": 0.35,
      "caveat": "Cross-domain — soft signal only",
      "source_type": "brigada",
      "relevance": "nice_to_have"
    }
  ]
}
```

DROPPED: `React` (no individual contribution claim — team_size 5, candidate explicitly owns backend slice).

**Example B — career-changer (ops manager → product role).**

Profile excerpt:
- candidate_type: `"career_changer"`
- target_domains: `["product-manager"]`
- work_experience: `"Provozní manažer v restauraci U Pinkasů (5 let): vedl 12-člennou kuchyňskou směnu, koordinoval s dodavateli, řešil reklamace, vlastnil P&L."`
- summary: `"Hledám příležitost přejít do produktové role, kde se uplatní moje schopnost řídit cross-functional projekty."`

Output:

```json
{
  "translated_capabilities": [
    {
      "skill": "stakeholder management",
      "evidence_quote": "vedl 12-člennou kuchyňskou směnu, koordinoval s dodavateli",
      "confidence": 0.65,
      "caveat": "Industry-different but skill-transferable",
      "source_type": "other",
      "relevance": "must_have"
    },
    {
      "skill": "cross-functional coordination",
      "evidence_quote": "Hledám příležitost přejít do produktové role, kde se uplatní moje schopnost řídit cross-functional projekty",
      "confidence": 0.55,
      "caveat": "Self-described — verify in interview",
      "source_type": "other",
      "relevance": "must_have"
    },
    {
      "skill": "P&L ownership",
      "evidence_quote": "vlastnil P&L",
      "confidence": 0.7,
      "caveat": "Restaurant scale, not product scale",
      "source_type": "other",
      "relevance": "nice_to_have"
    }
  ]
}
```
