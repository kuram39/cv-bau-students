# Extract structured profile from a candidate's CV

You analyse a CV (student, fresh graduate, career-changer, or experienced) and produce a single structured JSON profile.

The profile feeds an AI matching pipeline. Recruiters compare it against job ads. Honesty + missing-data discipline matter more than padded output — if a field is absent or ambiguous in the CV, set it to `null` or `[]` rather than guessing.

**Fairness — blind to demographics.** Extract skills, education and experience ONLY from what the CV states. Do NOT infer or weight competence from the candidate's name, gender, age, nationality, marital status, or photo. `name` is captured for display only and must never influence any other extracted field.

## Output (strict JSON only)

Return a single JSON object — no prose, no markdown fences. Schema:

```json
{
  "candidate_type": "student" | "career_changer" | "experienced",
  "language": "cs" | "en",
  "name": "<full name as it appears in CV header>" | null,
  "contact": "<email and/or phone, joined with ' / ' if both present>" | null,
  "location": "<city / region from CV header, e.g. 'Praha' or 'Brno'>" | null,
  "summary": "<elevator pitch / professional summary verbatim from CV, max 600 chars>" | null,
  "target_domains": ["<role family the candidate clearly targets, e.g. 'data-analyst', 'frontend-developer'>", "..."],
  "explicit_skills": ["<skill names exactly as listed in the CV's skills section>", "..."],
  "hard_skills": ["<measurable, course-learnable technologies / tools / certifications: e.g. 'Python', 'SQL', 'Power BI', 'AWS', 'CFA Level 1', 'Tableau'>", "..."],
  "soft_skills": ["<interpersonal / personality traits: e.g. 'communication', 'team leadership', 'problem solving', 'presentation skills', 'conflict resolution', 'time management', 'mentoring'>", "..."],
  "languages": [
    {"language": "English", "min_level": "B2"},
    {"language": "Czech", "min_level": "C2"}
  ],
  "education": [
    {
      "institution": "<institution name>",
      "field_of_study": "<field>",
      "degree": "Bachelor" | "Master" | "PhD" | "high_school" | null,
      "start_year": <int> | null,
      "end_year": <int> | null,
      "in_progress": true | false,
      "gpa": <float on the institution's scale, 1.0-4.0 or 1-5> | null,
      "awards": ["<award name>", "..."],
      "thesis_title": "<title>" | null,
      "thesis_summary": "<1-2 sentence description if present in CV>" | null
    }
  ],
  "work_experience": [
    {
      "employer": "<employer>",
      "role": "<role title>",
      "start_date": "<YYYY-MM>" | null,
      "end_date": "<YYYY-MM>" | null,
      "domain": "<industry / function>" | null,
      "is_brigada": true | false,
      "description": "<verbatim or close paraphrase from CV, max 400 chars>" | null
    }
  ],
  "school_projects": [
    {
      "title": "<project name>",
      "description": "<verbatim or close paraphrase, max 400 chars>" | null,
      "technologies": ["<tech 1>", "<tech 2>", "..."],
      "team_size": <int> | null
    }
  ],
  "open_source": ["<repo / contribution name + link>", "..."],
  "certifications": ["<certification name>", "..."],
  "hobbies": ["<hobby name>", "..."],
  "total_work_years": <float — sum of full-time-equivalent years across NON-brigada work_experience entries; brigády count at 0.3× each>,
  "most_recent_grad_year": <int — most recent education end_year, even if in_progress> | null,
  "studying_in_progress": true | false
}
```

## Classification rules — `candidate_type`

Apply in order. First matching rule wins.

1. **`studying_in_progress == true`** AND **`total_work_years < 2`** → `student`.
2. **`most_recent_grad_year >= currentYear - 1`** AND **`total_work_years < 2`** → `student` (fresh graduate).
3. **`total_work_years >= 2`** AND **the candidate's `summary` / `target_domains` clearly signal a target role family distinct from the majority of their work history** → `career_changer`.
4. Otherwise → `experienced`.

The summary / target-domain signal for career-changer must be explicit (e.g. the CV says *"hledám příležitost v oblasti dat"* while work history is hospitality). Don't infer career-change from vague phrasing — default to `experienced`.

