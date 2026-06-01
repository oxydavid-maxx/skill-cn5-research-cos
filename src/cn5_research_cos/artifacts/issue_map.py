"""Issue Map artifact operations (pure mutations on ResearchState.issue_map)."""
from __future__ import annotations

from ..models import IssueNode, IssueStatus, IssueType, ResearchState


def _next_id(state: ResearchState) -> str:
    return "I-%03d" % (len(state.issue_map) + 1)


def add(
    state: ResearchState,
    *,
    title: str,
    description: str,
    issue_type: IssueType,
    status: IssueStatus,
    now: str,
    parent_id: str | None = None,
    impact: int = 3,
    confidence: int = 2,
) -> IssueNode:
    node = IssueNode(
        id=_next_id(state),
        parent_id=parent_id,
        title=title,
        description=description,
        issue_type=issue_type,
        status=status,
        impact=impact,
        confidence=confidence,
        last_updated=now,
    )
    state.issue_map[node.id] = node
    return node


def get(state: ResearchState, issue_id: str) -> IssueNode | None:
    return state.issue_map.get(issue_id)


def set_status(state: ResearchState, issue_id: str, status: IssueStatus, *, now: str) -> None:
    node = state.issue_map[issue_id]
    node.status = status
    node.last_updated = now


def has_type(state: ResearchState, issue_type: IssueType) -> bool:
    return any(n.issue_type == issue_type for n in state.issue_map.values())
