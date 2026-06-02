"""ClaudeSession lifecycle tests — deterministic, NO real LLM.

These monkeypatch the SDK's `ClaudeSDKClient` with a fake that records
connect/disconnect calls and returns scripted messages. They prove the
persistent-session contract that the P2 acceleration relies on:

* ONE connect for many `.ask()` calls (the whole point — pay ~12s startup once).
* Structured dict returned from the StructuredOutput tool block.
* Reconnect-once after a simulated transport error mid-run.
* Disconnect on context-manager exit.

The real speedup (fewer subprocess spawns) is only observable live; these tests
lock the *behavioral* contract that makes the speedup possible.
"""
from __future__ import annotations

import pytest

from cn5_research_cos.llm import sdk_client
from cn5_research_cos.llm.sdk_client import ClaudeSession, LLMUnavailableError


# --------------------------------------------------------------------------- #
# Fake SDK client + message blocks
# --------------------------------------------------------------------------- #
class _ToolBlock:
    """Mimics a ToolUseBlock(name="StructuredOutput", input={...})."""

    def __init__(self, payload: dict):
        self.name = "StructuredOutput"
        self.input = payload


class _TextBlock:
    def __init__(self, text: str):
        self.text = text


class _AssistantMessage:
    def __init__(self, content: list):
        self.content = content


class _ResultMessage:
    def __init__(self, *, cost: float | None = None, usage: dict | None = None,
                 is_error: bool = False):
        self.total_cost_usd = cost
        self.usage = usage or {}
        self.is_error = is_error


class FakeSDKClient:
    """Records connect/disconnect and replays scripted turns.

    ``script`` is a list of "turn" message-lists; each `.query()`+`.receive_response()`
    cycle pops the next turn. ``fail_on_turn`` (1-based) raises a transport error
    on that turn's receive to simulate a dead connection.
    """

    # class-level counters so the test can inspect across the (re)constructed
    # instances the session makes when it reconnects.
    instances: list["FakeSDKClient"] = []

    def __init__(self, options=None):
        self.options = options
        self.connect_calls = 0
        self.disconnect_calls = 0
        self._turn = 0
        FakeSDKClient.instances.append(self)

    # the session drives these via the event loop (they are async)
    async def connect(self):
        self.connect_calls += 1

    async def disconnect(self):
        self.disconnect_calls += 1

    async def query(self, user):
        self._last_user = user

    def receive_response(self):
        return self._gen()

    async def _gen(self):
        self._turn += 1
        script = type(self)._script
        fail_on = type(self)._fail_on_turn
        # global turn index across all instances (a reconnect makes a new client
        # but the "logical" turn keeps advancing)
        idx = type(self)._global_turn
        type(self)._global_turn += 1
        if fail_on is not None and idx + 1 == fail_on:
            raise RuntimeError("simulated transport drop")
        msgs = script[min(idx, len(script) - 1)]
        for m in msgs:
            yield m


def _install_fake(monkeypatch, script, *, fail_on_turn=None):
    FakeSDKClient.instances = []
    FakeSDKClient._script = script
    FakeSDKClient._fail_on_turn = fail_on_turn
    FakeSDKClient._global_turn = 0
    monkeypatch.setattr(sdk_client, "ClaudeSDKClient", FakeSDKClient)
    return FakeSDKClient


_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _turn(answer: str, *, cost=0.001, usage=None):
    return [
        _AssistantMessage([_ToolBlock({"answer": answer})]),
        _ResultMessage(cost=cost, usage=usage or {"input_tokens": 10, "output_tokens": 5}),
    ]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_session_connects_once_for_many_asks(monkeypatch):
    fake = _install_fake(monkeypatch, [_turn("a1"), _turn("a2"), _turn("a3")])
    with ClaudeSession(system="sys", schema=_SCHEMA) as s:
        r1 = s.ask("u1")
        r2 = s.ask("u2")
        r3 = s.ask("u3")
    # exactly ONE client constructed, ONE connect, results reused the same client
    assert len(fake.instances) == 1
    client = fake.instances[0]
    assert client.connect_calls == 1
    assert r1 == {"answer": "a1"}
    assert r2 == {"answer": "a2"}
    assert r3 == {"answer": "a3"}


def test_session_returns_structured_dict(monkeypatch):
    _install_fake(monkeypatch, [_turn("ok")])
    with ClaudeSession(system="sys", schema=_SCHEMA) as s:
        assert s.ask("u") == {"answer": "ok"}


def test_session_disconnects_on_exit(monkeypatch):
    fake = _install_fake(monkeypatch, [_turn("ok")])
    with ClaudeSession(system="sys", schema=_SCHEMA) as s:
        s.ask("u")
    assert fake.instances[0].disconnect_calls == 1


def test_session_reconnects_after_transport_error(monkeypatch):
    # turn 1 ok, turn 2 raises a transport error -> session must reconnect (a
    # second client) and the retry of turn 2 succeeds.
    fake = _install_fake(
        monkeypatch,
        [_turn("a1"), _turn("a2"), _turn("a2-retry")],
        fail_on_turn=2,
    )
    with ClaudeSession(system="sys", schema=_SCHEMA, max_attempts=3,
                       backoff_base=0.0) as s:
        r1 = s.ask("u1")
        r2 = s.ask("u2")  # first attempt fails, reconnects, retries
    assert r1 == {"answer": "a1"}
    assert r2 == {"answer": "a2-retry"}
    # a reconnect means a SECOND client was constructed
    assert len(fake.instances) == 2
    assert fake.instances[0].disconnect_calls == 1  # dead one was torn down
    assert fake.instances[1].connect_calls == 1


def test_session_raises_when_no_structured(monkeypatch):
    _install_fake(monkeypatch, [[_AssistantMessage([_TextBlock("no tool used")]),
                                 _ResultMessage()]])
    with ClaudeSession(system="sys", schema=_SCHEMA, max_attempts=1) as s:
        with pytest.raises(LLMUnavailableError):
            s.ask("u")


def test_session_records_metrics_when_provided(monkeypatch):
    from cn5_research_cos.llm.metrics import RunMetrics

    _install_fake(monkeypatch, [_turn("a1", cost=0.002), _turn("a2", cost=0.003)])
    m = RunMetrics()
    with ClaudeSession(system="sys", schema=_SCHEMA, metrics=m) as s:
        s.ask("u1", brain="expander")
        s.ask("u2", brain="scorer")
    assert m.calls == 2
    assert abs(m.total_usd - 0.005) < 1e-9
    assert m.per_brain["expander"] == 1
    assert m.per_brain["scorer"] == 1
