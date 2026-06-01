"""sdk_client tests.

Deterministic part: no key -> has_api_key() False -> call_structured raises
LLMUnavailableError (never fabricates). Key-gated live smoke is @pytest.mark.llm.
"""
from __future__ import annotations

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


def test_call_structured_raises_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with pytest.raises(LLMUnavailableError):
        call_structured("sys", "user", _SCHEMA)


@pytest.mark.llm
def test_call_structured_live_smoke():
    if not has_api_key():
        pytest.skip("no ANTHROPIC_API_KEY; skipping live LLM smoke")
    out = call_structured(
        system="You answer with a single short string.",
        user="Reply with the word OK in the 'answer' field.",
        schema=_SCHEMA,
    )
    assert isinstance(out, dict) and "answer" in out
