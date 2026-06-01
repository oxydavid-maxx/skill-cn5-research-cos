"""Readiness Board — a *derived* view of issue/challenge status (pure function).

Never stored authoritative; recomputed from issue_map + albert_challenge_map.
"""
from __future__ import annotations

from ..models import (BoardColumn, ChallengeStatus, IssueStatus, ResearchState)

ISSUE_TO_COLUMN: dict[IssueStatus, BoardColumn] = {
    IssueStatus.open: BoardColumn.pending,
    IssueStatus.researching: BoardColumn.pending,
    IssueStatus.partially_answered: BoardColumn.pending,
    IssueStatus.low_confidence: BoardColumn.pending,
    IssueStatus.answered: BoardColumn.answered,
    IssueStatus.blocked_by_internal_data: BoardColumn.blocked,
    IssueStatus.blocked_by_permission: BoardColumn.blocked,
    IssueStatus.blocked_by_decision: BoardColumn.blocked,
    IssueStatus.blocked_by_human: BoardColumn.needs_human,
}

CHALLENGE_TO_COLUMN: dict[ChallengeStatus, BoardColumn] = {
    ChallengeStatus.open: BoardColumn.pending,
    ChallengeStatus.answered: BoardColumn.answered,
    ChallengeStatus.needs_internal_data: BoardColumn.blocked,
    ChallengeStatus.needs_albert_decision: BoardColumn.needs_human,
    ChallengeStatus.needs_bu_judgment: BoardColumn.needs_human,
}


def derive_board(state: ResearchState) -> dict[BoardColumn, list[str]]:
    board: dict[BoardColumn, list[str]] = {col: [] for col in BoardColumn}
    for node in state.issue_map.values():
        col = ISSUE_TO_COLUMN.get(node.status, BoardColumn.pending)
        board[col].append(node.id)
    for ch in state.albert_challenge_map.values():
        col = CHALLENGE_TO_COLUMN.get(ch.status, BoardColumn.pending)
        board[col].append(ch.id)
    return board
