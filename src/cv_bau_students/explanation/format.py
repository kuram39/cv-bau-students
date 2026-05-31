"""Tolerant rendering helpers for the stored rationale string.

The rationale is persisted as a JSON string (verdict + strengths + gaps +
interview_prompts). A truncated LLM response — or a stale pre-format cache row
— can leave that string as invalid/cut-off JSON. The recruiter UI must never
dump raw JSON at the user, so `parse_reasoning` degrades gracefully: strict
`json.loads` first, then regex extraction of whatever fields survive.

Leaf module (stdlib only) so both `candidates.repo` and the UI can import it
without an import cycle.
"""

from __future__ import annotations

import json
import re

_FIELDS = ("strengths", "gaps", "interview_prompts")


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\").strip()


def _extract_array(key: str, raw: str) -> list[str]:
    m = re.search(r'"' + key + r'"\s*:\s*\[(.*?)(?:\]|$)', raw, re.S)
    if not m:
        return []
    items = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    return [_unescape(x) for x in items if x.strip()]


def _extract_verdict(raw: str) -> str:
    # Closed string first; then a truncated one (no closing quote → take rest).
    m = re.search(r'"verdict"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if m:
        return _unescape(m.group(1))
    m = re.search(r'"verdict"\s*:\s*"(.*)$', raw, re.S)
    return _unescape(m.group(1)) if m else ""


def parse_reasoning(raw: str | None) -> dict:
    """Best-effort structured parse. Always returns the 4 keys; tolerates
    truncated/invalid JSON by regex-extracting the fields that survive.
    `truncated` flags that strict JSON parsing failed (UI can hint at it)."""
    out: dict = {
        "verdict": "",
        "strengths": [],
        "gaps": [],
        "interview_prompts": [],
        "truncated": False,
    }
    if not raw or not raw.strip():
        return out
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            out["verdict"] = str(d.get("verdict", "")).strip()
            for k in _FIELDS:
                v = d.get(k) or []
                out[k] = [str(x) for x in v] if isinstance(v, list) else []
            return out
        # Valid JSON but not an object → treat the whole thing as the verdict.
        out["verdict"] = str(d).strip()
        return out
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: salvage whatever we can from a malformed/truncated string.
    out["truncated"] = True
    out["verdict"] = _extract_verdict(raw)
    for k in _FIELDS:
        out[k] = _extract_array(k, raw)
    if not out["verdict"] and not any(out[k] for k in _FIELDS):
        # Nothing JSON-like at all → show the raw text as the verdict.
        out["verdict"] = raw.strip()
    return out
