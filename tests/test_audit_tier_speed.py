"""Deterministic speed-cascade tests (P6 Task 2).

``audit_tier_for(stage, state) -> "flash" | "quick" | "fast" | "normal"`` picks
the Albert run speed by stage + risk, PURELY (no LLM, no datetime, no I/O):

  * per-iteration sentinel          -> flash   (one Opus call, ~secs)
  * escalation (readiness approaching OR last audit flagged drift/premature high)
                                    -> quick   (5min)
  * pre-synthesize (before §22 gate) -> fast    (10min)
  * final / high-stakes / H6        -> normal  (20min)

``speed_to_cli_flag(speed)`` maps the speed to the run_albert.py flag:
flash->--flash, quick->--quick, fast->--fast, normal->None (default thorough).
"""
from __future__ import annotations

from cn5_research_cos.decision.audit_tier import audit_tier_for, speed_to_cli_flag
from cn5_research_cos.models import (AuditResult, AuditVerdict, ReadinessScore,
                                     ResearchState, Risk)


def _state(**kw) -> ResearchState:
    return ResearchState(run_id="r", original_question="q", **kw)


def _readiness(level: int) -> ReadinessScore:
    return ReadinessScore(
        albert_challenge_readiness=level, decision_readiness=level,
        research_exhaustion_readiness=level, human_bottleneck_clarity=level,
    )


# --------------------------------------------------------------------------- #
# Stage-driven base cascade
# --------------------------------------------------------------------------- #
def test_sentinel_stage_is_flash():
    assert audit_tier_for("sentinel", _state()) == "flash"


def test_pre_synthesize_stage_is_fast():
    # No high-risk signals -> the stage default (fast) wins.
    assert audit_tier_for("pre_synthesize", _state()) == "fast"


def test_final_stage_is_normal():
    assert audit_tier_for("final", _state()) == "normal"


def test_h6_stage_is_normal():
    assert audit_tier_for("h6", _state()) == "normal"


def test_high_stakes_stage_is_normal():
    assert audit_tier_for("high_stakes", _state()) == "normal"


# --------------------------------------------------------------------------- #
# Escalation overrides the sentinel-tier toward quick
# --------------------------------------------------------------------------- #
def test_sentinel_escalates_to_quick_when_readiness_approaching():
    # readiness >= APPROACHING on all axes (but not yet a gate) -> quick.
    st = _state(readiness_score=_readiness(3))
    assert audit_tier_for("sentinel", st) == "quick"


def test_sentinel_escalates_to_quick_when_last_audit_premature_high():
    st = _state(last_audit=AuditResult(verdict=AuditVerdict.rework,
                                       premature_end_risk=Risk.high))
    assert audit_tier_for("sentinel", st) == "quick"


def test_sentinel_escalates_to_quick_when_last_audit_drift_high():
    st = _state(last_audit=AuditResult(verdict=AuditVerdict.rework,
                                       research_drift_risk=Risk.high))
    assert audit_tier_for("sentinel", st) == "quick"


def test_sentinel_low_risk_low_readiness_stays_flash():
    st = _state(readiness_score=_readiness(1),
                last_audit=AuditResult(verdict=AuditVerdict.continue_,
                                       premature_end_risk=Risk.med))
    assert audit_tier_for("sentinel", st) == "flash"


def test_final_stage_never_downgraded_by_low_risk():
    # final is the deepest tier; risk signals cannot make it shallower.
    st = _state(readiness_score=_readiness(1))
    assert audit_tier_for("final", st) == "normal"


def test_unknown_stage_defaults_to_quick():
    assert audit_tier_for("whatever", _state()) == "quick"


# --------------------------------------------------------------------------- #
# CLI flag mapping
# --------------------------------------------------------------------------- #
def test_speed_to_cli_flag():
    assert speed_to_cli_flag("flash") == "--flash"
    assert speed_to_cli_flag("quick") == "--quick"
    assert speed_to_cli_flag("fast") == "--fast"
    assert speed_to_cli_flag("normal") is None  # default thorough, no flag


def test_speed_to_cli_flag_unknown_is_none():
    assert speed_to_cli_flag("bogus") is None
