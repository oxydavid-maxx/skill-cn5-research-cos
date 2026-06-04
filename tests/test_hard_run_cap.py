"""Component C — hard run cap (cost + wall).

With real Albert (5–20 min/audit) a runaway loop can blow up cost/time. Today only
a SOFT budget warning exists. C adds a HARD cap: run_loop / run_auto accept
``max_cost_usd`` and ``max_wall_s`` (env ``CN5_COS_MAX_COST_USD`` /
``CN5_COS_MAX_WALL_S``). When ``metrics.total_usd`` >= the cost cap OR the wall
clock >= the wall cap, the loop HARD-STOPS after the current node, emits the
current findings (degraded-but-honest), and records the stop reason.

Deterministic: the cap predicate is pure; tests inject fake metrics + a fake
clock, never touching a real wall clock or LLM.
"""
from __future__ import annotations

import pytest

from cn5_research_cos.decision import run_cap
from cn5_research_cos.llm.metrics import RunMetrics


# --------------------------------------------------------------------------- #
# The pure cap predicate.
# --------------------------------------------------------------------------- #
def test_cost_cap_triggers_at_or_above_threshold():
    m = RunMetrics(total_usd=10.0)
    hit, reason = run_cap.cap_exceeded(m, max_cost_usd=10.0, max_wall_s=None,
                                       elapsed_s=0.0)
    assert hit is True
    assert "cost" in reason and "10" in reason


def test_cost_cap_not_triggered_below_threshold():
    m = RunMetrics(total_usd=9.99)
    hit, reason = run_cap.cap_exceeded(m, max_cost_usd=10.0, max_wall_s=None,
                                       elapsed_s=0.0)
    assert hit is False
    assert reason == ""


def test_wall_cap_triggers_at_or_above_threshold():
    m = RunMetrics(total_usd=0.0)
    hit, reason = run_cap.cap_exceeded(m, max_cost_usd=None, max_wall_s=600.0,
                                       elapsed_s=600.0)
    assert hit is True
    assert "wall" in reason


def test_no_caps_never_triggers():
    m = RunMetrics(total_usd=1e9)
    hit, reason = run_cap.cap_exceeded(m, max_cost_usd=None, max_wall_s=None,
                                       elapsed_s=1e9)
    assert hit is False


def test_caps_from_env(monkeypatch):
    monkeypatch.setenv("CN5_COS_MAX_COST_USD", "12.5")
    monkeypatch.setenv("CN5_COS_MAX_WALL_S", "900")
    cost, wall = run_cap.caps_from_args(None, None)
    assert cost == 12.5
    assert wall == 900.0


def test_explicit_args_override_env(monkeypatch):
    monkeypatch.setenv("CN5_COS_MAX_COST_USD", "12.5")
    cost, wall = run_cap.caps_from_args(5.0, 30.0)
    assert cost == 5.0
    assert wall == 30.0


def test_wall_cap_defaults_to_8h_when_unset(monkeypatch):
    monkeypatch.delenv("CN5_COS_MAX_WALL_S", raising=False)
    monkeypatch.delenv("CN5_COS_MAX_COST_USD", raising=False)
    cost, wall = run_cap.caps_from_args(None, None)
    assert wall == 28800.0
    assert cost is None


def test_explicit_wall_overrides_default():
    cost, wall = run_cap.caps_from_args(None, 60.0)
    assert wall == 60.0


def test_caps_absent_when_neither(monkeypatch):
    monkeypatch.delenv("CN5_COS_MAX_COST_USD", raising=False)
    monkeypatch.delenv("CN5_COS_MAX_WALL_S", raising=False)
    cost, wall = run_cap.caps_from_args(None, None)
    # Cost stays opt-in (None); wall falls back to the 8h default (P8 E1).
    assert cost is None
    assert wall == run_cap.DEFAULT_MAX_WALL_S


# --------------------------------------------------------------------------- #
# The cap published on a contextvar + consulted by the graph router.
# --------------------------------------------------------------------------- #
def test_cap_contextvar_round_trip():
    m = RunMetrics(total_usd=50.0)
    token = run_cap.publish_cap(m, max_cost_usd=10.0, max_wall_s=None,
                                clock=lambda: 0.0)
    try:
        assert run_cap.cap_hit_now() is True
    finally:
        run_cap.reset_cap(token)
    # after reset, no cap is active.
    assert run_cap.cap_hit_now() is False


def test_cap_contextvar_not_hit_when_under():
    m = RunMetrics(total_usd=1.0)
    token = run_cap.publish_cap(m, max_cost_usd=10.0, max_wall_s=None,
                                clock=lambda: 0.0)
    try:
        assert run_cap.cap_hit_now() is False
    finally:
        run_cap.reset_cap(token)


# --------------------------------------------------------------------------- #
# The loop hard-stops when the cap is hit (deterministic, fake metrics).
# --------------------------------------------------------------------------- #
def test_loop_hard_stops_at_cost_cap(tmp_path, monkeypatch):
    """A loop whose metrics already exceed the cost cap must HARD-STOP: route to
    the wrap-up (deep_audit -> review) instead of another research iteration, and
    record the cap stop reason. Driven with the mock brains so no LLM runs; the
    fake metrics are pre-loaded over the cap so the FIRST routing decision stops."""
    from cn5_research_cos.graph import run_loop
    from cn5_research_cos.models import ResearchState

    # Pre-load metrics OVER the cap so the cap predicate fires on the first route.
    metrics = RunMetrics(total_usd=999.0)
    rs = ResearchState(run_id="capped", original_question="q")
    final, used = run_loop(
        rs, base_dir=tmp_path, max_iterations=8, now="t0", llm="mock",
        metrics=metrics, max_cost_usd=10.0, return_metrics=True,
    )
    # The loop did NOT run to the iteration ceiling; it stopped early on the cap.
    assert final.iteration_count < 8
    # The cap stop reason is recorded on the state.
    assert final.stop_reason and "cap" in final.stop_reason.lower()
    # Findings are still emitted (the deliverable is produced even when capped).
    assert final.final_memo


def test_loop_runs_normally_under_cap(tmp_path):
    """A generous cap must NOT interfere with a normal run."""
    from cn5_research_cos.graph import run_loop
    from cn5_research_cos.models import ResearchState

    metrics = RunMetrics(total_usd=0.0)
    rs = ResearchState(run_id="uncapped", original_question="q")
    final = run_loop(rs, base_dir=tmp_path, max_iterations=3, now="t0", llm="mock",
                     metrics=metrics, max_cost_usd=1e9, max_wall_s=1e9)
    assert final.iteration_count >= 1
