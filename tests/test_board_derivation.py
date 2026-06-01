from cn5_research_cos.models import (ResearchState, IssueType, IssueStatus,
    ChallengeStatus, BoardColumn)
from cn5_research_cos.artifacts import issue_map, challenge_map, readiness_board


def test_empty_all_empty():
    s = ResearchState(run_id="r", original_question="q")
    board = readiness_board.derive_board(s)
    assert set(board.keys()) == set(BoardColumn)
    assert all(v == [] for v in board.values())


def test_mixed_status_columns_and_backrefs():
    s = ResearchState(run_id="r", original_question="q")
    a = issue_map.add(s, title="answered", description="d", issue_type=IssueType.roi,
                      status=IssueStatus.answered, now="t")
    p = issue_map.add(s, title="pending", description="d", issue_type=IssueType.risk,
                      status=IssueStatus.open, now="t")
    b = issue_map.add(s, title="blocked-data", description="d",
                      issue_type=IssueType.internal_data,
                      status=IssueStatus.blocked_by_internal_data, now="t")
    h = issue_map.add(s, title="blocked-human", description="d", issue_type=IssueType.market,
                      status=IssueStatus.blocked_by_human, now="t")
    ch = challenge_map.add(s, challenge="needs decision", why_albert_would_ask="w",
                           status=ChallengeStatus.needs_albert_decision)

    board = readiness_board.derive_board(s)
    assert a.id in board[BoardColumn.answered]
    assert p.id in board[BoardColumn.pending]
    assert b.id in board[BoardColumn.blocked]
    assert h.id in board[BoardColumn.needs_human]
    # challenge needing albert decision surfaces as needs_human
    assert ch.id in board[BoardColumn.needs_human]
