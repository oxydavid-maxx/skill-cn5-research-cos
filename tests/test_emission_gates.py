"""Task 7 (P5): the four emission gates (each refuses independently) + H6 wiring.

Gate order (check_emission): (1) degraded-audit, (2) convergence (high-impact
challenge unresolved), (3) citation (unverified KEY claim), (4) readiness target
met OR explicit command. Memo emits ONLY when all four pass.
"""
from cn5_research_cos.synthesis.gates import check_emission
from cn5_research_cos.synthesis.memo import assemble_memo
from cn5_research_cos.brains.synthesis import MockSynthesizer
from cn5_research_cos.models import (
    AlbertChallenge, AuditResult, AuditVerdict, ChallengeStatus, Memo,
    ReadinessScore, ResearchState, Risk,
)


def _clean_audit(degraded=False):
    return AuditResult(verdict=AuditVerdict.exhausted, degraded=degraded,
                       premature_end_risk=Risk.low, research_drift_risk=Risk.low)


def _ready_score(v=5):
    return ReadinessScore(
        albert_challenge_readiness=v, decision_readiness=v,
        research_exhaustion_readiness=v, human_bottleneck_clarity=v,
        should_continue=False,
    )


def _good_state():
    """A state that passes gates 1, 2, 4: audit ran (not degraded), no unresolved
    high-impact challenge, readiness target met."""
    rs = ResearchState(run_id="r", original_question="q")
    rs.last_audit = _clean_audit()
    rs.readiness_score = _ready_score(5)
    return rs


def _clean_memo():
    return Memo(unverified_key_claims=[])


# --- gate 1: degraded / missing audit ---------------------------------------
def test_no_audit_refuses():
    rs = _good_state()
    rs.last_audit = None
    out = check_emission(rs, _clean_memo(), explicit=True)
    assert out.emitted is False
    assert out.refused_reason


def test_degraded_audit_refuses():
    rs = _good_state()
    rs.last_audit = _clean_audit(degraded=True)
    out = check_emission(rs, _clean_memo(), explicit=True)
    assert out.emitted is False
    assert "degrad" in out.refused_reason.lower() or "audit" in out.refused_reason.lower()


# --- gate 2: convergence (unresolved high-impact challenge) ------------------
# P5b policy: convergence is a COMPLETENESS gate. It refuses on the NORMAL path
# (explicit=False) but is OVERRIDDEN by an explicit emit command — the §22 memo
# documents the open challenge in its Albert Challenge Map / Blocking sections, so
# emitting on explicit command with an open challenge is honest, not a fabrication.
def test_unresolved_high_impact_challenge_refuses_without_explicit():
    rs = _good_state()
    rs.albert_challenge_map = {
        "C-1": AlbertChallenge(id="C-1", challenge="big one", confidence=5,
                               status=ChallengeStatus.open),
    }
    out = check_emission(rs, _clean_memo(), explicit=False)
    assert out.emitted is False
    assert "convergence" in out.refused_reason.lower()


def test_unresolved_high_impact_challenge_emits_with_explicit():
    """P5b Task 4: explicit overrides the convergence (completeness) gate when the
    correctness gates (degraded-audit, citation) pass."""
    rs = _good_state()
    rs.albert_challenge_map = {
        "C-1": AlbertChallenge(id="C-1", challenge="big one", confidence=5,
                               status=ChallengeStatus.open),
    }
    out = check_emission(rs, _clean_memo(), explicit=True)
    assert out.emitted is True, f"refused: {out.refused_reason}"


def test_explicit_still_refuses_on_degraded_audit_even_with_open_challenge():
    """Correctness gate 1 ALWAYS applies — explicit never bypasses a degraded audit,
    even though it would bypass the open-challenge convergence gate."""
    rs = _good_state()
    rs.last_audit = _clean_audit(degraded=True)
    rs.albert_challenge_map = {
        "C-1": AlbertChallenge(id="C-1", challenge="big one", confidence=5,
                               status=ChallengeStatus.open),
    }
    out = check_emission(rs, _clean_memo(), explicit=True)
    assert out.emitted is False
    assert "degrad" in out.refused_reason.lower() or "audit" in out.refused_reason.lower()


def test_explicit_still_refuses_on_unverified_key_claim_with_open_challenge():
    """Correctness gate 3 ALWAYS applies — explicit never bypasses an unverified KEY
    claim, even with an open challenge that the convergence gate would have caught."""
    rs = _good_state()
    rs.albert_challenge_map = {
        "C-1": AlbertChallenge(id="C-1", challenge="big one", confidence=5,
                               status=ChallengeStatus.open),
    }
    memo = Memo(unverified_key_claims=["a decision-critical unverified claim"])
    out = check_emission(rs, memo, explicit=True)
    assert out.emitted is False
    assert "citation" in out.refused_reason.lower()


# --- gate 3: citation (unverified KEY claim) --------------------------------
def test_unverified_key_claim_refuses():
    rs = _good_state()
    memo = Memo(unverified_key_claims=["a decision-critical unverified claim"])
    out = check_emission(rs, memo, explicit=True)
    assert out.emitted is False


# --- gate 4: readiness target OR explicit -----------------------------------
def test_below_readiness_without_explicit_refuses():
    rs = _good_state()
    rs.readiness_score = _ready_score(2)  # below TARGET=4
    out = check_emission(rs, _clean_memo(), explicit=False)
    assert out.emitted is False


def test_below_readiness_with_explicit_emits():
    rs = _good_state()
    rs.readiness_score = _ready_score(2)
    out = check_emission(rs, _clean_memo(), explicit=True)
    assert out.emitted is True


# --- all pass ---------------------------------------------------------------
def test_all_pass_emits_without_explicit_when_ready():
    out = check_emission(_good_state(), _clean_memo(), explicit=False)
    assert out.emitted is True
    assert out.refused_reason is None


def test_all_pass_emits_with_explicit_command():
    out = check_emission(_good_state(), _clean_memo(), explicit=True)
    assert out.emitted is True


# --- integration with assemble_memo ----------------------------------------
def test_assembled_memo_then_gated():
    rs = _good_state()
    memo = assemble_memo(rs, MockSynthesizer())
    gated = check_emission(rs, memo, explicit=True)
    assert gated.emitted is True
    assert gated.section_keys() and len(gated.sections) == 9
