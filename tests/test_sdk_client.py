"""sdk_client tests.

The Agent SDK authenticates via the Claude subscription (the spawned `claude`
CLI) — an ANTHROPIC_API_KEY is NOT required. So `call_structured` does NOT
pre-gate on env vars; it attempts the SDK and only raises LLMUnavailableError
if the call genuinely fails (never fabricates). Live tests are opt-in via
CN5_COS_LLM_TESTS=1 (they cost a few cents; default-skip keeps the suite fast).
"""
from __future__ import annotations

import os

import pytest

from cn5_research_cos.llm import sdk_client
from cn5_research_cos.llm.sdk_client import (LLMUnavailableError, call_structured,
                                            call_structured_websearch, has_api_key)


_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


def test_has_api_key_reads_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    assert has_api_key() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert has_api_key() is True


def test_call_structured_no_env_gate(monkeypatch):
    """No env key present -> the wrapper must NOT pre-gate; it attempts the SDK
    (which auths via the subscription) and returns the structured result."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    async def _fake_query(**_kw):
        return {"text": "", "structured": {"answer": "ok"}, "is_error": False}

    monkeypatch.setattr(sdk_client, "_query_structured", _fake_query)
    assert call_structured("sys", "user", _SCHEMA) == {"answer": "ok"}


def test_call_structured_raises_on_no_structured(monkeypatch):
    """If the SDK returns no StructuredOutput block, raise (never fabricate)."""
    async def _fake_query(**_kw):
        return {"text": "oops", "structured": None, "is_error": True}

    monkeypatch.setattr(sdk_client, "_query_structured", _fake_query)
    with pytest.raises(LLMUnavailableError):
        call_structured("sys", "user", _SCHEMA)


@pytest.mark.llm
def test_call_structured_live_smoke():
    if os.environ.get("CN5_COS_LLM_TESTS") != "1":
        pytest.skip("set CN5_COS_LLM_TESTS=1 to run live LLM tests")
    out = call_structured(
        system="You answer with a single short string.",
        user="Reply with the word OK in the 'answer' field.",
        schema=_SCHEMA,
    )
    assert isinstance(out, dict) and "answer" in out


# --------------------------------------------------------------------------- #
# websearch path (P2b)
# --------------------------------------------------------------------------- #
def test_call_structured_websearch_passes_websearch_tool(monkeypatch):
    """The websearch path must hand the SDK allowed_tools=['WebSearch'] and
    max_turns>=4 (tool cycle), while keeping the SAME MCP isolation. We assert
    those args by capturing what `_query_structured` is called with — and the
    structured result still flows through unchanged."""
    captured = {}

    async def _fake_query(**kw):
        captured.update(kw)
        return {"text": "", "structured": {"findings": [{"claim": "x"}]}, "is_error": False}

    monkeypatch.setattr(sdk_client, "_query_structured", _fake_query)
    out = call_structured_websearch("sys", "search the web", _SEARCH_SCHEMA)
    assert out == {"findings": [{"claim": "x"}]}
    assert captured.get("allowed_tools") == ["WebSearch"]
    assert captured.get("max_turns", 0) >= 4


def test_call_structured_websearch_raises_on_no_structured(monkeypatch):
    async def _fake_query(**_kw):
        return {"text": "no tools used", "structured": None, "is_error": False}

    monkeypatch.setattr(sdk_client, "_query_structured", _fake_query)
    with pytest.raises(LLMUnavailableError):
        call_structured_websearch("sys", "user", _SEARCH_SCHEMA)


@pytest.mark.llm
def test_call_structured_websearch_live(monkeypatch):
    if os.environ.get("CN5_COS_LLM_TESTS") != "1":
        pytest.skip("set CN5_COS_LLM_TESTS=1 to run live LLM tests")
    out = call_structured_websearch(
        system="You research a topic using WebSearch and return findings with sources.",
        user=("Search the web for the latest news about NVIDIA and return at least one "
              "finding with its source URL in the 'findings' array."),
        schema=_SEARCH_SCHEMA,
    )
    assert isinstance(out, dict)
    findings = out.get("findings") or []
    assert len(findings) >= 1, f"expected >=1 web finding, got {out!r}"
    assert any(f.get("claim") for f in findings)
