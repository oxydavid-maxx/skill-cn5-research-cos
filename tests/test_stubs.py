from cn5_research_cos.models import ResearchState, IssueType, IssueStatus, AuditVerdict, Risk
from cn5_research_cos.artifacts import issue_map
from cn5_research_cos.brains import build_brains
import pytest


def test_auditor_raises_competitor_when_absent():
    s = ResearchState(run_id="r", original_question="q")
    issue_map.add(s, title="ROI", description="d", issue_type=IssueType.roi, status=IssueStatus.open, now="t")
    a = build_brains("mock").auditor.audit(s)
    assert a.verdict == AuditVerdict.rework and a.premature_end_risk == Risk.high and a.challenges


def test_brief_stub_sets_brief():
    s = ResearchState(run_id="r", original_question="AI overnight research?")
    build_brains("mock").brief_writer.write(s)
    assert s.research_brief


def test_build_brains_real_not_implemented():
    with pytest.raises(NotImplementedError):
        build_brains("real")


def test_issue_expander_never_seeds_competitor():
    s = ResearchState(run_id="r", original_question="q")
    nodes = build_brains("mock").issue_expander.expand(s, now="t")
    assert nodes  # seeded something
    assert not issue_map.has_type(s, IssueType.competitor)
