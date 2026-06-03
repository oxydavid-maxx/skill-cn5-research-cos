"""Deterministic §4 blocker labeling (P5 Component, no LLM).

Every thing blocking the answer is one of 6 kinds. We read the live state's
issue statuses + open Albert-challenge statuses and map each to a ``BlockerType``:

  IssueStatus.blocked_by_internal_data  -> internal_data
  IssueStatus.blocked_by_permission     -> permission
  IssueStatus.blocked_by_human          -> human_judgment
  IssueStatus.blocked_by_decision       -> albert_decision
  ChallengeStatus.needs_internal_data   -> internal_data
  ChallengeStatus.needs_bu_judgment     -> bu_preference
  ChallengeStatus.needs_albert_decision -> albert_decision
  open high-impact issue (not blocked)  -> research

No LLM, no wall-clock, no I/O.
"""
from __future__ import annotations

from ..models import (Blocker, BlockerType, ChallengeStatus, IssueStatus,
                      ResearchState)

# How high an OPEN, unblocked issue's impact must be to count as a residual
# RESEARCH blocker worth surfacing in §4 (lower-impact open issues are noise).
RESEARCH_IMPACT_FLOOR = 3

_ISSUE_STATUS_TO_BLOCKER = {
    IssueStatus.blocked_by_internal_data: BlockerType.internal_data,
    IssueStatus.blocked_by_permission: BlockerType.permission,
    IssueStatus.blocked_by_human: BlockerType.human_judgment,
    IssueStatus.blocked_by_decision: BlockerType.albert_decision,
}

_CHALLENGE_STATUS_TO_BLOCKER = {
    ChallengeStatus.needs_internal_data: BlockerType.internal_data,
    ChallengeStatus.needs_bu_judgment: BlockerType.bu_preference,
    ChallengeStatus.needs_albert_decision: BlockerType.albert_decision,
}

_OPEN_ISSUE_STATUSES = (
    IssueStatus.open,
    IssueStatus.researching,
    IssueStatus.partially_answered,
    IssueStatus.low_confidence,
)


def label_blockers(state: ResearchState) -> list[Blocker]:
    """Map the live state's blocked issues + open challenges to labeled Blockers.

    Order is stable: issue-status blockers (in issue_map order), then research
    blockers (open high-impact issues), then challenge-status blockers (in
    challenge_map order). Answered issues and resolved/escalated-to-human
    challenges are NOT blockers.
    """
    blockers: list[Blocker] = []

    for iid, node in state.issue_map.items():
        btype = _ISSUE_STATUS_TO_BLOCKER.get(node.status)
        if btype is not None:
            blockers.append(Blocker(
                blocker_type=btype, description=node.title, source_id=iid,
            ))

    # Residual RESEARCH blockers: open, NOT-blocked, high-impact issues that
    # still need (addressable) research before the answer is complete.
    for iid, node in state.issue_map.items():
        if node.status in _OPEN_ISSUE_STATUSES and node.impact >= RESEARCH_IMPACT_FLOOR:
            blockers.append(Blocker(
                blocker_type=BlockerType.research, description=node.title,
                source_id=iid,
            ))

    for cid, ch in state.albert_challenge_map.items():
        btype = _CHALLENGE_STATUS_TO_BLOCKER.get(ch.status)
        if btype is not None:
            blockers.append(Blocker(
                blocker_type=btype, description=ch.challenge, source_id=cid,
                owner=ch.blocking_owner,
            ))

    return blockers
