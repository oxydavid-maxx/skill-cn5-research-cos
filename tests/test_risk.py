"""Unit tests for decision/risk.py — pure classify_pull(state, decision)."""
from cn5_research_cos.decision import risk
from cn5_research_cos.models import (AuditResult, AuditVerdict, Decision,
                                     IssueStatus, IssueType, ResearchState, Risk)
from cn5_research_cos.artifacts import issue_map


def _state() -> ResearchState:
    return ResearchState(run_id="r", original_question="q")


def test_low_when_safe_default_and_addressable():
    """A plain continue with no audit risk and addressable issues → low."""
    s = _state()
    issue_map.add(s, title="A", description="d", issue_type=IssueType.roi,
                  status=IssueStatus.open, now="t", impact=3)
    d = Decision.pull_human
    assert risk.classify_pull(s, d) == "low"


def test_high_when_premature_end_risk_high():
    s = _state()
    s.last_audit = AuditResult(verdict=AuditVerdict.continue_,
                               premature_end_risk=Risk.high)
    assert risk.classify_pull(s, Decision.pull_human) == "high"


def test_high_when_research_drift_risk_high():
    s = _state()
    s.last_audit = AuditResult(verdict=AuditVerdict.continue_,
                               research_drift_risk=Risk.high)
    assert risk.classify_pull(s, Decision.pull_human) == "high"


def test_high_when_criterion_unknown_and_all_high_impact_open_depend():
    """decision_criterion unknown AND every high-impact OPEN issue depends on it."""
    s = _state()
    # default_research_priority None == criterion unknown
    s.default_research_priority = None
    n = issue_map.add(s, title="big intent", description="d",
                      issue_type=IssueType.intent, status=IssueStatus.open,
                      now="t", impact=5)
    n.unknowns.append("decision_criterion")  # marks dependence on the criterion
    assert risk.classify_pull(s, Decision.pull_human) == "high"


def test_low_when_criterion_known():
    """If the criterion is known (default_research_priority set), not high on that path."""
    s = _state()
    s.default_research_priority = "ROI first"
    n = issue_map.add(s, title="big intent", description="d",
                      issue_type=IssueType.intent, status=IssueStatus.open,
                      now="t", impact=5)
    n.unknowns.append("decision_criterion")
    assert risk.classify_pull(s, Decision.pull_human) == "low"


def test_high_when_multiple_high_impact_intents_no_safe_default():
    """Multiple high-impact intent issues open with no fallback default → high."""
    s = _state()
    s.fallback_behavior_if_human_unavailable = None  # no safe default
    for i in range(2):
        issue_map.add(s, title=f"intent{i}", description="d",
                      issue_type=IssueType.intent, status=IssueStatus.open,
                      now="t", impact=5)
    assert risk.classify_pull(s, Decision.pull_human) == "high"


def test_low_when_multiple_high_impact_intents_but_safe_default_exists():
    s = _state()
    s.fallback_behavior_if_human_unavailable = "proceed with ROI priority"
    for i in range(2):
        issue_map.add(s, title=f"intent{i}", description="d",
                      issue_type=IssueType.intent, status=IssueStatus.open,
                      now="t", impact=5)
    assert risk.classify_pull(s, Decision.pull_human) == "low"
