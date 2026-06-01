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
from cn5_research_cos.llm.sdk_client import LLMUnavailableError, call_structured, has_api_key


_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
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
