"""Exhaustion stop model + plateau detector (pure, no I/O).

ADDRESSABLE  = the item is still self-answerable by more research.
RESIDUAL     = blocked on a human / internal-data / permission / decision.

terminal_eligible is True only when no ADDRESSABLE item remains AND all four
readiness targets are met (>= TARGET). When ``flags`` is supplied it is ANDed with
``anti_premature.all_done`` so the graph cannot terminal-stop with unmet prereqs.
The pure unit form (flags=None) skips the prereq gate.
"""
from __future__ import annotations

from ..models import IssueStatus, ResearchState
from . import anti_premature

TARGET = 4

ADDRESSABLE_STATUSES = {
    IssueStatus.open,
    IssueStatus.researching,
    IssueStatus.partially_answered,
    IssueStatus.low_confidence,
}


def has_addressable(state: ResearchState) -> bool:
    return any(n.status in ADDRESSABLE_STATUSES for n in state.issue_map.values())


def targets_met(state: ResearchState) -> bool:
    rs = state.readiness_score
    if rs is None:
        return False
    return min(
        rs.albert_challenge_readiness,
        rs.decision_readiness,
        rs.research_exhaustion_readiness,
        rs.human_bottleneck_clarity,
    ) >= TARGET


def terminal_eligible(state: ResearchState, flags: dict | None = None) -> bool:
    base = (not has_addressable(state)) and targets_met(state)
    if not base:
        return False
    if flags is not None:
        return anti_premature.all_done(flags)
    return True


def plateau(state: ResearchState, window: int = 2) -> bool:
    """True if the last ``window+1`` readiness sums are non-increasing (stalled)."""
    hist = [h.get("sum", 0) for h in state.readiness_history]
    if len(hist) < window + 1:
        return False
    tail = hist[-(window + 1):]
    return all(tail[i] >= tail[i + 1] for i in range(len(tail) - 1))
