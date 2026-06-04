"""Deterministic interrupt/resume round-trip over the REAL LangGraph path.

CRITICAL (prior-increment lesson): a live-only event-loop/interrupt bug can pass
mocked tests. So this test exercises the ACTUAL LangGraph interrupt() + Command()
+ SqliteSaver mechanism offline, with mock BRAINS (not a mocked graph):

  * a gate node calls the real ``interrupt(payload)`` mid-loop;
  * ``app.invoke`` returns a state carrying ``__interrupt__`` and ``app.get_state``
    shows the run paused AT the gate node (NOT finished);
  * ``app.invoke(Command(resume=...))`` continues FROM the checkpoint (the
    iteration_count does not reset) and the resumed value flows into the state.
"""
from langgraph.types import Command

from cn5_research_cos.graph import compile_with_checkpoint
from cn5_research_cos.models import (Decision, IssueStatus, IssueType,
                                     ResearchState)
from cn5_research_cos.artifacts import issue_map


def _state_that_pulls() -> ResearchState:
    rs = ResearchState(run_id="hp", original_question="q", mode="interactive")
    # A queued H4 steering event of kind request_pull forces cos_decision -> pull.
    issue_map.add(rs, title="big intent", description="d",
                  issue_type=IssueType.intent, status=IssueStatus.open,
                  now="t", impact=5)
    rs.steering_events.append({
        "kind": "request_pull",
        "context": "方向不明：要先做 ROI 還是競品?",
        "why": "兩條高影響路徑互斥，需要人類定奪",
        "options": ["A: ROI 先", "B: 競品先", "C: 兩者並行"],
        "ai_recommendation": "A",
        "impact_per_option": {"A": "聚焦商業價值", "B": "防守競品", "C": "資源分散"},
        "default_if_no_response": "A",
        "consumed": False,
    })
    return rs


def test_interrupt_pauses_then_resumes_from_checkpoint(tmp_path):
    run_dir = tmp_path / "hp"
    app, saver, conn = compile_with_checkpoint(run_dir)
    try:
        cfg = {"configurable": {"thread_id": "hp"}, "recursion_limit": 100}
        init = {
            "research_state": _state_that_pulls(),
            "base_dir": str(tmp_path), "now": "t0", "max_iterations": 6,
            "llm": "mock", "mode": "interactive",
            "assume_brief": True,  # P8: tests human_pull interrupt/resume, not the H0 clarify gate
        }
        out1 = app.invoke(init, config=cfg)

        # The real interrupt fired: state carries __interrupt__ and the run is
        # PAUSED at the human_pull gate (not finished).
        assert "__interrupt__" in out1
        interrupts = out1["__interrupt__"]
        assert interrupts, "expected a pending interrupt"
        payload = interrupts[0].value
        assert payload["options"] == ["A: ROI 先", "B: 競品先", "C: 兩者並行"]
        assert payload["ai_recommendation"] == "A"
        assert "default_if_no_response" in payload

        snap = app.get_state(cfg)
        assert snap.next == ("human_pull",), f"paused node = {snap.next}"
        paused_iter = snap.values["research_state"].iteration_count
        assert paused_iter >= 1

        # Resume FROM the checkpoint (not a restart): the human picks option B.
        out2 = app.invoke(Command(resume={"choice": "B", "answer": "競品先"}), config=cfg)

        rs2 = out2["research_state"]
        # The resumed value flowed into the state as a recorded steering decision.
        recorded = [e for e in rs2.steering_events if e.get("kind") == "pull_answer"]
        assert recorded, "resumed answer must be recorded as a steering_event"
        assert recorded[-1]["choice"] == "B"
        # Continued from the checkpoint: iteration_count did not reset to 0.
        assert rs2.iteration_count >= paused_iter
        # The request_pull event was consumed (not re-fired on the next round).
        pending = [e for e in rs2.steering_events
                   if e.get("kind") == "request_pull" and not e.get("consumed")]
        assert not pending
    finally:
        conn.close()
