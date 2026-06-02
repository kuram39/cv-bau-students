"""Tests for the selective adaptive-thinking flag on `llm.call_json`.

We mock `llm._client()` so no network is touched and we can assert exactly
which kwargs reach `messages.create` for `think=False` vs `think=True`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cv_bau_students import llm
from cv_bau_students.config import LLM_MAX_TOKENS, LLM_THINK_BUDGET, LLM_THINK_MAX_TOKENS


def _fake_message(*, text: str, with_thinking: bool = False):
    """Build a response object shaped like the SDK's Message."""
    blocks = []
    if with_thinking:
        # A thinking block must be ignored by the text-only concatenation.
        blocks.append(SimpleNamespace(type="thinking", thinking="...reasoning..."))
    blocks.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(content=blocks)


def _patched_client(message):
    client = MagicMock()
    client.messages.create.return_value = message
    return client


def test_default_call_has_no_thinking_kwarg():
    msg = _fake_message(text='{"ok": true}')
    client = _patched_client(msg)
    with patch.object(llm, "_client", return_value=client):
        out = llm.call_json("prompt")
    assert out == {"ok": True}
    _, kwargs = client.messages.create.call_args
    assert "thinking" not in kwargs
    assert kwargs["max_tokens"] == LLM_MAX_TOKENS


def test_think_true_ignored_when_master_switch_off():
    """With LLM_THINK_ENABLED off, think=True sends no thinking (the env opt-out
    CV_BAU_STUDENTS_THINK=0 path)."""
    msg = _fake_message(text='{"ok": true}')
    client = _patched_client(msg)
    with (
        patch.object(llm, "_client", return_value=client),
        patch.object(llm, "LLM_THINK_ENABLED", False),
    ):
        out = llm.call_json("prompt", think=True)
    assert out == {"ok": True}
    _, kwargs = client.messages.create.call_args
    assert "thinking" not in kwargs
    assert kwargs["max_tokens"] == LLM_MAX_TOKENS  # not bumped


def test_think_true_enables_budgeted_thinking_when_on():
    msg = _fake_message(text='{"ok": true}', with_thinking=True)
    client = _patched_client(msg)
    with (
        patch.object(llm, "_client", return_value=client),
        patch.object(llm, "LLM_THINK_ENABLED", True),
    ):
        out = llm.call_json("prompt", think=True)
    # Thinking block ignored; JSON parsed from the text block.
    assert out == {"ok": True}
    _, kwargs = client.messages.create.call_args
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": LLM_THINK_BUDGET}
    assert kwargs["max_tokens"] == LLM_THINK_MAX_TOKENS
    # The answer always has reserved room beyond the thinking cap.
    assert kwargs["max_tokens"] > kwargs["thinking"]["budget_tokens"]


def test_explicit_large_max_tokens_not_shrunk_by_think():
    msg = _fake_message(text="{}")
    client = _patched_client(msg)
    big = LLM_THINK_MAX_TOKENS + 5000
    with (
        patch.object(llm, "_client", return_value=client),
        patch.object(llm, "LLM_THINK_ENABLED", True),
    ):
        llm.call_json("prompt", max_tokens=big, think=True)
    _, kwargs = client.messages.create.call_args
    # think bumps only when the caller's budget is smaller than the floor.
    assert kwargs["max_tokens"] == big


def test_thinking_block_does_not_corrupt_json_parse():
    msg = _fake_message(text='{"a": 1, "b": 2}', with_thinking=True)
    client = _patched_client(msg)
    with patch.object(llm, "_client", return_value=client):
        out = llm.call_json("prompt", think=True)
    assert out == {"a": 1, "b": 2}
    assert json.dumps(out)  # round-trips


def test_model_override_threads_through():
    """An explicit model= reaches messages.create; default uses LLM_MODEL."""
    from cv_bau_students.config import LLM_MODEL

    msg = _fake_message(text="{}")
    client = _patched_client(msg)
    with patch.object(llm, "_client", return_value=client):
        llm.call_json("prompt", model="claude-haiku-4-5")
        _, kwargs = client.messages.create.call_args
        assert kwargs["model"] == "claude-haiku-4-5"

        llm.call_json("prompt")  # no override → default
        _, kwargs = client.messages.create.call_args
        assert kwargs["model"] == LLM_MODEL


