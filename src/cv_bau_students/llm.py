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

from cv_bau_students.config import LLM_MAX_TOKENS, LLM_MODEL, PROMPTS_DIR


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

    return Anthropic(api_key=key)


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


def call_json(prompt: str, *, max_tokens: int = LLM_MAX_TOKENS) -> dict:
    """Send a single-turn prompt expecting strict JSON output. Returns parsed dict."""
    msg = _client().messages.create(
        model=LLM_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
    payload = _strip_fences(raw)
    try:
        return json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON. First 500 chars:\n{payload[:500]}") from e
