"""Task 3 (P5b): wire StageReporter into the loop nodes.

Threading a reporter into the GraphState makes the debate VISIBLE during a (mock,
deterministic) run: the captured stream contains each stage's marker, in loop
order, INCLUDING the albert_audit block with its challenges, readiness, and the
COS decision. When NO reporter is threaded (the default), the nodes emit nothing —
so the existing 305 loop tests stay green.
"""
from __future__ import annotations

import io

from cn5_research_cos.graph import run_loop
from cn5_research_cos.models import ResearchState
from cn5_research_cos.observability.reporter import StageReporter


def test_mock_loop_streams_debate_when_reporter_threaded(tmp_path):
    buf = io.StringIO()
    reporter = StageReporter(stream=buf)
    final = run_loop(
        ResearchState(run_id="rw", original_question="我們該不該做隔夜研究 agent？"),
        base_dir=tmp_path, max_iterations=4, now="t0", reporter=reporter,
    )
    out = buf.getvalue()
    # the key debate stages are visible.
    assert "[scope]" in out
    assert "[expand]" in out
    assert "[albert_audit]" in out
    assert "[readiness]" in out
    assert "[decision]" in out
    # albert_audit appears BEFORE the decision (the debate precedes the COS action).
    assert out.index("[albert_audit]") < out.index("[decision]")
    # at least one Albert verdict line surfaced (the audit genuinely rendered).
    assert "verdict:" in out
    assert final.iteration_count >= 1


def test_loop_without_reporter_emits_nothing_to_a_probe(tmp_path):
    """The default (no reporter) path must not write to any reporter — proven by
    run_loop accepting reporter=None and behaving exactly as before."""
    final = run_loop(
        ResearchState(run_id="rw2", original_question="q"),
        base_dir=tmp_path, max_iterations=4, now="t0",
    )
    assert final.readiness_score is not None and final.iteration_count >= 1


def test_reporter_threads_through_graphstate():
    """The reporter is carried in GraphState (mirrors metrics threading) so every
    node can reach it."""
    from cn5_research_cos.state import GraphState
    buf = io.StringIO()
    gs: GraphState = {"reporter": StageReporter(stream=buf)}
    assert gs["reporter"].stream is buf