def test_mechanical_model_respects_flag():
    """mechanical_model() returns the cheap tier only when LLM_TIER_MECHANICAL on."""
    from cv_bau_students import config

    with patch.object(config, "LLM_TIER_MECHANICAL", False):
        assert llm.mechanical_model() == config.LLM_MODEL
    with patch.object(config, "LLM_TIER_MECHANICAL", True):
        assert llm.mechanical_model() == config.LLM_MODEL_CHEAP


def _tool_use_message(payload: dict):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=payload)])


def test_schema_ignored_when_structured_flag_off():
    """schema= alone does nothing — the default text path is used."""
    from cv_bau_students import config

    msg = _fake_message(text='{"ok": true}')
    client = _patched_client(msg)
    with (
        patch.object(llm, "_client", return_value=client),
        patch.object(config, "LLM_STRUCTURED", False),
    ):
        out = llm.call_json("p", schema={"type": "object"})
    assert out == {"ok": True}
    _, kwargs = client.messages.create.call_args
    assert "tools" not in kwargs


def test_structured_flag_forces_tool_call_and_parses_input():
    from cv_bau_students import config

    client = _patched_client(_tool_use_message({"name": "Anna", "skills": ["SQL"]}))
    with (
        patch.object(llm, "_client", return_value=client),
        patch.object(config, "LLM_STRUCTURED", True),
    ):
        out = llm.call_json("p", schema={"type": "object"})
    assert out == {"name": "Anna", "skills": ["SQL"]}
    _, kwargs = client.messages.create.call_args
    assert kwargs["tool_choice"] == {"type": "tool", "name": "emit_result"}
    assert kwargs["tools"][0]["input_schema"] == {"type": "object"}


def test_structured_skipped_for_thinking_calls():
    """Forced tool-use is NOT combined with extended thinking (SDK rough edge)."""
    from cv_bau_students import config

    msg = _fake_message(text='{"ok": true}', with_thinking=True)
    client = _patched_client(msg)
    with (
        patch.object(llm, "_client", return_value=client),
        patch.object(llm, "LLM_THINK_ENABLED", True),
        patch.object(config, "LLM_STRUCTURED", True),
    ):
        out = llm.call_json("p", think=True, schema={"type": "object"})
    assert out == {"ok": True}
    _, kwargs = client.messages.create.call_args
    assert "tools" not in kwargs  # text+thinking path, not tool-use
    assert "thinking" in kwargs


def test_cache_prefix_ignored_when_flag_off():
    from cv_bau_students import config

    client = _patched_client(_fake_message(text="{}"))
    with (
        patch.object(llm, "_client", return_value=client),
        patch.object(config, "LLM_CACHE", False),
    ):
        llm.call_json("variable", cache_prefix="static body")
    _, kwargs = client.messages.create.call_args
    # Plain string content — no cache_control block.
    assert kwargs["messages"][0]["content"] == "variable"


def test_cache_prefix_builds_ephemeral_block_when_on():
    from cv_bau_students import config

    client = _patched_client(_fake_message(text="{}"))
    with (
        patch.object(llm, "_client", return_value=client),
        patch.object(config, "LLM_CACHE", True),
    ):
        llm.call_json("variable", cache_prefix="static body")
    _, kwargs = client.messages.create.call_args
    content = kwargs["messages"][0]["content"]
    assert content[0] == {
        "type": "text",
        "text": "static body",
        "cache_control": {"type": "ephemeral"},
    }
    assert content[1] == {"type": "text", "text": "variable"}


def test_no_text_block_raises_diagnostic_error():
    """Response with no text block → error names stop_reason + block types,
    not an empty 'First 500 chars' blank."""
    import pytest

    msg = SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="...")],
        stop_reason="max_tokens",
    )
    client = _patched_client(msg)
    with patch.object(llm, "_client", return_value=client):
        with pytest.raises(ValueError, match="no text to parse") as exc:
            llm.call_json("prompt")
    text = str(exc.value)
    assert "stop_reason='max_tokens'" in text
    assert "thinking" in text
