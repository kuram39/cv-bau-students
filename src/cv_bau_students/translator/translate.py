"""LLM #3 — translate student / changer artefacts into experienced-language capabilities.

Uses `prompts/translate_capabilities.md`. Output validated against the
`TranslatedCapability` Pydantic model. Confidence floor + de-duplication
happen here so downstream scoring works against a clean list.
"""

import json
from functools import lru_cache

from cv_bau_students import llm
from cv_bau_students.config import TRANSLATOR_CONFIDENCE_FLOOR
from cv_bau_students.models import CandidateProfile, TranslatedCapability
from cv_bau_students.taxonomy.repo import resolve_skill_esco


def translate(profile: CandidateProfile) -> list[TranslatedCapability]:
    """Run the translator and return the validated, de-duped capability list.

    Capabilities below `TRANSLATOR_CONFIDENCE_FLOOR` are dropped — they
    add noise to the matcher without adding signal. De-duplication
    keeps the highest-confidence entry per `(skill, source_type)`.

    Each surviving capability is linked to the ESCO taxonomy via its
    `esco_term` (LLM-supplied English label) → `skill_id`, so the matcher
    can compare candidate skills against an occupation's expected set in a
    single namespace. Resolution falls back to `skill` when `esco_term` is
    missing; `skill_id` stays None when nothing maps.
    """
    raw = _translate_raw(
        candidate_type=profile.candidate_type,
        target_domains=tuple(profile.target_domains),
        profile_json=json.dumps(profile.model_dump(), ensure_ascii=False, sort_keys=True),
    )
    return [_link_to_esco(cap) for cap in _dedupe_and_floor(raw)]


def _link_to_esco(cap: TranslatedCapability) -> TranslatedCapability:
    """Attach the resolved ESCO skill_id (esco_term first, else skill name)."""
    match = resolve_skill_esco(cap.esco_term or cap.skill)
    if match is None:
        return cap
    return cap.model_copy(update={"skill_id": match[0]})


@lru_cache(maxsize=128)
def _translate_raw(
    *,
    candidate_type: str,
    target_domains: tuple[str, ...],
    profile_json: str,
) -> tuple[TranslatedCapability, ...]:
    """LRU-cached LLM call keyed on the canonical profile payload."""
    prompt = llm.render_prompt(
        "translate_capabilities",
        candidate_type=candidate_type,
        target_domains=json.dumps(list(target_domains), ensure_ascii=False),
        profile_json=profile_json,
    )
    # Interpretive call — adaptive thinking sharpens the skepticism rules
    # (confidence calibration, person ≠ role, sequential ≠ synthesis).
    payload = llm.call_json(prompt, think=True)
    items = payload.get("translated_capabilities", [])
    return tuple(TranslatedCapability.model_validate(item) for item in items)


def _dedupe_and_floor(
    items: tuple[TranslatedCapability, ...],
) -> list[TranslatedCapability]:
    """Apply confidence floor + per-(skill, source_type) max-confidence dedup."""
    filtered = [it for it in items if it.confidence >= TRANSLATOR_CONFIDENCE_FLOOR]
    best: dict[tuple[str, str], TranslatedCapability] = {}
    for it in filtered:
        key = (it.skill.lower().strip(), it.source_type)
        if key not in best or it.confidence > best[key].confidence:
            best[key] = it
    # Preserve the original LLM order to keep prompts deterministic.
    seen: set[tuple[str, str]] = set()
    out: list[TranslatedCapability] = []
    for it in filtered:
        key = (it.skill.lower().strip(), it.source_type)
        if key in seen:
            continue
        if best[key] is not it:
            continue
        out.append(it)
        seen.add(key)
    return out
