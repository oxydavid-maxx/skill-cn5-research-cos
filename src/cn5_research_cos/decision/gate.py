"""Emission / decision gate (borrowing #8).

A synthesize / terminal_stop decision is refused when the last audit is missing or
``degraded`` (ran in fallback/error mode). On refusal the loop is forced back to
continue_research (re-audit). Bypass only via env CN5_COS_EMIT_DESPITE_DEGRADED_AUDIT=1.
"""
from __future__ import annotations

import os

from ..models import Decision, ResearchState

_GATED = {Decision.terminal_stop, Decision.synthesize}


def assert_audit_ran(state: ResearchState, decision: Decision) -> Decision:
    if decision not in _GATED:
        return decision
    if os.environ.get("CN5_COS_EMIT_DESPITE_DEGRADED_AUDIT") == "1":
        return decision
    audit = state.last_audit
    if audit is None or audit.degraded:
        return Decision.continue_research
    return decision
