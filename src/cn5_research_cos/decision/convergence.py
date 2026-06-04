"""Adversarial-convergence tracking (P4b Component 1, pure / deterministic).

The audit loop must CONVERGE: challenges carry forward across rounds (via
``challenge_map.upsert``) and move ``open -> answered -> resolved`` (or
``escalated_to_human`` / a human-blocked status). This module reads the challenge
map and answers:

  * how many challenges are still UNRESOLVED (open/answered/needs-*),
  * whether the open-count trend is descending (a convergence signal),
  * whether the run has CONVERGED (no unresolved, or all-remaining human-blocked),
  * the ``albert_challenge_readiness`` score from the resolved-vs-total ratio,
  * whether a HIGH-IMPACT challenge is still unresolved (the emission gate refuses
    a memo while one remains — but NOT once it has been escalated to a human).

No LLM, no wall-clock, no I/O.
"""
from __future__ import annotations

from ..models import ChallengeStatus, Decision, ResearchState

# Statuses that count as DONE (no further AI work moves them).
_RESOLVED_STATUSES = (
    ChallengeStatus.resolved,
)
# Statuses that are terminal-for-AI because a human now owns them. They do NOT
# count as "resolved" but they DO let the run converge (no AI progress remains).
_HUMAN_BLOCKED_STATUSES = (
    ChallengeStatus.escalated_to_human,
    ChallengeStatus.needs_internal_data,
    ChallengeStatus.needs_albert_decision,
    ChallengeStatus.needs_bu_judgment,
)

# Confidence at/above which a challenge is "high-impact" (the auditor maps its
# low/medium/high onto 1/3/5; >= HIGH_IMPACT_CONF means a serious challenge whose
# unresolved state must block emission).
HIGH_IMPACT_CONF = 4

# Emission decisions the convergence gate guards.
_GATED = {Decision.terminal_stop, Decision.synthesize}


def unresolved_challenges(state: ResearchState) -> list:
    """Challenges that are neither resolved nor handed to a human."""
    return [
        c for c in state.albert_challenge_map.values()
        if c.status not in _RESOLVED_STATUSES
        and c.status not in _HUMAN_BLOCKED_STATUSES
    ]


def open_count(state: ResearchState) -> int:
    return len(unresolved_challenges(state))


def resolved_count(state: ResearchState) -> int:
    return sum(
        1 for c in state.albert_challenge_map.values()
        if c.status in _RESOLVED_STATUSES
    )


def escalated_count(state: ResearchState) -> int:
    return sum(
        1 for c in state.albert_challenge_map.values()
        if c.status in _HUMAN_BLOCKED_STATUSES
    )


def record_signal(state: ResearchState) -> int:
    """Append the current unresolved-count to ``convergence_history`` and return it."""
    n = open_count(state)
    state.convergence_history.append(n)
    return n


def is_converging(state: ResearchState) -> bool:
    """True iff the last two recorded open-counts are strictly descending (the
    loop is making convergence progress). Needs >= 2 data points; a flat or rising
    tail is NOT converging (plateau / divergence)."""
    hist = state.convergence_history
    if len(hist) < 2:
        return False
    return hist[-1] < hist[-2]


def is_converged(state: ResearchState) -> bool:
    """True iff no challenge is still UNRESOLVED — every challenge is either
    resolved or handed to a human (all-remaining-human-blocked is terminal)."""
    return open_count(state) == 0


def albert_challenge_readiness(state: ResearchState) -> int:
    """Readiness 0-5 from the resolved-vs-total ratio (human-blocked counts as
    'done' for readiness, since AI cannot move it further). Full (5) when there
    are no challenges at all."""
    total = len(state.albert_challenge_map)
    if total == 0:
        return 5
    done = resolved_count(state) + escalated_count(state)
    return round(5 * done / total)


def has_unresolved_high_impact(state: ResearchState) -> bool:
    """True iff a HIGH-IMPACT challenge is still UNRESOLVED (open/answered). An
    escalated-to-human high-impact challenge does NOT count — the human gate owns
    it, so blocking emission on it would be an infinite loop."""
    return any(
        c.confidence >= HIGH_IMPACT_CONF
        for c in unresolved_challenges(state)
    )


def grid_converged(state) -> bool:
    """P8 §4 — converged iff the grid exists and has no open high-impact cell."""
    grid = getattr(state, "task_grid", None)
    if grid is None:
        return False
    return not grid.open_high_impact_cells(min_impact=HIGH_IMPACT_CONF)


def gate_emission(state: ResearchState, decision: Decision) -> Decision:
    """Refuse a synthesize/terminal emission while a high-impact challenge is
    unresolved — force back to ``continue_research``. Non-emission decisions pass
    through unchanged."""
    if decision not in _GATED:
        return decision
    if has_unresolved_high_impact(state):
        return Decision.continue_research
    return decision
