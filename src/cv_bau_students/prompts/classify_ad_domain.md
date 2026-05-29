# Classify a job ad's role domain

You read a job ad and return its canonical role-domain slug. The slug feeds the matcher's level-checklist join, so picking a domain that has no checklist row (or doesn't match the corpus convention) silently kills the bridge axis.

## Inputs

- **Ad title**: {title}
- **Employer**: {employer}
- **Ad body** (truncated to 1200 chars): {raw_text}

## Output (strict JSON only)

```json
{
  "domain": "<canonical slug — one of the known list below, or 'general' when none fit>",
  "confidence": <float 0.0 - 1.0>,
  "reason": "<one short clause explaining the choice>"
}
```

## Known canonical domains

Prefer one of these (matches `data/level_checklists.csv`):

- `data-analyst` — analytics, reporting, BI, dashboards, SQL-heavy
- `frontend-developer` — React / Vue / Angular / HTML+CSS / UI work
- `backend-developer` — server-side APIs in Python / Java / .NET / Go / PHP
- `marketing-analyst` — marketing performance, paid media analytics, CRM analytics
- `ux-designer` — UX research, product design, Figma, prototyping
- `project-manager` — coordination, delivery, scrum / agile / waterfall PM, product / programme management
- `controller` — financial control, FP&A, controlling, accounting + reporting
- `qa-engineer` — manual or automated test engineering

If the ad clearly fits none of the above (e.g. plumber, nurse, lawyer, sales representative, copywriter, mechanical engineer, supply chain analyst), return `"domain": "general"` — the bridge axis will then be N/A and the matcher relies on skill + personal fit alone.

## Rules

- **Title is the strongest signal.** "Senior Python Backend Engineer" → `backend-developer`. "UX Designer / Researcher" → `ux-designer`.
- **When the title is generic** ("Specialist", "Konzultant", "Analytik"), use the body — specifically the must-have tech list — to decide. "Analytik" + SQL + Tableau → `data-analyst`. "Analytik" + accounting reports → `controller`.
- **Default to `general`** when the body doesn't yield a clean match. False-confident classification is worse than honest `general` (which still scores skill + personal fit cleanly).
- **`confidence`** should reflect how clean the signal was. 0.9+ when title + body agree; 0.5-0.7 when only one supports; ≤0.4 when you're guessing.
- Czech ads stay in Czech for the body but classify into the English slug.
