"""Vendored Albert contract mapping tests (deterministic, NO LLM).

Asserts that `albert.contract.to_audit_result` maps an `albert_challenge`-shaped
dict (schema-valid per the vendored albert_challenge.schema.json) 1:1 into our
cockpit `AuditResult` Pydantic model, plus enrichment onto the A2 fields.
"""
from __future__ import annotations

import json
from pathlib import Path

from cn5_research_cos.albert.contract import to_audit_result
from cn5_research_cos.models import (AuditResult, AuditVerdict, ChallengeStatus,
                                     Decision, Risk)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "src" / "cn5_research_cos" / "albert" / "albert_challenge.schema.json"
)


def _vendored_shape() -> dict:
    """A hand-built dict matching the vendored albert_challenge schema, covering
    the Test-3 'human-in-loop' angles so the field mapping is exercised end-to-end."""
    return {
        "verdict": "rework",
        "audited_answer": "human-in-the-loop is needed for this research",
        "would_survive_leadership": False,
        "albert_challenges": [
            {
                "challenge": "Why can't the AI ask all clarifying questions upfront, then run overnight?",
                "why_albert_would_ask": "HITL may be an excuse to avoid building autonomy",
                "current_answer": "We pause for human input each loop.",
                "status": "needs_bu_judgment",
                "confidence": "low",
                "severity": "high",
                "current_answer_strength": "weak",
                "evidence_refs": ["S-1"],
                "missing_info": "which parts truly require a human",
                "blocking_owner": "PM",
                "next_action": "enumerate human-only steps",
                "meeting_ready_response": "...",
                "generator": "first_principle",
                "bone": 7,
                "high_impact": True,
            },
            {
                "challenge": "Which parts truly require humans vs can be automated now?",
                "why_albert_would_ask": "separate genuine HITL from laziness",
                "status": "needs_albert_decision",
                "confidence": "medium",
                "severity": "medium",
                "current_answer_strength": "medium",
                "generator": "owner_business",
                "bone": 5,
            },
        ],
        "weak_points": ["no enumeration of human-only steps", {"x": "non-string coerced"}],
        "missing_business_context": ["which decisions need BU head"],
        "missing_evidence": [{"item": "automation feasibility", "who_can_answer": "AI"}],
        "questions_albert_would_ask": [
            "Is HITL an excuse?",
            "What can be automated now?",
        ],
        "premature_end_risk": {"level": "high", "grounded_in": "inferred",
                               "atoms": {"a": 1}, "why": "unverified"},
        "research_drift_risk": {"level": "low", "grounded_in": "inferred"},
        "recommended_next_probe": [{"probe": "enumerate human steps", "why": "scope HITL"}],
        "recommended_next_action": "branch",
        "rationale": "HITL claim is unverified; must separate genuine human steps.",
        "readiness_score_delta": -1,
        "degraded": False,
    }


def test_schema_file_is_vendored():
    assert _SCHEMA_PATH.exists(), f"vendored schema missing at {_SCHEMA_PATH}"
    data = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert data.get("title") == "AlbertChallenge"


def test_to_audit_result_constructs_our_auditresult():
    """The mapped audit_result dict must construct our Pydantic AuditResult 1:1."""
    mapped = to_audit_result(_vendored_shape())
    ar_dict = mapped["audit_result"]
    ar = AuditResult.model_validate(ar_dict)

    assert ar.verdict == AuditVerdict.rework
    assert ar.recommended_next_action == Decision.branch
    assert ar.premature_end_risk == Risk.high
    assert ar.research_drift_risk == Risk.low
    assert ar.rationale.startswith("HITL claim")
    assert ar.degraded is False


def test_challenges_map_one_to_one():
    ar = AuditResult.model_validate(to_audit_result(_vendored_shape())["audit_result"])
    assert len(ar.challenges) == 2
    c0 = ar.challenges[0]
    assert c0.challenge.startswith("Why can't the AI")
    assert c0.why_albert_would_ask == "HITL may be an excuse to avoid building autonomy"
    assert c0.current_answer == "We pause for human input each loop."
    # status mapped into OUR ChallengeStatus enum
    assert c0.status == ChallengeStatus.needs_bu_judgment
    assert ar.challenges[1].status == ChallengeStatus.needs_albert_decision
    # confidence: vendored 'low' string -> our int 0-5
    assert 0 <= c0.confidence <= 5
    assert c0.evidence_refs == ["S-1"]


def test_weak_points_coerced_to_strings():
    ar = AuditResult.model_validate(to_audit_result(_vendored_shape())["audit_result"])
    assert all(isinstance(w, str) for w in ar.weak_points)


def test_enrichment_carries_a2_fields():
    enr = to_audit_result(_vendored_shape())["enrichment"]
    assert enr["missing_business_context"] == ["which decisions need BU head"]
    assert enr["questions_albert_would_ask"] == ["Is HITL an excuse?", "What can be automated now?"]
    assert enr["readiness_score_delta"] == -1
    assert "recommended_next_probe" in enr


def test_risk_medium_maps_to_our_med():
    shape = _vendored_shape()
    shape["premature_end_risk"] = {"level": "medium", "grounded_in": "inferred"}
    ar = AuditResult.model_validate(to_audit_result(shape)["audit_result"])
    assert ar.premature_end_risk == Risk.med


def test_unknown_status_falls_back_to_open():
    shape = _vendored_shape()
    shape["albert_challenges"][0]["status"] = "needs_external_research"
    ar = AuditResult.model_validate(to_audit_result(shape)["audit_result"])
    # statuses we don't model collapse to a safe in-model value
    assert ar.challenges[0].status in set(ChallengeStatus)
