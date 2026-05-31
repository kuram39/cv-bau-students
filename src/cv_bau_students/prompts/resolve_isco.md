You map a job advert to the single best ISCO-08 occupation code.

Job advert:
- Title: {title}
- Domain: {domain}
- Must-have skills: {must_have}

Candidate occupations (ESCO labels with their ISCO-08 group code):
{options}

Pick the ONE ISCO code from the list above that best matches the advert's
actual occupation. Judge by what the person would *do* day to day, not by
surface word overlap. If none of the candidates is a reasonable fit, return
null for the code.

Return STRICT JSON, nothing else:
{"isco_code": "2511", "occupation_label": "data analyst"}
or, when no candidate fits:
{"isco_code": null, "occupation_label": null}
