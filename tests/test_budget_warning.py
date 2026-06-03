"""Task 8 (P5): soft budget warning — cumulative cost/iter/calls metrics line,
informational ONLY. The loop NEVER auto-truncates research on budget (no hard cap,
per the spec's cost-governance decision)."""
from cn5_research_cos.llm.metrics import RunMetrics
from cn5_research_cos.graph import run_loop
from cn5_research_cos.models import ResearchState


def test_summary_line_includes_cost_iter_calls():
    m = RunMetrics()
    m.record(cost_usd=1.04, wall_s=12.0, brain="researcher")
    m.record(cost_usd=0.50, wall_s=3.0, brain="scorer")
    line = m.summary_line(iteration=2)
    assert "cost=$1.54" in line
    assert "iter=2" in line
    assert "calls=2" in line


def test_summary_line_iteration_optional():
    # back-compat: no iteration arg still yields a valid line (no iter token).
    m = RunMetrics()
    m.record(cost_usd=0.1, wall_s=1.0)
    line = m.summary_line()
    assert "cost=$0.10" in line
    assert "calls=1" in line


def test_loop_never_caps_on_budget(tmp_path):
    # Even with a large accumulated cost, the loop runs to its natural stop and is
    # NOT truncated early by a budget cap (research completeness is preserved).
    big = RunMetrics()
    big.record(cost_usd=9999.0, wall_s=1.0, brain="researcher")
    final = run_loop(ResearchState(run_id="r", original_question="q"),
                     base_dir=tmp_path, max_iterations=8, now="t0",
                     metrics=big)
    # the mock loop converges by its deterministic stop (competitor + saturation),
    # NOT by any budget cap — it still completes a full convergence (>= 1 iter,
    # readiness scored) regardless of the $9999 already spent.
    assert final.readiness_score is not None
    assert final.iteration_count >= 1
