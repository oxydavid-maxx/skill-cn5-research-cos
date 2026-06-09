from cn5_research_cos.observability import reporter as R
from cn5_research_cos.models import (ResearchState, EvidenceBundle, Claim, Source,
    IssueNode, IssueType, IssueStatus)


def _rs():
    return ResearchState(run_id="r", original_question="q")


def test_research_delta_counts_new_evidence():
    rs = _rs()
    rs.evidence.append(EvidenceBundle(query="NXP", claims=[Claim(claim="c")],
                                      sources=[Source(id="S1", title="t")]))
    first = R.render_research(rs)
    assert "+1" in first
    second = R.render_research(rs)
    assert "本站無動作" in second


def test_critique_delta_counts_new_counterargs():
    rs = _rs()
    n = IssueNode(id="I1", title="t", description="d", issue_type=IssueType.risk,
                  status=IssueStatus.open, impact=3, confidence=2)
    n.counterarguments = ["bias A"]
    rs.issue_map["I1"] = n
    assert "+1" in R.render_critique(rs)
    assert "本站無動作" in R.render_critique(rs)
