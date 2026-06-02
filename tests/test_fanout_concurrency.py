"""Concurrent researcher fan-out tests (deterministic, NO real LLM).

P2 accel increment 2 replaces the SERIAL per-issue research with an
``asyncio.gather`` over the K selected issues, bounded by ``MAX_CONCURRENT``.
These tests inject a fake researcher that records concurrency (sleeps + a shared
in-flight counter) and assert:

* the K researchers OVERLAP (max-in-flight > 1) and never exceed MAX_CONCURRENT;
* results land in ``state.evidence`` in STABLE issue-id order (so the loop stays
  deterministic regardless of which task finished first);
* a researcher that RAISES does not break the others and does not leak a permit
  (the rest still complete, the loop still advances).
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from cn5_research_cos import graph as graph_mod
from cn5_research_cos.models import (Claim, EvidenceBundle, IssueStatus, IssueType,
                                     ResearchState, Source, SourceQuality, SourceType)
from cn5_research_cos.artifacts import issue_map


# --------------------------------------------------------------------------- #
# Concurrency-recording fake researcher
# --------------------------------------------------------------------------- #
class _ConcurrencyRecorder:
    """Shared across the fake brains; tracks max simultaneous in-flight research."""

    def __init__(self):
        self.lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.order_started: list[str] = []


class _SleepyResearcher:
    """A researcher whose async research sleeps so concurrent tasks overlap."""

    def __init__(self, rec: _ConcurrencyRecorder, *, sleep=0.05, fail_ids=()):
        self._rec = rec
        self._sleep = sleep
        self._fail = set(fail_ids)

    async def research_async(self, state, issue_id, *, pool=None):
        with self._rec.lock:
            self._rec.in_flight += 1
            self._rec.max_in_flight = max(self._rec.max_in_flight, self._rec.in_flight)
            self._rec.order_started.append(issue_id)
        try:
            await asyncio.sleep(self._sleep)
            if issue_id in self._fail:
                raise RuntimeError(f"boom for {issue_id}")
            node = state.issue_map.get(issue_id)
            title = node.title if node else issue_id
            return EvidenceBundle(
                query=title, issue_id=issue_id,
                sources=[Source(id=f"S-{issue_id}", title=title,
                                source_type=SourceType.secondary,
                                quality=SourceQuality.medium)],
                claims=[Claim(claim=f"c-{issue_id}", source_refs=[f"S-{issue_id}"],
                              confidence=3)],
            )
        finally:
            with self._rec.lock:
                self._rec.in_flight -= 1


class _PassThru:
    def review(self, bundle):
        return bundle

    def compress(self, bundle):
        return bundle


def _make_brains(rec, *, fail_ids=()):
    """Minimal brain bundle exposing just researcher/source_critic/compressor."""
    class _B:
        researcher = _SleepyResearcher(rec, fail_ids=fail_ids)
        source_critic = _PassThru()
        compressor = _PassThru()
    return _B()


def _state_with_open_issues(titles) -> ResearchState:
    rs = ResearchState(run_id="r", original_question="q")
    for t in titles:
        issue_map.add(rs, title=t, description=t, issue_type=IssueType.technical,
                      status=IssueStatus.open, now="t", impact=3, confidence=1)
    return rs


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_researchers_overlap_under_cap(monkeypatch):
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "3")
    rec = _ConcurrencyRecorder()
    rs = _state_with_open_issues(["i0", "i1", "i2", "i3", "i4", "i5"])
    selected = list(rs.issue_map.keys())  # all 6
    brains = _make_brains(rec)

    bundles = graph_mod.run_research_fanout(rs, selected, brains, now="t", llm="mock")

    # Concurrency really happened, bounded by the cap.
    assert rec.max_in_flight > 1, "researchers did not overlap (ran serially)"
    assert rec.max_in_flight <= 3, f"exceeded cap: {rec.max_in_flight}"
    # All issues researched, results in STABLE selected order (by issue id).
    assert [b.issue_id for b in bundles] == selected


def test_fanout_stable_order_regardless_of_finish(monkeypatch):
    """Even if later issues finish first, results come back in selected order."""
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "5")
    rec = _ConcurrencyRecorder()
    rs = _state_with_open_issues(["a", "b", "c", "d"])
    selected = list(rs.issue_map.keys())

    # Make earlier issues sleep LONGER so they finish LAST — order must still hold.
    class _VarSleep(_SleepyResearcher):
        async def research_async(self, state, issue_id, *, pool=None):
            # reverse the sleep by position so first-selected finishes last
            pos = selected.index(issue_id)
            self._sleep = 0.02 * (len(selected) - pos)
            return await super().research_async(state, issue_id, pool=pool)

    class _B:
        researcher = _VarSleep(rec)
        source_critic = _PassThru()
        compressor = _PassThru()

    bundles = graph_mod.run_research_fanout(rs, selected, _B(), now="t", llm="mock")
    assert [b.issue_id for b in bundles] == selected


def test_one_researcher_raises_others_complete(monkeypatch):
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "3")
    rec = _ConcurrencyRecorder()
    rs = _state_with_open_issues(["x0", "x1", "x2", "x3"])
    selected = list(rs.issue_map.keys())
    fail_id = selected[1]
    brains = _make_brains(rec, fail_ids=[fail_id])

    bundles = graph_mod.run_research_fanout(rs, selected, brains, now="t", llm="mock")

    # The failing issue is skipped; the other 3 succeed, still in stable order.
    got = [b.issue_id for b in bundles]
    assert fail_id not in got
    assert got == [i for i in selected if i != fail_id]
    assert len(got) == 3


class _SyncLoopBrain:
    """A *sync* critique brain (source_critic / compressor shape) that internally
    drives its own event loop via ``asyncio.run`` — exactly what the REAL brains do
    when routed through ``sdk_client``'s sync ``call_structured`` -> ``ClaudeSession``
    (``self._loop.run_until_complete(...)``) path.

    Contract this locks: such a brain must NEVER be invoked from inside the running
    fan-out event loop. If it is, ``asyncio.run()`` raises
    ``RuntimeError: asyncio.run() cannot be called from a running event loop`` —
    which is the deterministic stand-in for the live failure
    (``coroutine 'ClaudeSDKClient.connect' was never awaited`` + no structured
    output). With the fix (critique runs on the sync stack AFTER ``asyncio.gather``),
    these calls succeed and the bundles survive.
    """

    @staticmethod
    async def _noop():
        return None

    def review(self, bundle):
        asyncio.run(self._noop())  # illegal inside a running loop -> RuntimeError
        return bundle

    def compress(self, bundle):
        asyncio.run(self._noop())  # illegal inside a running loop -> RuntimeError
        return bundle


def test_sync_loop_critique_brains_run_outside_fanout_loop(monkeypatch):
    """REGRESSION (the gap that let the 0-evidence bug ship): the critique brains
    (source_critic, compressor) are SYNC and internally run their own event loop.
    They must execute OUTSIDE the async fan-out loop. If they ran inside it (the
    bug), ``asyncio.run`` would raise and every researcher's bundle would be dropped
    -> 0 evidence. With the fix, all bundles come back intact.
    """
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "3")
    rec = _ConcurrencyRecorder()
    rs = _state_with_open_issues(["q0", "q1", "q2"])
    selected = list(rs.issue_map.keys())

    class _B:
        researcher = _SleepyResearcher(rec)
        source_critic = _SyncLoopBrain()
        compressor = _SyncLoopBrain()

    bundles = graph_mod.run_research_fanout(rs, selected, _B(), now="t", llm="mock")

    # If the sync-loop critique brains ran inside the fan-out loop, asyncio.run
    # would raise and each task would be dropped via return_exceptions -> [].
    # The fix runs them on the sync stack after gather, so all bundles survive.
    assert [b.issue_id for b in bundles] == selected, (
        "critique brains were run inside the async fan-out loop "
        "(sync asyncio.run nested in a running loop) -> bundles dropped"
    )


def test_collect_folds_fanout_results_into_evidence(monkeypatch):
    """The graph node writes the gathered bundles into state.evidence in order."""
    monkeypatch.setenv("CN5_COS_MAX_CONCURRENT", "3")
    rec = _ConcurrencyRecorder()
    rs = _state_with_open_issues(["m0", "m1", "m2"])
    selected = list(rs.issue_map.keys())
    brains = _make_brains(rec)

    state = {"research_state": rs, "now": "t", "llm": "mock"}
    # Patch brain resolution + selection so the node uses our fake brains + ids.
    monkeypatch.setattr(graph_mod, "_brains", lambda s=None: brains)
    monkeypatch.setattr(graph_mod, "select_research_issues",
                        lambda state, brains, k=None: selected)

    out = graph_mod.node_research_fanout(state)
    results = out["worker_results"]
    assert [EvidenceBundle.model_validate(r).issue_id for r in results] == selected
