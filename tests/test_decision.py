from cn5_research_cos.models import (ResearchState, IssueType, IssueStatus, ReadinessScore,
    AuditResult, AuditVerdict, Decision)
from cn5_research_cos.artifacts import issue_map
from cn5_research_cos.decision import exhaustion, gate, anti_premature, branch_budget


def _ready(s, v):
    s.readiness_score = ReadinessScore(albert_challenge_readiness=v, decision_readiness=v,
        research_exhaustion_readiness=v, human_bottleneck_clarity=v, should_continue=v < 4, reason="")


def test_addressable_blocks_terminal():
    s = ResearchState(run_id="r", original_question="q")
    issue_map.add(s, title="A", description="d", issue_type=IssueType.roi, status=IssueStatus.open, now="t")
    _ready(s, 5); assert exhaustion.terminal_eligible(s) is False


def test_all_residual_ready_terminal():
    s = ResearchState(run_id="r", original_question="q")
    issue_map.add(s, title="A", description="d", issue_type=IssueType.internal_data,
                  status=IssueStatus.blocked_by_internal_data, now="t")
    _ready(s, 4); assert exhaustion.terminal_eligible(s) is True


def test_plateau():
    s = ResearchState(run_id="r", original_question="q")
    s.readiness_history = [{"sum": 8}, {"sum": 8}, {"sum": 8}]
    assert exhaustion.plateau(s, window=2) is True


def test_gate_refuses_degraded():
    s = ResearchState(run_id="r", original_question="q")
    s.last_audit = AuditResult(verdict=AuditVerdict.exhausted, degraded=True)
    assert gate.assert_audit_ran(s, Decision.terminal_stop) == Decision.continue_research


def test_anti_premature_blocks_until_all_true():
    flags = {k: True for k in anti_premature.PREREQS}; flags["counterargument_pass"] = False
    assert anti_premature.all_done(flags) is False
    flags["counterargument_pass"] = True
    assert anti_premature.all_done(flags) is True


def test_branch_budget_decays_and_refuses():
    b = branch_budget.Budget(breadth=4, depth=1)
    b2 = branch_budget.spend(b)
    assert b2.breadth == 2 and b2.depth == 0
    assert branch_budget.can_branch(b2) is False
