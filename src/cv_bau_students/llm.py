"""Anthropic API helper — single source of truth for LLM invocation.

Loads prompts from `prompts/*.md`, fills `{var}` placeholders via
`str.replace` (so JSON braces in the prompt body don't need escaping),
calls Claude (Opus 4.8), parses the JSON-only response. Determinism comes
from the frozen prompts — Opus 4.8 removed the `temperature` parameter.

Mirrors cv-estimator/llm.py — proven pattern, do not divergently
refactor.
"""

import json
import os
import re
from functools import lru_cache
from typing import Any

from cv_bau_students.config import (
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_THINK_BUDGET,
    LLM_THINK_ENABLED,
    LLM_THINK_MAX_TOKENS,
    PROMPTS_DIR,
)


@lru_cache(maxsize=1)
def _client():
    """Lazy Anthropic client — `from anthropic import Anthropic` takes
    ~60s on first import on this machine, so we defer it until an actual
    LLM call is made. Pytest collection + module import stay snappy.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")
    from anthropic import Anthropic

    # Bound a stalled/overloaded request: a single call can't hang the whole
    # seed for minutes. 300s comfortably exceeds legit generation (≤8K output
    # tokens ≈ ~2-3 min) but turns an API stall into a fast, visible error
    # instead of a silent multi-minute freeze. max_retries handles transient 529s.
    return Anthropic(api_key=key, timeout=300.0, max_retries=2)


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Read a prompt template from prompts/<name>.md."""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **kwargs: Any) -> str:
    """Load and fill a prompt template by replacing `{var}` placeholders.

    Uses plain `str.replace` (NOT `str.format`) so JSON braces in the
    prompt body don't need to be escaped as `{{` / `}}`.
    """
    out = load_prompt(name)
    for key, value in kwargs.items():
        out = out.replace("{" + key + "}", str(value))
    return out


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.MULTILINE)


def _strip_fences(text: str) -> str:
    """Extract JSON from optional ```json ... ``` fences."""
    m = _JSON_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def call_json(prompt: str, *, max_tokens: int = LLM_MAX_TOKENS, think: bool = False) -> dict:
    """Send a single-turn prompt expecting strict JSON output. Returns parsed dict.

    `think=True` enables extended thinking with an explicit `budget_tokens`
    cap — reserved for the interpretive calls (capability translation,
    recruiter reasoning) where extra reasoning measurably improves the
    judgement. The cheap extraction / classification calls leave it off (the
    default) to keep per-call cost down. Thinking blocks are billed as output,
    so thinking calls get a larger `max_tokens` (`LLM_THINK_MAX_TOKENS`); the
    `budget_tokens` cap reserves the remainder for the JSON answer so a
    long chain-of-thought can't starve the response.

    Only `text` blocks are concatenated below, so any thinking blocks in the
    response are ignored for parsing regardless of this flag.
    """
    kwargs: dict = {
        "model": LLM_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if think and LLM_THINK_ENABLED:
        # Explicit thinking budget (not adaptive): caps reasoning at
        # LLM_THINK_BUDGET so the remaining max_tokens is reserved for the JSON
        # answer. Adaptive thinking could consume the whole budget and leave no
        # answer (stop_reason=max_tokens, blocks=['thinking']).
        budget = max_tokens if max_tokens > LLM_THINK_MAX_TOKENS else LLM_THINK_MAX_TOKENS
        kwargs["max_tokens"] = budget
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": LLM_THINK_BUDGET}
    msg = _client().messages.create(**kwargs)
    raw = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
    payload = _strip_fences(raw)
    if not payload:
        # No text block at all → the useless "" error. Surface what actually
        # came back so the cause is diagnosable: stop_reason="max_tokens"
        # (budget too small / consumed by thinking), "refusal", or a response
        # carrying only non-text blocks.
        block_types = [getattr(b, "type", None) for b in msg.content]
        raise ValueError(
            "LLM returned no text to parse "
            f"(model={LLM_MODEL}, stop_reason={getattr(msg, 'stop_reason', None)!r}, "
            f"blocks={block_types}, max_tokens={kwargs['max_tokens']})."
        )
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON. First 500 chars:\n{payload[:500]}") from e
