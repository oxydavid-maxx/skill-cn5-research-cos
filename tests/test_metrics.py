"""RunMetrics accumulation tests — deterministic, no LLM."""
from __future__ import annotations

from cn5_research_cos.llm.metrics import RunMetrics


def test_metrics_start_empty():
    m = RunMetrics()
    assert m.calls == 0
    assert m.total_usd == 0.0
    assert m.wall_clock_s == 0.0
    assert m.per_brain == {}


def test_metrics_record_accumulates():
    m = RunMetrics()
    m.record(cost_usd=0.001, wall_s=1.5, brain="expander",
             usage={"input_tokens": 100, "output_tokens": 20})
    m.record(cost_usd=0.002, wall_s=0.5, brain="scorer",
             usage={"input_tokens": 50, "output_tokens": 10})
    m.record(cost_usd=0.003, wall_s=2.0, brain="expander")
    assert m.calls == 3
    assert abs(m.total_usd - 0.006) < 1e-9
    assert abs(m.wall_clock_s - 4.0) < 1e-9
    assert m.per_brain == {"expander": 2, "scorer": 1}
    assert m.input_tokens == 150
    assert m.output_tokens == 30


def test_metrics_handles_none_cost():
    """A turn with no cost reported (e.g. cached/local) must not crash; counts
    the call but adds 0 to the dollar total."""
    m = RunMetrics()
    m.record(cost_usd=None, wall_s=1.0, brain="x")
    assert m.calls == 1
    assert m.total_usd == 0.0
    assert m.per_brain == {"x": 1}


def test_metrics_summary_line_format():
    m = RunMetrics()
    m.record(cost_usd=0.0123, wall_s=12.5, brain="a")
    m.record(cost_usd=0.0077, wall_s=7.5, brain="b")
    line = m.summary_line()
    # one-line cost/latency/calls summary
    assert "cost=$" in line
    assert "0.02" in line  # 0.0123+0.0077 = 0.0200 -> rounded
    assert "latency=" in line
    assert "20.0" in line  # 12.5 + 7.5
    assert "calls=2" in line
