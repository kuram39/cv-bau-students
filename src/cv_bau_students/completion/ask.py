"""LLM #2 — turn a missing-fields list into 1–3 candidate-facing questions.

Uses `prompts/completion_questions.md`. Output validated against the
`CompletionRound` Pydantic model. Keeps the round_no separate so the
pipeline can stop after the second round per the design.
"""

import json
from datetime import datetime

from cv_bau_students import llm
from cv_bau_students.models import CandidateProfile, CompletionQuestion, CompletionRound


def ask(
    profile: CandidateProfile,
    missing_fields: list[str],
    *,
    round_no: int,
) -> CompletionRound:
    """Generate up to 3 targeted clarifying questions for the candidate."""
    if not missing_fields:
        return CompletionRound(round_no=round_no, questions=[])

    prompt = llm.render_prompt(
        "completion_questions",
        profile_json=json.dumps(profile.model_dump(), ensure_ascii=False),
        missing_fields=json.dumps(missing_fields, ensure_ascii=False),
        language=profile.language,
    )
    payload = llm.call_json(prompt)
    questions = [CompletionQuestion.model_validate(q) for q in payload.get("questions", [])][:3]
    return CompletionRound(round_no=round_no, questions=questions)


def fold_answers_into_profile(
    profile: CandidateProfile,
    completion: CompletionRound,
) -> CandidateProfile:
    """Merge the candidate's answers back into the profile.

    For free-text fields (`summary`, `target_domains`, brigada
    descriptions, thesis summaries) the answer text is written verbatim
    into the right slot. Structured answers (language levels, skill
    proofs) are written into the corresponding nested model with
    minimal massaging — the next extractor round (or downstream
    translator) does the heavy lifting.
    """
    updates: dict = {}
    education = [e.model_copy() for e in profile.education]
    work = [w.model_copy() for w in profile.work_experience]
    languages = [lng.model_copy() for lng in profile.languages]

    for q in completion.questions:
        answer = completion.answers.get(q.field)
        if not answer:
            continue
        field = q.field

        if field == "summary":
            updates["summary"] = answer
        elif field == "target_domains":
            updates["target_domains"] = [
                d.strip().lower().replace(" ", "-") for d in answer.split(",") if d.strip()
            ]
        elif field.startswith("brigada_description::"):
            _, employer, role = field.split("::", 2)
            for w_entry in work:
                if w_entry.employer == employer and w_entry.role == role:
                    w_entry.description = answer
                    break
            updates["work_experience"] = work
        elif field.startswith("thesis_summary::"):
            _, institution = field.split("::", 1)
            for edu in education:
                if edu.institution == institution and edu.thesis_title:
                    edu.thesis_summary = answer
                    break
            updates["education"] = education
        elif field.startswith("language_level::"):
            _, language_name = field.split("::", 1)
            for lng in languages:
                if lng.language == language_name:
                    lng.min_level = answer.strip().upper()
                    break
            updates["languages"] = languages
        elif field.startswith("skill_proof::"):
            _, skill = field.split("::", 1)
            existing = list(profile.school_projects)
            # Append the answer as a one-off project so the translator
            # has evidence for the skill on the next pass.
            from cv_bau_students.models import SchoolProjectItem

            existing.append(
                SchoolProjectItem(
                    title=f"Candidate-supplied example: {skill}",
                    description=answer,
                    technologies=[skill],
                )
            )
            updates["school_projects"] = existing

    if not updates:
        return profile
    updates_with_meta = {"_completion_applied_at": datetime.utcnow().isoformat(), **updates}
    updates_with_meta.pop("_completion_applied_at")  # don't poison the schema
    return profile.model_copy(update=updates)
