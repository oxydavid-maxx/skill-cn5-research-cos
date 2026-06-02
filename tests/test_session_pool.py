"""SessionPool routing tests (deterministic, NO real LLM).

The pool keeps ONE persistent ClaudeSession per (tools, schema-signature) key and
reuses it across calls, so repeated calls of the SAME brain across iterations pay
the ~12s session startup once. When a pool is installed via `use_session_pool`,
`call_structured` / `call_structured_websearch` transparently route through it,
so the real brains need no change.
"""
from __future__ import annotations

from cn5_research_cos.llm import sdk_client
from cn5_research_cos.llm.metrics import RunMetrics


class _FakeSession:
    """Stand-in for ClaudeSession: records construction + ask() calls."""

    constructed: list["_FakeSession"] = []

    def __init__(self, *, system, schema=None, allowed_tools=None, metrics=None,
                 model=None, **kw):
        self.system = system
        self.schema = schema
        self.allowed_tools = list(allowed_tools or [])
        self.metrics = metrics
        self.entered = False
        self.exited = False
        self.asks: list[tuple] = []
        _FakeSession.constructed.append(self)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True

    def ask(self, user, *, schema=None, brain="unknown"):
        self.asks.append((user, brain))
        # echo a schema-shaped dict so callers get a dict back
        return {"_brain": brain, "_n": len(self.asks)}


_SCHEMA_A = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
_SCHEMA_B = {"type": "object", "properties": {"b": {"type": "string"}}, "required": ["b"]}


def _install(monkeypatch):
    _FakeSession.constructed = []
    monkeypatch.setattr(sdk_client, "ClaudeSession", _FakeSession)


def test_pool_reuses_session_for_same_schema(monkeypatch):
    _install(monkeypatch)
    m = RunMetrics()
    with sdk_client.use_session_pool(metrics=m):
        sdk_client.call_structured("sysA", "u1", _SCHEMA_A)
        sdk_client.call_structured("sysA", "u2", _SCHEMA_A)
        sdk_client.call_structured("sysA", "u3", _SCHEMA_A)
    # exactly ONE session constructed for the 3 same-schema/no-tool calls
    assert len(_FakeSession.constructed) == 1
    sess = _FakeSession.constructed[0]
    assert len(sess.asks) == 3
    assert sess.exited is True  # torn down when the pool context exits


def test_pool_separates_by_schema_and_tools(monkeypatch):
    _install(monkeypatch)
    with sdk_client.use_session_pool(metrics=RunMetrics()):
        sdk_client.call_structured("sysA", "u", _SCHEMA_A)          # no-tool, schema A
        sdk_client.call_structured("sysB", "u", _SCHEMA_B)          # no-tool, schema B
        sdk_client.call_structured_websearch("sysW", "u", _SCHEMA_A)  # WebSearch, schema A
    # 3 distinct keys -> 3 sessions
    assert len(_FakeSession.constructed) == 3
    # the websearch one has the WebSearch tool
    tools = [s.allowed_tools for s in _FakeSession.constructed]
    assert ["WebSearch"] in tools


def test_no_pool_falls_back_to_one_shot(monkeypatch):
    """Without an active pool, call_structured uses the one-shot _query_structured
    path (back-compat) — never touches ClaudeSession."""
    _install(monkeypatch)

    async def _fake_query(**_kw):
        return {"text": "", "structured": {"a": "ok"}, "is_error": False}

    monkeypatch.setattr(sdk_client, "_query_structured", _fake_query)
    out = sdk_client.call_structured("sysA", "u", _SCHEMA_A)
    assert out == {"a": "ok"}
    assert _FakeSession.constructed == []  # pool never used


def test_pool_threads_metrics(monkeypatch):
    _install(monkeypatch)
    m = RunMetrics()
    with sdk_client.use_session_pool(metrics=m):
        sdk_client.call_structured("sysA", "u", _SCHEMA_A)
    # the constructed session got the metrics object (so .ask records into it)
    assert _FakeSession.constructed[0].metrics is m
