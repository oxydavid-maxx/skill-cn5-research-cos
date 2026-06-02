"""Async session path + bounded multi-session pool tests (deterministic, NO real LLM).

Increment 2 (P2 accel) adds:

* ``ClaudeSession.ask_async`` — runs ONE turn on the caller's running event loop
  (no private-loop ``run_until_complete``), so K researchers can ``asyncio.gather``.
* ``AsyncSessionPool`` — up to ``MAX_CONCURRENT`` LIVE sessions PER
  ``(model, tools, schema)`` key, guarded by an ``asyncio.Semaphore``. Concurrent
  callers get their own live `claude`; an idle session is reused, else (under the
  cap) a new one connects, else the caller waits on the semaphore. A session is
  ALWAYS returned to the pool — on success AND on exception — so a failed call
  never leaks a permit / deadlocks.

These mock ``ClaudeSDKClient`` with a counting fake that tracks how many clients
are simultaneously "live" (connected, not disconnected) so we can assert the cap
is never exceeded under concurrency.
"""
from __future__ import annotations

import asyncio

import pytest

from cn5_research_cos.llm import sdk_client
from cn5_research_cos.llm.sdk_client import LLMUnavailableError


# --------------------------------------------------------------------------- #
# Counting fake SDK client (tracks max concurrent live connections)
# --------------------------------------------------------------------------- #
class _ToolBlock:
    def __init__(self, payload):
        self.name = "StructuredOutput"
        self.input = payload


class _Assistant:
    def __init__(self, content):
        self.content = content


class _Result:
    def __init__(self, *, cost=0.001, usage=None, is_error=False):
        self.total_cost_usd = cost
        self.usage = usage or {"input_tokens": 1, "output_tokens": 1}
        self.is_error = is_error


class CountingFake:
    """Fake ClaudeSDKClient; a shared class-level live-counter records how many
    instances are connected (and not yet disconnected) at any moment. ``turn_delay``
    lets a turn yield control (await sleep) so concurrent gather overlaps and the
    live-counter peaks under real concurrency."""

    live = 0
    max_live = 0
    connect_total = 0
    turn_delay = 0.0
    answer = "ok"
    fail_first_turn = False  # one-shot transport failure on the first turn served

    def __init__(self, options=None):
        self.options = options
        self._connected = False
        self._served = 0

    async def connect(self):
        type(self).connect_total += 1
        self._connected = True
        type(self).live += 1
        type(self).max_live = max(type(self).max_live, type(self).live)

    async def disconnect(self):
        if self._connected:
            self._connected = False
            type(self).live -= 1

    async def query(self, user):
        self._last = user

    def receive_response(self):
        return self._gen()

    async def _gen(self):
        self._served += 1
        if type(self).turn_delay:
            await asyncio.sleep(type(self).turn_delay)
        if type(self).fail_first_turn and self._served == 1:
            # consume the one-shot so a retry succeeds
            type(self).fail_first_turn = False
            raise RuntimeError("simulated transport drop")
        yield _Assistant([_ToolBlock({"answer": type(self).answer})])
        yield _Result()


_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _install(monkeypatch, **attrs):
    CountingFake.live = 0
    CountingFake.max_live = 0
    CountingFake.connect_total = 0
    CountingFake.turn_delay = 0.0
    CountingFake.answer = "ok"
    CountingFake.fail_first_turn = False
    for k, v in attrs.items():
        setattr(CountingFake, k, v)
    monkeypatch.setattr(sdk_client, "ClaudeSDKClient", CountingFake)


# --------------------------------------------------------------------------- #
# ask_async
# --------------------------------------------------------------------------- #
def test_ask_async_returns_structured(monkeypatch):
    _install(monkeypatch, answer="from-async")

    async def _run():
        async with sdk_client.ClaudeSession.open_async(system="sys", schema=_SCHEMA) as s:
            return await s.ask_async("u", brain="t")

    out = asyncio.run(_run())
    assert out == {"answer": "from-async"}


