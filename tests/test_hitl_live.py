"""Live opt-in P3 tests (CN5_COS_LLM_TESTS=1). Skip cleanly without the opt-in.

Exercises the REAL brains end-to-end through the P3 surfaces. Short by design (a
couple of iterations) — NOT a long benchmark.
"""
import os

import pytest
from langgraph.types import Command

from cn5_research_cos.graph import (compile_with_checkpoint, run_auto)
from cn5_research_cos.models import (IssueStatus, IssueType, ResearchState)
from cn5_research_cos.artifacts import issue_map


@pytest.mark.llm
def test_run_auto_real_reaches_sensible_stop(tmp_path):
    """run-auto --llm real --max-iterations 2 reaches a sensible stop (terminal/
    synthesize/ceiling) or a high-risk hard-stop — with the real brains."""
    if os.environ.get("CN5_COS_LLM_TESTS") != "1":
        pytest.skip("set CN5_COS_LLM_TESTS=1 to run live LLM tests")

    rs = ResearchState(run_id="live-auto", original_question="Can AI do overnight research?")
    result = run_auto(rs, base_dir=tmp_path, max_iterations=2, now="t0", llm="real")
    final = result["state"]
    assert final.iteration_count >= 1
    assert final.readiness_score is not None
    assert final.last_audit is not None
    # Either it stopped with a reason, or it hard-stopped with an ask payload.
    if result["paused"]:
        assert result["ask"] is not None and "options" in result["ask"]
    else:
        assert result["stop_reason"]
        assert result["reason_kind"] in (
            "terminal_stop", "synthesize", "iteration_ceiling", "stopped")


@pytest.mark.llm
def test_interactive_interrupt_resume_round_trip_real(tmp_path):
    """One interactive interrupt -> resume round-trip with the REAL brains: a
    queued request_pull pauses the loop; Command(resume=...) continues from the
    checkpoint and records the human's choice."""
    if os.environ.get("CN5_COS_LLM_TESTS") != "1":
        pytest.skip("set CN5_COS_LLM_TESTS=1 to run live LLM tests")

    rs = ResearchState(run_id="live-int", original_question="Can AI do overnight research?",
                       mode="interactive")
    issue_map.add(rs, title="big intent", description="d", issue_type=IssueType.intent,
                  status=IssueStatus.open, now="t", impact=5)
    rs.steering_events.append({
        "kind": "request_pull", "context": "方向不明", "why": "高影響互斥",
        "options": ["A", "B", "C"], "ai_recommendation": "A",
        "default_if_no_response": "A", "consumed": False,
    })
    app, saver, conn = compile_with_checkpoint(tmp_path / "live-int")
    try:
        cfg = {"configurable": {"thread_id": "live-int"}, "recursion_limit": 100}
        out = app.invoke(
            {"research_state": rs, "base_dir": str(tmp_path), "now": "t0",
             "max_iterations": 3, "llm": "real", "mode": "interactive"},
            config=cfg,
        )
        assert "__interrupt__" in out
        snap = app.get_state(cfg)
        assert snap.next == ("human_pull",)
        out2 = app.invoke(Command(resume={"choice": "B", "answer": "競品先"}), config=cfg)
        rs2 = out2["research_state"]
        recorded = [e for e in rs2.steering_events if e.get("kind") == "pull_answer"]
        assert recorded and recorded[-1]["choice"] == "B"
    finally:
        conn.close()
