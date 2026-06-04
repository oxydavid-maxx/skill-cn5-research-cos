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

    # No-tools structured calls now take the one-shot path (ask_oneshot), so stub
    # the async transport so those calls never hit a real LLM.
    async def _fake_query(**_kw):
        return {
            "text": "", "structured": {"a": "ok"}, "is_error": False,
            "cost_usd": 0.01, "usage": {"input_tokens": 10, "output_tokens": 2},
        }

    monkeypatch.setattr(sdk_client, "_query_structured", _fake_query)


def test_pool_reuses_session_for_same_schema(monkeypatch):
    """A persistent session is reused across same-key calls — asserted via the
    TOOL-bearing (WebSearch) path, which is the path that legitimately uses a
    persistent session under the fix."""
    _install(monkeypatch)
    m = RunMetrics()
    with sdk_client.use_session_pool(metrics=m):
        sdk_client.call_structured_websearch("sysA", "u1", _SCHEMA_A)
        sdk_client.call_structured_websearch("sysA", "u2", _SCHEMA_A)
        sdk_client.call_structured_websearch("sysA", "u3", _SCHEMA_A)
    # exactly ONE session constructed for the 3 same-schema/same-tool calls
    assert len(_FakeSession.constructed) == 1
    sess = _FakeSession.constructed[0]
    assert len(sess.asks) == 3
    assert sess.exited is True  # torn down when the pool context exits


def test_pool_separates_by_schema_and_tools(monkeypatch):
    """Distinct (tools, schema) keys map to distinct persistent sessions —
    asserted with TOOL-bearing calls (the persistent-session path)."""
    _install(monkeypatch)
    with sdk_client.use_session_pool(metrics=RunMetrics()):
        sdk_client.call_structured_websearch("sysA", "u", _SCHEMA_A)  # WebSearch, schema A
        sdk_client.call_structured_websearch("sysB", "u", _SCHEMA_B)  # WebSearch, schema B
    # 2 distinct schema keys (same tool) -> 2 sessions
    assert len(_FakeSession.constructed) == 2
    # both carry the WebSearch tool
    tools = [s.allowed_tools for s in _FakeSession.constructed]
    assert tools == [["WebSearch"], ["WebSearch"]]


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
    """A no-tools call inside the pool records into the pool's RunMetrics — now via
    the one-shot ask_oneshot path (no persistent session is built for it)."""
    _install(monkeypatch)
    m = RunMetrics()
    with sdk_client.use_session_pool(metrics=m):
        sdk_client.call_structured("sysA", "u", _SCHEMA_A)
    # no persistent session for the no-tools call...
    assert _FakeSession.constructed == []
    # ...but the metrics still got a record (cost threaded through ask_oneshot).
    assert m.calls == 1
    assert m.total_usd == 0.01
