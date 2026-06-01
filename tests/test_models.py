import pytest
from pydantic import ValidationError
from cn5_research_cos.models import (IssueNode, IssueType, IssueStatus, AuditResult,
    AuditVerdict, ResearchState, EvidenceBundle)


def test_issue_round_trip():
    n = IssueNode(id="I-001", title="t", description="d", issue_type=IssueType.competitor,
                  status=IssueStatus.open, impact=3, confidence=2)
    assert IssueNode.model_validate_json(n.model_dump_json()) == n


def test_bounds_and_enum():
    with pytest.raises(ValidationError):
        IssueNode(id="x", title="t", description="d", issue_type=IssueType.roi,
                  status=IssueStatus.open, impact=9, confidence=1)
    with pytest.raises(ValidationError):
        IssueNode(id="x", title="t", description="d", issue_type="bad",
                  status=IssueStatus.open, impact=1, confidence=1)


def test_state_has_r2_fields():
    s = ResearchState(run_id="r", original_question="q")
    # R2 preflight + brief fields exist and default empty/None
    assert s.research_brief is None and s.forbidden_directions == []
    assert ResearchState.model_validate_json(s.model_dump_json()) == s


def test_audit_r2_fields():
    a = AuditResult(verdict=AuditVerdict.exhausted)
    assert a.questions_albert_would_ask_next == [] and a.readiness_score_delta == 0 and a.degraded is False


def test_evidence_coverage_gaps():
    e = EvidenceBundle(query="q")
    assert e.coverage_gaps == []
