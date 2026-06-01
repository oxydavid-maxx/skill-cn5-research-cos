from cn5_research_cos.models import (ResearchState, IssueType, IssueStatus,
    ChallengeStatus)
from cn5_research_cos.artifacts import issue_map, challenge_map


def test_issue_add_monotonic_ids_and_get():
    s = ResearchState(run_id="r", original_question="q")
    a = issue_map.add(s, title="A", description="da", issue_type=IssueType.roi,
                      status=IssueStatus.open, now="t1")
    b = issue_map.add(s, title="B", description="db", issue_type=IssueType.risk,
                      status=IssueStatus.open, now="t1")
    assert a.id == "I-001" and b.id == "I-002"
    assert issue_map.get(s, "I-001") is a


def test_issue_set_status_updates_timestamp():
    s = ResearchState(run_id="r", original_question="q")
    n = issue_map.add(s, title="A", description="d", issue_type=IssueType.roi,
                      status=IssueStatus.open, now="t1")
    issue_map.set_status(s, n.id, IssueStatus.answered, now="t2")
    got = issue_map.get(s, n.id)
    assert got.status == IssueStatus.answered and got.last_updated == "t2"


def test_has_type():
    s = ResearchState(run_id="r", original_question="q")
    assert issue_map.has_type(s, IssueType.competitor) is False
    issue_map.add(s, title="C", description="d", issue_type=IssueType.competitor,
                  status=IssueStatus.open, now="t1")
    assert issue_map.has_type(s, IssueType.competitor) is True


def test_challenge_add_monotonic_and_get():
    s = ResearchState(run_id="r", original_question="q")
    c1 = challenge_map.add(s, challenge="ch1", why_albert_would_ask="w",
                           status=ChallengeStatus.open)
    c2 = challenge_map.add(s, challenge="ch2", why_albert_would_ask="w",
                           status=ChallengeStatus.open)
    assert c1.id == "C-001" and c2.id == "C-002"
    assert challenge_map.get(s, "C-002") is c2
