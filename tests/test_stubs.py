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


def test_build_brains_unknown_raises():
    # P2b: "real" is now implemented; an UNKNOWN llm key still raises.
    with pytest.raises(NotImplementedError):
        build_brains("gpt-9000")


def test_issue_expander_never_seeds_competitor():
    s = ResearchState(run_id="r", original_question="q")
    nodes = build_brains("mock").issue_expander.expand(s, now="t")
    assert nodes  # seeded something
    assert not issue_map.has_type(s, IssueType.competitor)


def test_build_brains_real_smoke():
    """Constructs the real bundle + satisfies every Protocol WITHOUT calling an LLM."""
    from cn5_research_cos.brains import interfaces
    from cn5_research_cos.albert.simulator import RealAlbertSimulator
    from cn5_research_cos.brains.real import (RealCompressor, RealIssueExpander,
                                              RealResearcher, RealScorer,
                                              RealSkeptic, RealSourceCritic)

    b = build_brains("real")
    assert isinstance(b.issue_expander, RealIssueExpander)
    assert isinstance(b.researcher, RealResearcher)
    assert isinstance(b.source_critic, RealSourceCritic)
    assert isinstance(b.skeptic, RealSkeptic)
    assert isinstance(b.compressor, RealCompressor)
    assert isinstance(b.scorer, RealScorer)
    assert isinstance(b.auditor, RealAlbertSimulator)
    # Protocols satisfied across the whole bundle.
    assert isinstance(b.clarify_gate, interfaces.ClarifyGate)
    assert isinstance(b.brief_writer, interfaces.BriefWriter)
    assert isinstance(b.issue_expander, interfaces.IssueExpander)
    assert isinstance(b.supervisor, interfaces.Supervisor)
    assert isinstance(b.researcher, interfaces.Researcher)
    assert isinstance(b.source_critic, interfaces.SourceCritic)
    assert isinstance(b.compressor, interfaces.Compressor)
    assert isinstance(b.skeptic, interfaces.Skeptic)
    assert isinstance(b.auditor, interfaces.Auditor)
    assert isinstance(b.scorer, interfaces.Scorer)
