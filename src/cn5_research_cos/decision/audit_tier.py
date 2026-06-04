"""Deterministic Albert audit-SPEED cascade (P6, §14 of the spec).

``audit_tier_for(stage, state) -> speed`` picks how DEEP the real Albert runs at a
given loop position, balancing cost vs rigor. PURE: no LLM, no ``datetime.now()``,
no I/O — speed is a function of the stage label + cheap state signals only.

Speed ladder (cheap → deep), mapped to the live ``run_albert.py`` profiles:

  * ``flash``  — one DIRECT Opus call (~secs, no FSM). The per-iteration sentinel.
  * ``quick``  — full Albert FSM, ~5min  (``--quick``).
  * ``fast``   — full Albert FSM, ~10min (``--fast``).
  * ``normal`` — full Albert FSM, ~20min (default ``thorough``, no flag).

Stage → base speed:
  * ``"sentinel"``                       → flash  (per-iteration)
  * ``"pre_synthesize"``                 → fast   (before the §22 memo gate)
  * ``"final" | "h6" | "high_stakes"``   → normal (the deepest, final gate)
  * any other / unknown stage            → quick  (safe middle default)

Escalation: a ``sentinel`` (flash) iteration ESCALATES to ``quick`` when the loop
smells a wrong turn — readiness is APPROACHING a gate (so the next audit matters
more) OR the last audit flagged ``premature_end_risk`` / ``research_drift_risk``
as ``high``. The gate stages (fast/normal) are NEVER downgraded by low risk —
depth at a gate is non-negotiable.
"""
from __future__ import annotations

from ..models import ResearchState, Risk

# The valid speeds, cheap → deep.
SPEEDS = ("flash", "quick", "fast", "normal")

# Base speed per stage label.
_STAGE_BASE = {
    "sentinel": "flash",
    "plan": "flash",
    "pre_synthesize": "fast",
    "final": "normal",
    "h6": "normal",
    "high_stakes": "normal",
}
_DEFAULT_STAGE_SPEED = "quick"

# Readiness (min axis) at/above which we are "approaching" a gate — escalate the
# cheap sentinel to a real --quick FSM audit so the gate decision is well-founded.
APPROACHING_READINESS = 3

# speed → run_albert.py CLI flag. normal = default thorough (no flag).
_SPEED_FLAG = {"flash": "--flash", "quick": "--quick", "fast": "--fast", "normal": None}


def _last_audit_smells_wrong(state: ResearchState) -> bool:
    audit = state.last_audit
    if audit is None:
        return False
    return audit.premature_end_risk == Risk.high or audit.research_drift_risk == Risk.high


def _readiness_approaching(state: ResearchState) -> bool:
    rs = state.readiness_score
    if rs is None:
        return False
    return min(
        rs.albert_challenge_readiness,
        rs.decision_readiness,
        rs.research_exhaustion_readiness,
        rs.human_bottleneck_clarity,
    ) >= APPROACHING_READINESS


def audit_tier_for(stage: str, state: ResearchState) -> str:
    """Return the Albert speed (``flash|quick|fast|normal``) for ``stage`` + ``state``."""
    base = _STAGE_BASE.get(stage, _DEFAULT_STAGE_SPEED)
    # Only the per-iteration sentinel is eligible for risk-driven escalation; the
    # gate stages already run a full FSM and are never downgraded.
    if base == "flash" and (
        _readiness_approaching(state) or _last_audit_smells_wrong(state)
    ):
        return "quick"
    return base


def speed_to_cli_flag(speed: str) -> str | None:
    """Map a speed to the ``run_albert.py`` flag (``normal`` → ``None`` = default)."""
    return _SPEED_FLAG.get(speed)
