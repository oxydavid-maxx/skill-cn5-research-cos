"""P8 H0 — the 4-criterion Socratic clarification convergence gate (deterministic)."""
from __future__ import annotations
from ..models import ResearchState

CRITERIA = ("purpose", "scope", "success", "constraints")

def _has_purpose(rs: ResearchState) -> bool:
    return bool(rs.decision_criterion)
def _has_scope(rs: ResearchState) -> bool:
    return bool(rs.research_brief)
def _has_success(rs: ResearchState) -> bool:
    return bool(rs.success_form)
def _has_constraints(rs: ResearchState) -> bool:
    return bool(rs.fallback_behavior_if_human_unavailable)

_CHECKS = {"purpose": _has_purpose, "scope": _has_scope,
           "success": _has_success, "constraints": _has_constraints}

def clarify_converged(rs: ResearchState) -> tuple[bool, list[str]]:
    """Return (converged, missing_criteria). Converged iff all 4 are pinned."""
    missing = [c for c in CRITERIA if not _CHECKS[c](rs)]
    return (not missing, missing)
