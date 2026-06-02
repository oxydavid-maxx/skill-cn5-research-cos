"""RealAlbertSimulator wiring tests.

Deterministic (default): monkeypatch sdk_client.call_structured to return a
scripted albert_challenge-shaped dict; assert the simulator maps it to our
AuditResult (via the vendored contract) and stashes enrichment.

Live (opt-in CN5_COS_LLM_TESTS=1): Acceptance Test 3 — a 'human-in-loop needed'
draft must produce challenges covering the expected angles.
"""
from __future__ import annotations

import os

import pytest

from cn5_research_cos.albert.simulator import RealAlbertSimulator
from cn5_research_cos.brains import interfaces
from cn5_research_cos.llm import sdk_client
from cn5_research_cos.models import (AuditResult, AuditVerdict, Decision, Risk,
                                     ResearchState)


def _scripted_challenge() -> dict:
    return {
        "verdict": "rework",
        "audited_answer": "human-in-the-loop is needed",
        "would_survive_leadership": False,
        "albert_challenges": [
            {
                "challenge": "Why can't the AI ask upfront then run overnight?",
                "why_albert_would_ask": "autonomy",
                "status": "needs_bu_judgment",
                "confidence": "low",
                "severity": "high",
                "current_answer_strength": "weak",
                "generator": "first_principle",
                "bone": 8,
            }
        ],
        "weak_points": ["no enumeration of human-only steps"],
        "missing_business_context": ["which decisions need BU head"],
        "questions_albert_would_ask": ["Is HITL an excuse?"],
        "premature_end_risk": {"level": "high", "grounded_in": "inferred"},
        "research_drift_risk": {"level": "low", "grounded_in": "inferred"},
        "recommended_next_probe": [{"probe": "enumerate human steps", "why": "scope"}],
        "recommended_next_action": "branch",
        "rationale": "HITL claim unverified.",
        "readiness_score_delta": -1,
        "degraded": False,
    }


def test_simulator_satisfies_auditor_protocol():
    assert isinstance(RealAlbertSimulator(), interfaces.Auditor)


def test_simulator_maps_scripted_dict_to_auditresult(monkeypatch):
    monkeypatch.setattr(sdk_client, "call_structured", lambda *a, **k: _scripted_challenge())
    state = ResearchState(run_id="r", original_question="Can AI research overnight?")
    state.research_brief = "draft answer: human-in-the-loop is needed"

    audit = RealAlbertSimulator().audit(state)
    assert isinstance(audit, AuditResult)
    assert audit.verdict == AuditVerdict.rework
    assert audit.recommended_next_action == Decision.branch
    assert audit.premature_end_risk == Risk.high
    assert len(audit.challenges) == 1
    assert audit.challenges[0].challenge.startswith("Why can't the AI")
    # enrichment stashed onto the A2 fields
    assert audit.missing_business_context == ["which decisions need BU head"]
    assert audit.questions_albert_would_ask_next == ["Is HITL an excuse?"]
    assert audit.readiness_score_delta == -1


@pytest.mark.llm
def test_albert_acceptance_test_3_live():
    """Acceptance Test 3: 'human-in-loop needed' draft -> Albert challenges cover
    the expected angles. Assert STRUCTURE/coverage (keywords), not verbatim."""
    if os.environ.get("CN5_COS_LLM_TESTS") != "1":
        pytest.skip("set CN5_COS_LLM_TESTS=1 to run live LLM tests")

    state = ResearchState(
        run_id="r-t3",
        original_question="Should AI research be human-in-the-loop?",
    )
    state.research_brief = (
        "Draft answer: This research requires human-in-the-loop at every step; "
        "a human must review and approve each iteration before continuing."
    )
    audit = RealAlbertSimulator().audit(state)
    assert isinstance(audit, AuditResult)
    assert audit.challenges, "Albert produced no challenges"

    blob = " ".join(
        (c.challenge + " " + c.why_albert_would_ask).lower()
        for c in audit.challenges
    )
    blob += " " + " ".join(q.lower() for q in audit.questions_albert_would_ask_next)

    # The four expected angles (any phrasing); require coverage of >=2 to be robust
    # to model variance while still proving the audit hits the HITL critique.
    angles = {
        "ask_upfront_overnight": any(
            k in blob for k in ("upfront", "overnight", "ahead of time", "batch", "in advance")
        ),
        "which_parts_human": any(
            k in blob for k in ("which part", "truly require", "genuinely need", "really need", "necessary")
        ),
        "hitl_excuse": any(
            k in blob for k in ("excuse", "crutch", "justif", "avoid", "lazy")
        ),
        "automate_now": any(
            k in blob for k in ("automat", "without human", "self-serve", "autonomous")
        ),
    }
    covered = [k for k, v in angles.items() if v]
    assert len(covered) >= 2, f"only covered {covered}; blob={blob[:500]!r}"
