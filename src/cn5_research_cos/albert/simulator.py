"""RealAlbertSimulator — the cockpit's cheap-LLM Albert Auditor (P2b).

A NARROW LLM node: given the current draft/answer + research state, it produces an
`albert_challenge`-shaped dict (a subset of the vendored albert_challenge schema,
sufficient for the cockpit mapping), then `contract.to_audit_result(dict)` maps it
into our `AuditResult` 1:1 and the `["enrichment"]` is stashed onto the A2 fields.

All loop/convergence/stop/routing/COS-decision control stays DETERMINISTIC (the
graph is unchanged from P1). This node only emits a structured audit.

P3/P6: swap this simulator for the real external `skill-cn5-i-am-albert` at the
SAME `to_audit_result` contract — the graph does not change.
"""
from __future__ import annotations

from ..llm import sdk_client
from ..models import AuditResult, ResearchState
from .contract import to_audit_result

# Subset of the vendored albert_challenge.schema.json — exactly the fields the
# cockpit mapping consumes. Kept narrow (one job: challenge the current answer).
ALBERT_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["continue", "exhausted", "rework"]},
        "albert_challenges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "challenge": {"type": "string"},
                    "why_albert_would_ask": {"type": "string"},
                    "current_answer": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["answered", "partially_answered", "needs_external_research",
                                 "needs_internal_data", "needs_bu_judgment",
                                 "needs_albert_decision", "needs_source_validation", "blocked"],
                    },
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "missing_info": {"type": "string"},
                    "blocking_owner": {"type": "string"},
                    "next_action": {"type": "string"},
                },
                "required": ["challenge", "why_albert_would_ask", "status"],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
        "weak_points": {"type": "array", "items": {"type": "string"}},
        "missing_business_context": {"type": "array", "items": {"type": "string"}},
        "questions_albert_would_ask": {"type": "array", "items": {"type": "string"}},
        "premature_end_risk": {
            "type": "object",
            "properties": {"level": {"type": "string", "enum": ["low", "medium", "high"]}},
            "required": ["level"],
        },
        "research_drift_risk": {
            "type": "object",
            "properties": {"level": {"type": "string", "enum": ["low", "medium", "high"]}},
            "required": ["level"],
        },
        "recommended_next_action": {
            "type": "string",
            "enum": ["continue_research", "branch", "rerank", "pull_human",
                     "push_human", "synthesize", "pause", "terminal_stop"],
        },
        "rationale": {"type": "string"},
        "readiness_score_delta": {"type": "integer", "minimum": -2, "maximum": 2},
    },
    "required": ["verdict", "albert_challenges", "premature_end_risk",
                 "research_drift_risk", "recommended_next_action", "rationale"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are Albert, a high-standard BU-head auditing a research answer in a war room. "
    "Your job is NOT to summarize — it is to CHALLENGE the current answer to force "
    "decision quality. Attack the weakest links: hidden assumptions, premature-stop "
    "risk, research drift, and whether any claimed human-in-the-loop dependency is "
    "genuine or an excuse to avoid building autonomy. For each challenge, state why "
    "you would ask it and the current (weak) answer. Return STRICT JSON per the schema."
)


def _user_prompt(state: ResearchState) -> str:
    draft = state.research_brief or state.final_memo or "(no draft yet)"
    issues = "; ".join(
        f"{n.title} [{n.status.value}]" for n in list(state.issue_map.values())[:12]
    ) or "(none)"
    return (
        f"ORIGINAL QUESTION:\n{state.original_question}\n\n"
        f"CURRENT DRAFT / ANSWER:\n{draft}\n\n"
        f"OPEN ISSUES:\n{issues}\n\n"
        "Audit this answer as Albert. If the draft leans on 'human-in-the-loop', "
        "challenge specifically: (1) why can't the AI ask all clarifying questions "
        "upfront and then run overnight unattended; (2) which parts TRULY require a "
        "human vs. which are automatable now; (3) whether HITL is being used as an "
        "excuse; (4) what could be automated immediately. Produce concrete challenges, "
        "a verdict, risks, a recommended_next_action, and a rationale."
    )


class RealAlbertSimulator:
    """Cheap-LLM Albert auditor satisfying the `Auditor` Protocol."""

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model

    def audit(self, state: ResearchState) -> AuditResult:
        raw = sdk_client.call_structured(
            _SYSTEM, _user_prompt(state), ALBERT_OUTPUT_SCHEMA, model=self._model
        )
        mapped = to_audit_result(raw)
        audit = AuditResult.model_validate(mapped["audit_result"])

        # Stash the gap-audit A2 enrichment onto the AuditResult's A2 fields when
        # the mapping didn't already place them (recommended_next_probe has no
        # dedicated AuditResult field beyond recommended_next_probe: str).
        enr = mapped.get("enrichment", {})
        if not audit.missing_business_context and enr.get("missing_business_context"):
            audit.missing_business_context = list(enr["missing_business_context"])
        if not audit.questions_albert_would_ask_next and enr.get("questions_albert_would_ask"):
            audit.questions_albert_would_ask_next = list(enr["questions_albert_would_ask"])
        if not audit.readiness_score_delta and enr.get("readiness_score_delta"):
            audit.readiness_score_delta = int(enr["readiness_score_delta"])
        probes = enr.get("recommended_next_probe") or []
        if probes and audit.recommended_next_probe is None:
            first = probes[0]
            audit.recommended_next_probe = (
                first.get("probe") if isinstance(first, dict) else str(first)
            )
        return audit
