"""Task 3 (P5): deterministic 6-kind blocker labeling."""
from cn5_research_cos.synthesis.blockers import label_blockers
from cn5_research_cos.models import (
    AlbertChallenge, BlockerType, ChallengeStatus, IssueNode, IssueStatus,
    IssueType, ResearchState,
)


def _issue(iid, status, impact=4):
    return IssueNode(
        id=iid, title=iid, description=iid, issue_type=IssueType.technical,
        status=status, impact=impact, confidence=1,
    )


def _state_all_kinds() -> ResearchState:
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map = {
        "I-int": _issue("I-int", IssueStatus.blocked_by_internal_data),
        "I-perm": _issue("I-perm", IssueStatus.blocked_by_permission),
        "I-hum": _issue("I-hum", IssueStatus.blocked_by_human),
        "I-open": _issue("I-open", IssueStatus.open, impact=5),  # research
    }
    rs.albert_challenge_map = {
        "C-bu": AlbertChallenge(id="C-bu", challenge="BU?",
                                status=ChallengeStatus.needs_bu_judgment),
        "C-alb": AlbertChallenge(id="C-alb", challenge="decide?",
                                 status=ChallengeStatus.needs_albert_decision),
    }
    return rs


def test_labels_all_six_kinds():
    labels = label_blockers(_state_all_kinds())
    kinds = {l.blocker_type for l in labels}
    assert kinds == {
        BlockerType.internal_data, BlockerType.permission,
        BlockerType.human_judgment, BlockerType.research,
        BlockerType.bu_preference, BlockerType.albert_decision,
    }


def test_decision_blocked_issue_is_albert_decision():
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map = {"I-dec": _issue("I-dec", IssueStatus.blocked_by_decision)}
    labels = label_blockers(rs)
    assert any(l.blocker_type == BlockerType.albert_decision for l in labels)


def test_challenge_needs_internal_data_labeled_internal():
    rs = ResearchState(run_id="r", original_question="q")
    rs.albert_challenge_map = {
        "C-i": AlbertChallenge(id="C-i", challenge="need data",
                               status=ChallengeStatus.needs_internal_data),
    }
    labels = label_blockers(rs)
    assert any(l.blocker_type == BlockerType.internal_data for l in labels)


def test_answered_issue_and_resolved_challenge_not_blockers():
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map = {"I-done": _issue("I-done", IssueStatus.answered)}
    rs.albert_challenge_map = {
        "C-done": AlbertChallenge(id="C-done", challenge="ok",
                                  status=ChallengeStatus.resolved),
    }
    assert label_blockers(rs) == []


def test_blocker_carries_source_id():
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map = {"I-perm": _issue("I-perm", IssueStatus.blocked_by_permission)}
    labels = label_blockers(rs)
    assert labels[0].source_id == "I-perm"