def test_ask_async_records_metrics(monkeypatch):
    from cn5_research_cos.llm.metrics import RunMetrics

    _install(monkeypatch)
    m = RunMetrics()

    async def _run():
        async with sdk_client.ClaudeSession.open_async(
            system="sys", schema=_SCHEMA, metrics=m
        ) as s:
            await s.ask_async("u1", brain="b")
            await s.ask_async("u2", brain="b")

    asyncio.run(_run())
    assert m.calls == 2
    assert m.per_brain["b"] == 2


# --------------------------------------------------------------------------- #
# Bounded multi-session pool
# --------------------------------------------------------------------------- #
def test_pool_never_exceeds_max_concurrent(monkeypatch):
    """K=8 concurrent acquires with cap=3 — never more than 3 live sessions for one key."""
    _install(monkeypatch, turn_delay=0.02)
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "3")

    async def _run():
        pool = sdk_client.AsyncSessionPool()
        try:
            async def _one(i):
                async with pool.acquire(
                    system="sys", schema=_SCHEMA, allowed_tools=None, model=None
                ) as sess:
                    return await sess.ask_async(f"u{i}", brain="r")

            results = await asyncio.gather(*[_one(i) for i in range(8)])
            return results
        finally:
            await pool.aclose()

    results = asyncio.run(_run())
    assert len(results) == 8
    assert all(r == {"answer": "ok"} for r in results)
    # The hard ceiling: never more than MAX_CONCURRENT live sessions at once.
    assert CountingFake.max_live <= 3, f"max_live={CountingFake.max_live} exceeded cap 3"
    # And concurrency really happened (more than one ran at once) — otherwise the
    # cap assertion is vacuous.
    assert CountingFake.max_live >= 2


def test_pool_releases_session_on_exception(monkeypatch):
    """A raising ask_async must still return the permit/session (no leak)."""
    _install(monkeypatch)
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "1")

    async def _run():
        pool = sdk_client.AsyncSessionPool()
        try:
            # First acquire: force a failure inside the with-block.
            with pytest.raises(RuntimeError):
                async with pool.acquire(
                    system="sys", schema=_SCHEMA, allowed_tools=None, model=None
                ) as sess:
                    raise RuntimeError("boom in body")
            # If the permit leaked, this second acquire (cap=1) would hang forever.
            async with pool.acquire(
                system="sys", schema=_SCHEMA, allowed_tools=None, model=None
            ) as sess:
                return await sess.ask_async("u", brain="r")
        finally:
            await pool.aclose()

    out = asyncio.wait_for(_run(), timeout=5)
    res = asyncio.run(out)
    assert res == {"answer": "ok"}


def test_pool_reuses_idle_sessions(monkeypatch):
    """Many SEQUENTIAL acquires for one key reuse idle sessions: connect called
    <= cap times, not once per acquire."""
    _install(monkeypatch)
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "3")

    async def _run():
        pool = sdk_client.AsyncSessionPool()
        try:
            for i in range(10):
                async with pool.acquire(
                    system="sys", schema=_SCHEMA, allowed_tools=None, model=None
                ) as sess:
                    await sess.ask_async(f"u{i}", brain="r")
        finally:
            await pool.aclose()

    asyncio.run(_run())
    # 10 sequential acquires, but each releases before the next -> 1 live session
    # reused throughout. connect_total must be <= cap (here exactly 1).
    assert CountingFake.connect_total <= 3
    assert CountingFake.connect_total == 1


def test_pool_rate_limit_retry_no_deadlock(monkeypatch):
    """A simulated transport error on one task is retried (reconnect) WITHOUT
    leaking a permit / deadlocking the pool; all tasks still complete."""
    _install(monkeypatch, fail_first_turn=True, turn_delay=0.0)
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "2")

    async def _run():
        pool = sdk_client.AsyncSessionPool()
        try:
            async def _one(i):
                async with pool.acquire(
                    system="sys", schema=_SCHEMA, allowed_tools=None, model=None,
                    max_attempts=3, backoff_base=0.0,
                ) as sess:
                    return await sess.ask_async(f"u{i}", brain="r")

            return await asyncio.gather(*[_one(i) for i in range(4)])
        finally:
            await pool.aclose()

    results = asyncio.run(asyncio.wait_for(_run(), timeout=10))
    assert len(results) == 4
    assert all(r == {"answer": "ok"} for r in results)
    assert CountingFake.max_live <= 2
