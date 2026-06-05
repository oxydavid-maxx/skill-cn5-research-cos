import pytest
from pydantic import ValidationError
from cn5_research_cos.models import (IssueNode, IssueType, IssueStatus, AuditResult,
    AuditVerdict, ResearchState, EvidenceBundle, TaskCell, TaskGrid, CellStatus)


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


def test_research_state_has_p8_fields():
    rs = ResearchState(run_id="r", original_question="q")
    assert rs.decision_criterion is None
    assert rs.success_form is None
    assert rs.clarify_converged is False
    assert rs.task_grid is None


def test_task_grid_cells_and_coverage():
    grid = TaskGrid(axes=["vendor", "spec_group"])
    grid.cells["NXP|fabric"] = TaskCell(
        id="NXP|fabric", vendor="NXP", spec_group="fabric",
        objective="拉齊 NXP switch fabric 規格", status=CellStatus.open, impact=5)
    assert grid.open_high_impact_cells(min_impact=4)[0].id == "NXP|fabric"
    grid.cells["NXP|fabric"].status = CellStatus.covered
    assert grid.open_high_impact_cells(min_impact=4) == []


def test_taskcell_has_success_criteria_and_expected_sources():
    from cn5_research_cos.models import TaskCell, CellStatus
    c = TaskCell(id="NXP|fabric", vendor="NXP", spec_group="fabric", objective="o",
                 success_criteria=["packet_buffer", "vlan_table"],
                 expected_sources=["vendor datasheet PDF"])
    assert c.success_criteria == ["packet_buffer", "vlan_table"]
    assert c.expected_sources == ["vendor datasheet PDF"]
    # defaults
    d = TaskCell(id="x|y", vendor="x", spec_group="y", objective="o")
    assert d.success_criteria == [] and d.expected_sources == []
