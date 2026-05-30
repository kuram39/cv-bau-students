"""LLM helpers for role-specific question generation + answer pre-fill.

Two functions:
  - `generate_role_questions(ad)` — called ONCE per ad. Produces the
    fixed 3-question template the whole applicant pool will answer.
  - `prefill_answers(profile, questions)` — called per candidate when
    they express interest. Drafts answers grounded in the CV.

Both are thin wrappers over `llm.call_json` + the prompts in
`prompts/role_specific_questions.md` and `prompts/prefill_role_answer.md`.
"""

from __future__ import annotations

import json

from cv_bau_students import llm
from cv_bau_students.models import (
    CandidateProfile,
    JobAd,
    PrefilledQuestion,
    RoleSpecificQuestionPydantic,
)


def generate_role_questions(ad: JobAd) -> list[RoleSpecificQuestionPydantic]:
    """One LLM call → the fixed 3-question template for this ad.

    Caller (`candidates.repo.ensure_role_questions`) persists the result
    once and replays it for every applicant, so this is only ever hit on
    the first interest in a given ad.
    """
    prompt = llm.render_prompt(
        "role_specific_questions",
        title=ad.title,
        employer=ad.employer or "",
        must_have=json.dumps(ad.must_have, ensure_ascii=False),
        nice_to_have=json.dumps(ad.nice_to_have, ensure_ascii=False),
        raw_text=ad.raw_text[:3000],  # cap to keep the prompt cheap
    )
    payload = llm.call_json(prompt)
    out: list[RoleSpecificQuestionPydantic] = []
    for q in payload.get("questions", [])[:3]:
        slot = (q.get("slot") or "").strip()
        text = (q.get("question_text") or "").strip()
        if not slot or not text:
            continue
        out.append(
            RoleSpecificQuestionPydantic(
                slot=slot,
                question_text=text,
                extract_hint=(q.get("extract_hint") or "").strip() or None,
            )
        )
    return out


def prefill_answers(
    profile: CandidateProfile,
    questions: list[RoleSpecificQuestionPydantic],
) -> list[PrefilledQuestion]:
    """One LLM call → draft answers grounded in the candidate's CV.

    Returns one `PrefilledQuestion` per input question, preserving order.
    Questions the CV can't answer come back with `prefilled_answer=None`.
    """
    if not questions:
        return []

    questions_payload = [
        {"slot": q.slot, "question_text": q.question_text, "extract_hint": q.extract_hint}
        for q in questions
    ]
    prompt = llm.render_prompt(
        "prefill_role_answer",
        profile_json=json.dumps(profile.model_dump(), ensure_ascii=False),
        questions_json=json.dumps(questions_payload, ensure_ascii=False),
        language=profile.language,
    )
    payload = llm.call_json(prompt)
    by_slot = {a.get("slot"): a for a in payload.get("answers", [])}

    out: list[PrefilledQuestion] = []
    for q in questions:
        ans = by_slot.get(q.slot, {})
        missing = bool(ans.get("missing", True))
        answer_text = (ans.get("answer") or "").strip()
        if missing or not answer_text:
            out.append(
                PrefilledQuestion(
                    slot=q.slot,
                    question_text=q.question_text,
                    extract_hint=q.extract_hint,
                    prefilled_answer=None,
                    prefilled_confidence=0.0,
                )
            )
        else:
            out.append(
                PrefilledQuestion(
                    slot=q.slot,
                    question_text=q.question_text,
                    extract_hint=q.extract_hint,
                    prefilled_answer=answer_text,
                    prefilled_confidence=float(ans.get("confidence", 0.5)),
                )
            )
    return out
