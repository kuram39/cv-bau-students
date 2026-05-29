# Generate a realistic Czech / English job ad

You synthesise a single job ad matching the given parameters. Output a structured JSON object that the rest of the pipeline can index.

## Inputs

- **Domain**: {domain} (e.g. `data-analyst`, `frontend-developer`, `marketing-analyst`)
- **Level**: {level} (`junior` / `medior` / `senior` / `lead`)
- **Language**: {language} (`cs` or `en`)
- **Remote mode**: {remote_mode}
- **Czech / European market context.** Realistic salary bands for {level} per the local market. Plausible employer names (made up but recognisable formats).

## Output (strict JSON only)

```json
{
  "title": "<job title>",
  "employer": "<plausible Czech / European company name>",
  "location": "<city or 'Remote'>",
  "remote_mode": "{remote_mode}",
  "level": "{level}",
  "domain": "{domain}",
  "must_have": ["<canonical skill name>", "..."],
  "nice_to_have": ["<canonical skill name>", "..."],
  "languages_required": [
    {"language": "Czech", "min_level": "C1"},
    {"language": "English", "min_level": "B2"}
  ],
  "raw_text": "<5-15 line plausible ad body in {language}>"
}
```

## Rules

- **Use canonical skill names** matching the taxonomy where possible: `Python`, `SQL`, `Power BI`, `React`, `Django`, `Docker`, `Kubernetes`, `Figma`, `Excel`, `Data Analysis`, `Stakeholder Management`, etc. Mixed casing follows the canonical form (e.g. `JavaScript`, not `javascript`).
- **Level matters.** Junior ads emphasise teachability + curiosity. Medior ads emphasise independent execution. Senior ads emphasise stakeholder leadership + system design. Lead ads emphasise people + roadmap ownership.
- **Don't over-stuff `must_have`.** 3-6 must-have entries is realistic. `nice_to_have` 2-5 entries.
- **Languages**: Czech ads default to `Czech C1` + `English B2`; English ads default to `English C1` + `Czech B2`. Adjust for the domain (e.g. SaaS company might list only English).
- **`raw_text`** should sound like a real Czech / European job listing — short paragraph about the role, bullet list of requirements, brief team / company line. Match the chosen `{language}`.
- **No invented salaries inside `raw_text`.** Keep the body skill-focused.
