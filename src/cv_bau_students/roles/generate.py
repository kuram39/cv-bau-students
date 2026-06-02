"""LLM helper for role-specific question generation (the BAU questionnaire).

  - `generate_role_questions(ad)` — called ONCE per ad. Produces the fixed
    3-question template the whole applicant pool answers. The AI value is the
    *questions* (surfacing skills the CV alone misses); answers are written by
    the candidate, not drafted by an LLM.

Thin wrapper over `llm.call_json` + `prompts/role_specific_questions.md`.
"""

from __future__ import annotations

import json

from cv_bau_students import llm
from cv_bau_students.models import JobAd, RoleSpecificQuestionPydantic


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
    payload = llm.call_json(prompt, model=llm.mechanical_model())
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
