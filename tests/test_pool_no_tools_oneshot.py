"""No-tools structured calls inside a pool take the ONE-SHOT path (NO persistent
session) but STILL thread the pool's RunMetrics (deterministic, NO real LLM).

Root cause this guards: a no-tools `call_structured` routed through the pool's
persistent `ClaudeSession.ask` HANGS (`run_until_complete` stalls on the
orchestrator/synthesis/clarifier turn). The fix routes no-tools calls to
`SessionPool.ask_oneshot` — the same one-shot `query()` path used when no pool is
active — while still recording cost/latency into the pool's metrics. Tool-bearing
(WebSearch) calls legitimately keep using a persistent session.
"""
from __future__ import annotations

from cn5_research_cos.llm import sdk_client
from cn5_research_cos.llm.metrics import RunMetrics


class _FakeSession:
    """Stand-in for ClaudeSession: records construction. Should NOT be built for
    no-tools calls under the fix."""

    constructed: list["_FakeSession"] = []

    def __init__(self, *, system, schema=None, allowed_tools=None, metrics=None,
                 model=None, **kw):
        self.system = system
        self.schema = schema
        self.allowed_tools = list(allowed_tools or [])
        self.metrics = metrics
        _FakeSession.constructed.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def ask(self, user, *, schema=None, brain="unknown"):
        return {"_brain": brain}


_SCHEMA_A = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


def _install(monkeypatch):
    """Replace ClaudeSession (so a persistent session never spawns a process) and
    stub the one-shot async transport (so ask_oneshot never hits a real LLM)."""
    _FakeSession.constructed = []
    monkeypatch.setattr(sdk_client, "ClaudeSession", _FakeSession)

    async def _fake_query(**_kw):
        return {
            "text": "",
            "structured": {"a": "ok"},
            "is_error": False,
            "cost_usd": 0.01,
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }

    monkeypatch.setattr(sdk_client, "_query_structured", _fake_query)


def test_no_tools_call_in_pool_builds_no_persistent_session(monkeypatch):
    _install(monkeypatch)
    m = RunMetrics()
    with sdk_client.use_session_pool(metrics=m):
        out = sdk_client.call_structured("sysA", "u1", _SCHEMA_A)
        sdk_client.call_structured("sysA", "u2", _SCHEMA_A)
    # (a) NO persistent ClaudeSession was created for the no-tools calls.
    assert _FakeSession.constructed == []
    # ...and the pool's session map stayed empty.
    # (the one-shot path returns the structured dict)
    assert out == {"a": "ok"}


def test_no_tools_call_in_pool_threads_metrics(monkeypatch):
    _install(monkeypatch)
    m = RunMetrics()
    with sdk_client.use_session_pool(metrics=m):
        sdk_client.call_structured("sysA", "u1", _SCHEMA_A)
    # (b) the pool's RunMetrics got a record(...) — cost threaded via ask_oneshot.
    assert m.calls == 1
    assert m.total_usd == 0.01
    assert m.input_tokens == 100
    assert m.output_tokens == 20


def test_pool_sessions_map_empty_after_no_tools_call(monkeypatch):
    _install(monkeypatch)
    m = RunMetrics()
    with sdk_client.use_session_pool(metrics=m) as pool:
        sdk_client.call_structured("sysA", "u1", _SCHEMA_A)
        # the pool kept NO persistent session for the no-tools call.
        assert pool._sessions == {}


def test_websearch_call_in_pool_builds_persistent_session(monkeypatch):
    _install(monkeypatch)
    m = RunMetrics()
    with sdk_client.use_session_pool(metrics=m) as pool:
        sdk_client.call_structured_websearch("sysW", "u", _SCHEMA_A)
        # (c) a tool-bearing call DOES create a persistent session.
        assert len(pool._sessions) == 1
    # a ClaudeSession was constructed for the WebSearch call, with the tool.
    assert len(_FakeSession.constructed) == 1
    assert _FakeSession.constructed[0].allowed_tools == ["WebSearch"]
