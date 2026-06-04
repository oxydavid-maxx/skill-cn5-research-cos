"""Audit gating: the Tier-2 deep audit runs ONLY at a deterministic gate.

Asserts (deterministic, counting fake deep_auditor):
  * NOT invoked on mid-loop continue/branch iterations;
  * IS invoked exactly once before synthesize/terminal (the H6 gate);
  * IS invoked before a HIGH-risk human_pull.
The Tier-1 sentinel (node_albert_audit) is unaffected — it runs every iteration.
"""
from langgraph.types import Command

from cn5_research_cos.graph import build_graph, compile_with_checkpoint
from cn5_research_cos.brains.stubs import build_mock_brains, AuditorStub
from cn5_research_cos.models import (Decision, IssueStatus, IssueType,
                                     ResearchState)
from cn5_research_cos.artifacts import issue_map


class CountingAuditor(AuditorStub):
    def __init__(self, counter):
        self.counter = counter

    def audit(self, state):
        self.counter["n"] += 1
        return super().audit(state)


def _brains_with_counting_deep(counter):
    b = build_mock_brains()
    b.deep_auditor = CountingAuditor(counter)
    return b


def test_deep_audit_not_called_mid_loop_but_once_at_terminal_gate():
    """Run the full mock loop to its synthesize stop. The deep audit must fire
    only at the terminal gate — exactly once — never on the many mid-loop
    continue/branch iterations the loop goes through first."""
    counter = {"n": 0}
    app = build_graph().compile()
    rs = ResearchState(run_id="ag", original_question="q", mode="interactive")
    out = app.invoke(
        {
            "research_state": rs, "base_dir": "runs", "now": "t0",
            "max_iterations": 8, "llm": "mock", "mode": "interactive",
            "enable_h6": False, "brains": _brains_with_counting_deep(counter),
            "assume_brief": True,  # P8: tests audit gating, not the H0 clarify gate
        },
        config={"recursion_limit": 200},
    )
    final = out["research_state"]
    # The loop ran multiple iterations (mid-loop continues/branches happened)...
    assert final.iteration_count >= 2
    # ...but the deep audit fired only at the gate: exactly once.
    assert counter["n"] == 1, f"deep audit ran {counter['n']}x (expected 1, gate-only)"
    assert final.deep_audit_count == 1


def test_deep_audit_runs_before_high_risk_pull(tmp_path):
    """A HIGH-risk pull routes through deep_audit before pausing at human_pull."""
    counter = {"n": 0}
    app, saver, conn = compile_with_checkpoint(tmp_path / "agp")
    try:
        rs = ResearchState(run_id="agp", original_question="q", mode="interactive")
        # High-impact intent + a queued request_pull → cos_decision -> pull; the
        # state is high-risk (multiple high-impact intents, no safe default).
        for i in range(2):
            issue_map.add(rs, title=f"intent{i}", description="d",
                          issue_type=IssueType.intent, status=IssueStatus.open,
                          now="t", impact=5)
        rs.steering_events.append({
            "kind": "request_pull", "context": "c", "why": "w",
            "options": ["A", "B", "C"], "ai_recommendation": "A",
            "default_if_no_response": "A", "consumed": False,
        })
        cfg = {"configurable": {"thread_id": "agp"}, "recursion_limit": 200}
        # Cannot inject a Brains object through the checkpointer (not JSON-
        # serializable); instead assert the deterministic deep_audit_count on the
        # state, which node_deep_audit increments only at the gate.
        out = app.invoke(
            {"research_state": rs, "base_dir": str(tmp_path), "now": "t0",
             "max_iterations": 6, "llm": "mock", "mode": "interactive",
             "assume_brief": True},  # P8: tests audit gating, not the H0 clarify gate
            config=cfg,
        )
        assert "__interrupt__" in out  # paused at the pull gate
        snap = app.get_state(cfg)
        assert snap.next == ("human_pull",)
        # The deep audit ran at the gate before the pause.
        assert snap.values["research_state"].deep_audit_count >= 1
    finally:
        conn.close()


def test_low_risk_pull_skips_deep_audit(tmp_path):
    """A LOW-risk pull goes straight to human_pull — no deep audit."""
    app, saver, conn = compile_with_checkpoint(tmp_path / "agl")
    try:
        rs = ResearchState(run_id="agl", original_question="q", mode="interactive")
        rs.default_research_priority = "ROI first"   # criterion known
        rs.fallback_behavior_if_human_unavailable = "proceed ROI"  # safe default
        issue_map.add(rs, title="one", description="d", issue_type=IssueType.roi,
                      status=IssueStatus.open, now="t", impact=3)
        # Seed a competitor issue so the sentinel audit is benign (continue / med
        # risk) — otherwise the mock auditor flags high premature_end_risk on a
        # competitor-less state, which would (correctly) make the pull HIGH-risk.
        issue_map.add(rs, title="competitor covered", description="d",
                      issue_type=IssueType.competitor, status=IssueStatus.open,
                      now="t", impact=3)
        rs.steering_events.append({
            "kind": "request_pull", "context": "c", "why": "w",
            "options": ["A", "B", "C"], "ai_recommendation": "A",
            "default_if_no_response": "A", "consumed": False,
        })
        cfg = {"configurable": {"thread_id": "agl"}, "recursion_limit": 200}
        out = app.invoke(
            {"research_state": rs, "base_dir": str(tmp_path), "now": "t0",
             "max_iterations": 6, "llm": "mock", "mode": "interactive",
             "assume_brief": True},  # P8: tests audit gating, not the H0 clarify gate
            config=cfg,
        )
        assert "__interrupt__" in out
        snap = app.get_state(cfg)
        assert snap.next == ("human_pull",)
        assert snap.values["research_state"].deep_audit_count == 0
    finally:
        conn.close()
