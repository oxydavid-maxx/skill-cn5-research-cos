"""Vendored Albert -> cockpit AuditResult mapping.

VENDORED (copied + adapted) from
    skill-cn5-i-am-albert/albert/cockpit_contract.py::to_audit_result
to freeze the contract in-repo (P2b spec fork 1+2). The external skill owns the
upstream source; this is the producer-side proof of the R17 seam. P3/P6 swap the
simulator for the real skill at this SAME contract.

Adaptations vs the upstream reference (which emits raw passthrough dicts):
- maps the vendored albert_challenge enums/strings into THIS repo's model
  vocabulary so the result constructs `AuditResult` / `AlbertChallenge` directly:
    * challenge `status` (vendored 8-value enum) -> our `ChallengeStatus`
      (statuses we don't model collapse to `open`).
    * challenge `confidence` (vendored "low"/"medium"/"high") -> our int 0-5.
    * `*_risk.level` "medium" -> our Risk "med".
- weak_points coerced to strings (mirrors upstream).
- the `["audit_result"]` dict is shaped to be `AuditResult.model_validate`-able;
  the `["enrichment"]` dict carries the gap-audit A2 fields.
"""
from __future__ import annotations

# Vendored challenge field projection (mirrors the upstream _CHALLENGE_FIELDS).
_CHALLENGE_FIELDS = ["challenge", "why_albert_would_ask", "current_answer", "status",
                     "confidence", "evidence_refs", "missing_info", "blocking_owner",
                     "next_action", "meeting_ready_response"]

# vendored albert_challenge.status -> our models.ChallengeStatus value.
_STATUS_MAP = {
    "answered": "answered",
    "partially_answered": "open",
    "needs_external_research": "open",
    "needs_internal_data": "needs_internal_data",
    "needs_bu_judgment": "needs_bu_judgment",
    "needs_albert_decision": "needs_albert_decision",
    "needs_source_validation": "open",
    "blocked": "open",
}

# vendored albert_challenge.confidence string -> our int 0-5.
_CONFIDENCE_MAP = {"low": 1, "medium": 3, "high": 5}

# vendored risk level -> our models.Risk value ("medium" -> "med").
_RISK_MAP = {"low": "low", "medium": "med", "med": "med", "high": "high"}


def _risk(node: dict | None) -> str:
    level = (node or {}).get("level", "low")
    return _RISK_MAP.get(level, "low")


def _missing_info_list(ch: dict) -> list[str]:
    mi = ch.get("missing_info", "")
    if isinstance(mi, list):
        return [str(x) for x in mi]
    return [mi] if mi else []


def _entry(ch: dict) -> dict:
    """Project a vendored challenge into an AlbertChallenge-constructible dict."""
    status = _STATUS_MAP.get(ch.get("status", ""), "open")
    conf = ch.get("confidence", 0)
    if isinstance(conf, str):
        conf = _CONFIDENCE_MAP.get(conf, 0)
    return {
        "id": ch.get("id", "C-ALBERT"),
        "challenge": ch.get("challenge", ""),
        "why_albert_would_ask": ch.get("why_albert_would_ask", ""),
        "current_answer": ch.get("current_answer", ""),
        "status": status,
        "confidence": int(conf),
        "evidence_refs": list(ch.get("evidence_refs", []) or []),
        "missing_info": _missing_info_list(ch),
        "blocking_owner": ch.get("blocking_owner") or None,
        "next_action": ch.get("next_action") or None,
        "meeting_ready_response": ch.get("meeting_ready_response") or None,
    }


def to_audit_result(challenge: dict) -> dict:
    """Map an `albert_challenge`-shaped dict -> {"audit_result", "enrichment"}.

    `["audit_result"]` is `AuditResult.model_validate`-able; `["enrichment"]`
    carries the gap-audit A2 fields the cockpit stashes onto the AuditResult.
    """
    challenges = challenge.get("albert_challenges", []) or []
    return {
        "audit_result": {  # the cockpit's AuditResult (load-bearing)
            "verdict": challenge.get("verdict", "rework"),
            "challenges": [_entry(c) for c in challenges],
            "weak_points": [w if isinstance(w, str) else str(w)
                            for w in challenge.get("weak_points", []) or []],
            "premature_end_risk": _risk(challenge.get("premature_end_risk")),
            "research_drift_risk": _risk(challenge.get("research_drift_risk")),
            "recommended_next_action": challenge.get("recommended_next_action"),
            "rationale": challenge.get("rationale", ""),
            "degraded": bool(challenge.get("degraded", False)),
            # gap-audit A2 fields our AuditResult already carries:
            "missing_business_context": list(challenge.get("missing_business_context", []) or []),
            "questions_albert_would_ask_next": list(challenge.get("questions_albert_would_ask", []) or []),
            "readiness_score_delta": int(challenge.get("readiness_score_delta", 0) or 0),
        },
        "enrichment": {  # gap-audit A2 (stashed onto the AuditResult by the simulator)
            "missing_business_context": list(challenge.get("missing_business_context", []) or []),
            "questions_albert_would_ask": list(challenge.get("questions_albert_would_ask", []) or []),
            "recommended_next_probe": list(challenge.get("recommended_next_probe", []) or []),
            "readiness_score_delta": int(challenge.get("readiness_score_delta", 0) or 0),
            "premature_end_atoms": (challenge.get("premature_end_risk") or {}).get("atoms", {}),
            "grounded_in": (challenge.get("premature_end_risk") or {}).get("grounded_in", "inferred"),
        },
    }
