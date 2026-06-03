"""Component 1 — convergence tracking (pure, deterministic).

Challenge lifecycle open -> answered -> resolved (or escalated_to_human). A
convergence signal = open-count trend toward 0 / all-remaining human-blocked.
``albert_challenge_readiness`` reflects the resolved-vs-open ratio. The emission
gate REFUSES while high-impact challenges remain unresolved.
"""
from __future__ import annotations

from cn5_research_cos.artifacts import challenge_map
from cn5_research_cos.decision import convergence
from cn5_research_cos.models import (AlbertChallenge, ChallengeStatus, Decision,
                                     ResearchState)


def _state() -> ResearchState:
    return ResearchState(run_id="r", original_question="q")


def _ch(cid, status, **kw):
    return AlbertChallenge(id=cid, challenge=cid, status=status, **kw)


# --------------------------------------------------------------------------- #
# lifecycle classification
# --------------------------------------------------------------------------- #
def test_open_and_resolved_counts():
    s = _state()
    s.albert_challenge_map = {
        "C-001": _ch("C-001", ChallengeStatus.open),
        "C-002": _ch("C-002", ChallengeStatus.answered),
        "C-003": _ch("C-003", ChallengeStatus.resolved),
        "C-004": _ch("C-004", ChallengeStatus.escalated_to_human),
    }
    assert convergence.open_count(s) == 2   # open + answered are still unresolved
    assert convergence.resolved_count(s) == 1
    assert convergence.escalated_count(s) == 1


def test_unresolved_excludes_resolved_and_escalated():
    s = _state()
    s.albert_challenge_map = {
        "C-001": _ch("C-001", ChallengeStatus.open),
        "C-002": _ch("C-002", ChallengeStatus.resolved),
    }
    unresolved = convergence.unresolved_challenges(s)
    assert [c.id for c in unresolved] == ["C-001"]


# --------------------------------------------------------------------------- #
# convergence signal
# --------------------------------------------------------------------------- #
def test_signal_records_open_count_history():
    s = _state()
    s.albert_challenge_map = {"C-001": _ch("C-001", ChallengeStatus.open)}
    convergence.record_signal(s)
    s.albert_challenge_map["C-001"].status = ChallengeStatus.resolved
    convergence.record_signal(s)
    # the open-count trend is recorded and is descending (1 -> 0)
    assert s.convergence_history == [1, 0]
    assert convergence.is_converging(s)


def test_not_converging_when_open_count_flat_or_rising():
    s = _state()
    s.convergence_history = [2, 2, 2]
    assert not convergence.is_converging(s)
    s.convergence_history = [1, 2]
    assert not convergence.is_converging(s)


def test_converged_when_no_unresolved():
    s = _state()
    s.albert_challenge_map = {"C-001": _ch("C-001", ChallengeStatus.resolved)}
    assert convergence.is_converged(s)


def test_converged_when_all_remaining_human_blocked():
    """All-remaining-human-blocked is a terminal convergence (no AI progress left)."""
    s = _state()
    s.albert_challenge_map = {
        "C-001": _ch("C-001", ChallengeStatus.resolved),
        "C-002": _ch("C-002", ChallengeStatus.escalated_to_human),
        "C-003": _ch("C-003", ChallengeStatus.needs_bu_judgment),
    }
    assert convergence.is_converged(s)


def test_not_converged_with_an_open_challenge():
    s = _state()
    s.albert_challenge_map = {
        "C-001": _ch("C-001", ChallengeStatus.open),
        "C-002": _ch("C-002", ChallengeStatus.escalated_to_human),
    }
    assert not convergence.is_converged(s)


# --------------------------------------------------------------------------- #
# readiness reflects resolved-vs-open
# --------------------------------------------------------------------------- #
def test_challenge_readiness_full_when_no_challenges():
    s = _state()
    assert convergence.albert_challenge_readiness(s) == 5


def test_challenge_readiness_scales_with_resolved_ratio():
    s = _state()
    s.albert_challenge_map = {
        "C-001": _ch("C-001", ChallengeStatus.resolved),
        "C-002": _ch("C-002", ChallengeStatus.resolved),
        "C-003": _ch("C-003", ChallengeStatus.resolved),
        "C-004": _ch("C-004", ChallengeStatus.open),
    }
    # 3/4 resolved -> round(5 * 0.75) == 4
    assert convergence.albert_challenge_readiness(s) == 4


def test_challenge_readiness_low_when_all_open():
    s = _state()
    s.albert_challenge_map = {"C-001": _ch("C-001", ChallengeStatus.open)}
    assert convergence.albert_challenge_readiness(s) == 0


# --------------------------------------------------------------------------- #
# emission gate: refuse when a HIGH-IMPACT challenge remains unresolved
# --------------------------------------------------------------------------- #
def test_high_impact_unresolved_blocks_emission():
    s = _state()
    s.albert_challenge_map = {
        "C-001": _ch("C-001", ChallengeStatus.open, confidence=5),
    }
    assert convergence.has_unresolved_high_impact(s)
    # gate downgrades synthesize/terminal to continue_research
    assert convergence.gate_emission(s, Decision.synthesize) == Decision.continue_research
    assert convergence.gate_emission(s, Decision.terminal_stop) == Decision.continue_research


def test_escalated_high_impact_does_not_block_emission():
    """A high-impact challenge that has been ESCALATED to a human is no longer a
    blocker for AI emission — the human gate owns it now (no infinite loop)."""
    s = _state()
    s.albert_challenge_map = {
        "C-001": _ch("C-001", ChallengeStatus.escalated_to_human, confidence=5),
    }
    assert not convergence.has_unresolved_high_impact(s)
    assert convergence.gate_emission(s, Decision.synthesize) == Decision.synthesize


def test_low_impact_unresolved_allows_emission():
    s = _state()
    s.albert_challenge_map = {
        "C-001": _ch("C-001", ChallengeStatus.open, confidence=1),
    }
    assert not convergence.has_unresolved_high_impact(s)
    assert convergence.gate_emission(s, Decision.synthesize) == Decision.synthesize


def test_gate_passthrough_for_non_emission_decisions():
    s = _state()
    s.albert_challenge_map = {"C-001": _ch("C-001", ChallengeStatus.open, confidence=5)}
    assert convergence.gate_emission(s, Decision.continue_research) == Decision.continue_research
    assert convergence.gate_emission(s, Decision.branch) == Decision.branch
