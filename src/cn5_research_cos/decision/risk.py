"""Risk classification for human-pull gates (pure, no I/O, deterministic).

`classify_pull(state, decision) -> "low" | "high"` drives auto mode's
stop-vs-default behaviour (spec §"Risk classification"):

A pull is **high** (auto mode must hard-stop and `interrupt`) when ANY of:

  1. the decision criterion is UNKNOWN (``default_research_priority`` unset)
     AND every high-impact OPEN issue depends on that criterion (so picking a
     direction without it gambles the whole high-impact frontier); OR
  2. the Albert audit flags ``premature_end_risk`` OR ``research_drift_risk``
     as ``high`` (the cheap sentinel already smells a wrong turn); OR
  3. multiple high-impact intent issues are OPEN with no safe fallback
     (``fallback_behavior_if_human_unavailable`` unset) — there is no defensible
     default to apply, so auto mode must not guess.

Otherwise the pull is **low**: auto mode applies ``default_if_no_response`` and
records a ``steering_event(auto-default)`` instead of stopping.

Pure function of ``state`` + ``decision``; no wall-clock, no LLM, no env reads.
"""
from __future__ import annotations

from ..models import Decision, IssueStatus, IssueType, ResearchState, Risk

# Impact at/above this counts as "high-impact" for the frontier checks.
HIGH_IMPACT = 4

# A token in an issue's ``unknowns`` marking it as gated on the decision criterion.
_CRITERION_TOKEN = "decision_criterion"

_OPEN_STATUSES = (
    IssueStatus.open,
    IssueStatus.researching,
    IssueStatus.partially_answered,
    IssueStatus.low_confidence,
)


def _high_impact_open(state: ResearchState):
    return [
        n for n in state.issue_map.values()
        if n.status in _OPEN_STATUSES and n.impact >= HIGH_IMPACT
    ]


def _criterion_unknown(state: ResearchState) -> bool:
    return not state.default_research_priority


def _all_high_impact_open_depend_on_criterion(state: ResearchState) -> bool:
    hi = _high_impact_open(state)
    if not hi:
        return False
    return all(_CRITERION_TOKEN in n.unknowns for n in hi)


def _no_safe_default(state: ResearchState) -> bool:
    return not state.fallback_behavior_if_human_unavailable


def classify_pull(state: ResearchState, decision: Decision) -> str:
    """Return ``"high"`` (hard-stop) or ``"low"`` (apply default) for a pull gate."""
    audit = state.last_audit
    if audit is not None and (
        audit.premature_end_risk == Risk.high
        or audit.research_drift_risk == Risk.high
    ):
        return "high"

    if _criterion_unknown(state) and _all_high_impact_open_depend_on_criterion(state):
        return "high"

    intents = [
        n for n in _high_impact_open(state)
        if n.issue_type == IssueType.intent
    ]
    if len(intents) >= 2 and _no_safe_default(state):
        return "high"

    return "low"