## Field extraction rules

- **`summary`**: use the CV's own elevator pitch / "About me" / "Professional summary" section verbatim. If absent → `null`. Do NOT fabricate one.
- **`target_domains`**: extract only when the candidate explicitly names target roles (in summary, cover letter, or career-objective section). Otherwise → `[]`. Use lowercase hyphenated forms when possible (`data-analyst`, `frontend-developer`, `marketing-analyst`).
- **`name` / `contact` / `location`**: pull from CV header. `contact` = email and/or phone joined with " / " (`alice@example.com / +420 777 123 456`). `location` = city or city + region (`Praha`, `Brno-střed`); strip street addresses. All three → `null` when the CV redacts them.
- **`explicit_skills`**: copy from the CV's dedicated skills section verbatim. Don't infer skills from work descriptions here — that's the next pipeline stage's job. **Keep populating this for back-compat with the translator** even though `hard_skills` / `soft_skills` now exist.
- **`hard_skills`**: subset of skills that are measurable / course-learnable: programming languages, frameworks, tools, databases, certifications, methodologies (Scrum, Kanban), software (Excel, Power BI), CAD/CAM, machine operation, foreign-language proficiencies that aren't already in `languages`. Take from CV's skills section + infer from work descriptions when explicitly named ("vyvinul jsem dashboard v Power BI" → "Power BI"). Min 3 items expected; if CV has fewer, leave list short — the completion loop will ask.
- **`soft_skills`**: interpersonal + personality attributes the CV explicitly names or strongly implies through quoted achievements: "vedl jsem 5člený tým" → `team leadership`; "prezentoval výstupy klientovi" → `presentation skills`; "řešil eskalované stížnosti zákazníků" → `conflict resolution`. Don't fabricate from vague claims. Use English short phrases for consistency across CZ/EN CVs. Min 3 items expected.
- **`languages`**: use CEFR levels (A1-C2). When the CV says "native" → C2. When only "passive" / "active" → null `min_level`.
- **`education.in_progress`**: `true` when the CV shows "ongoing", "studuji", "currently", or `end_year` is in the future or absent without `end_year`.
- **`work_experience.is_brigada`**: `true` when the role is part-time + clearly student-job (waiter, retail, call-centre) AND the candidate was studying at the time.
- **`school_projects`**: include capstones, thesis projects, semester projects, hackathon entries, course projects. Don't include personal hobby projects unless directly relevant to a target domain.
- **`total_work_years`**: brigády contribute at 0.3 × duration. So 2 years McDonald's brigáda = 0.6 yrs. Internships (`is_brigada=false`, short duration) contribute at 1.0 × duration.
- **`most_recent_grad_year`**: highest `end_year` across education entries, even if `in_progress=true`. Pull from `start_year + standard_duration` if `end_year` is missing for in-progress study (Bachelor = 3 yrs, Master = 2 yrs).

## Skepticism principles (carry over from cv-estimator)

- CV is candidate-authored; treat upper-bound optimistic. Don't strengthen claims.
- Title alone ≠ ownership. A "Founder" of a school club is not a "CEO" for matching purposes.
- Hobbies / interests are weak signals — list them as-is, but the translator will weight them low downstream.
- If two CV sections contradict (e.g. summary says "5 years" but work_experience sums to 1.2), trust the structured calculation (`total_work_years`) and ignore the prose claim.
- `summary` is for matching against personal-fit, NOT for fabricating capabilities the work history doesn't show.

## Edge cases

- **No language section** → `languages: []`.
- **No skills section** → `explicit_skills: []`.
- **CV in Czech using Czech terms for roles** → keep them verbatim in `work_experience.role` (e.g. "Vývojář", "Praktikant"). Don't translate.
- **Multiple summary candidates** (header tagline + dedicated paragraph) → take the longer / more substantive one. If still ambiguous, pick the one that explicitly names target roles or aspirations.
- **Career-changer with brigády in target domain** (e.g. ops manager doing freelance data analysis on the side) → still `career_changer`. The brigády entries inform the translator later.

## CV TEXT (current year: {current_year})

{cv_text}
