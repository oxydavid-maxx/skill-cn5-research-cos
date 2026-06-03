"""Component 1 — end-to-end convergence loop DoD (deterministic, mock brains).

Two scenarios:
  * a run whose challenges keep resolving terminates with open-count -> 0
    (the convergence signal descends and the run stops, not loops forever);
  * a run with an UNANSWERABLE CRITICAL challenge escalates to a HUMAN gate
    (interrupt at human_pull) instead of spinning forever.
"""
from __future__ import annotations

from cn5_research_cos.brains.stubs import build_mock_brains
from cn5_research_cos.decision import convergence
from cn5_research_cos.graph import build_graph, compile_with_checkpoint
from cn5_research_cos.models import (AlbertChallenge, AuditResult, AuditVerdict,
                                     ChallengeStatus, Decision, ResearchState, Risk)


class _ConvergingAuditor:
    """Raises ONE challenge early, then answers it with evidence so the loop
    resolves it and the open-count trends to 0. After that, recommends synthesize.

    The challenge is tied to no issue and is LOW-impact (confidence 1) so it does
    not block emission once it is resolved (and would not even if still open)."""
    def audit(self, state: ResearchState) -> AuditResult:
        # Has the challenge already been recorded and resolved?
        live = convergence.unresolved_challenges(state)
        any_resolved = convergence.resolved_count(state) > 0
        if any_resolved:
            # converged: nothing left to challenge -> synthesize
            return AuditResult(verdict=AuditVerdict.exhausted, challenges=[],
                               premature_end_risk=Risk.low, research_drift_risk=Risk.low,
                               recommended_next_action=Decision.synthesize,
                               rationale="challenge resolved; converged")
        if live:
            # round 2: answer the open challenge with evidence -> upsert resolves it
            return AuditResult(
                verdict=AuditVerdict.continue_,
                challenges=[AlbertChallenge(
                    id="x", challenge="是否考慮過邊際成本?",
                    status=ChallengeStatus.answered, current_answer="是，已分析",
                    evidence_refs=["S-evid"], confidence=1)],
                premature_end_risk=Risk.low, research_drift_risk=Risk.low,
                recommended_next_action=Decision.continue_research,
                rationale="answering the open challenge")
        # round 1: raise the challenge
        return AuditResult(
            verdict=AuditVerdict.continue_,
            challenges=[AlbertChallenge(
                id="x", challenge="是否考慮過邊際成本?",
                status=ChallengeStatus.open, confidence=1)],
            premature_end_risk=Risk.low, research_drift_risk=Risk.low,
            recommended_next_action=Decision.continue_research,
            rationale="raising a challenge")


class _EscalatingAuditor:
    """Every round raises the SAME unanswerable CRITICAL challenge (high
    confidence) and marks it escalated_to_human + recommends a human pull, proving
    the loop hands it to a human gate rather than looping forever."""
    def audit(self, state: ResearchState) -> AuditResult:
        return AuditResult(
            verdict=AuditVerdict.rework,
            challenges=[AlbertChallenge(
                id="crit", challenge="這個決策需要 BU head 親自拍板嗎?",
                status=ChallengeStatus.escalated_to_human, confidence=5)],
            premature_end_risk=Risk.high, research_drift_risk=Risk.low,
            recommended_next_action=Decision.pull_human,
            rationale="critical, unanswerable by research -> escalate")


def _brains_with_auditor(auditor):
    b = build_mock_brains()
    b.auditor = auditor
    return b


def test_converging_run_terminates_open_to_zero():
    app = build_graph().compile()
    rs = ResearchState(run_id="conv", original_question="q", mode="interactive")
    out = app.invoke(
        {"research_state": rs, "base_dir": "runs", "now": "t0",
         "max_iterations": 12, "llm": "mock", "mode": "interactive",
         "enable_h6": False, "brains": _brains_with_auditor(_ConvergingAuditor())},
        config={"recursion_limit": 200},
    )
    final = out["research_state"]
    # the challenge was raised then resolved -> no unresolved challenges remain
    assert convergence.open_count(final) == 0
    assert convergence.resolved_count(final) == 1
    assert convergence.is_converged(final)
    # the convergence signal descended at some point (open-count went 1 -> 0)
    assert 0 in final.convergence_history
    assert max(final.convergence_history) >= 1


def test_unanswerable_critical_challenge_escalates_to_human_gate(tmp_path, monkeypatch):
    """No infinite loop: a CRITICAL escalated challenge + pull_human recommendation
    drives the loop to PAUSE at the human_pull gate (interrupt).

    The Brains bundle can't ride through the SqliteSaver (not serializable), so we
    monkeypatch the graph's brain factory to build our escalating-auditor bundle
    internally instead of injecting it through the checkpointed state dict."""
    import cn5_research_cos.graph as graph_mod
    monkeypatch.setattr(
        graph_mod, "build_brains",
        lambda *a, **k: _brains_with_auditor(_EscalatingAuditor()),
    )
    app, saver, conn = compile_with_checkpoint(tmp_path / "esc")
    try:
        rs = ResearchState(run_id="esc", original_question="q", mode="interactive")
        cfg = {"configurable": {"thread_id": "esc"}, "recursion_limit": 200}
        out = app.invoke(
            {"research_state": rs, "base_dir": str(tmp_path), "now": "t0",
             "max_iterations": 8, "llm": "mock", "mode": "interactive"},
            config=cfg,
        )
        # It paused at a human gate rather than spinning forever.
        assert "__interrupt__" in out
        snap = app.get_state(cfg)
        assert snap.next == ("human_pull",)
        final = snap.values["research_state"]
        # the critical challenge is recorded and human-blocked (escalated)
        assert convergence.escalated_count(final) == 1
        # an escalated high-impact challenge no longer blocks AI emission
        assert not convergence.has_unresolved_high_impact(final)
    finally:
        conn.close()
