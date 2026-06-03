"""The §22 decision-memo synthesis brain (P5, cockpit-specific, narrow LLM).

ONE ``call_structured`` (cheap ``haiku``) whose schema's properties are EXACTLY
the 9 §22 section keys; it returns Chinese, meeting-ready prose per section,
grounded in the run state's evidence + Albert challenges. The section SET, the
blocker labels, the citation wiring, and the emission gates are all deterministic
Python (``synthesis/memo.py`` + ``synthesis/gates.py``) — only the prose is LLM.

A deterministic ``MockSynthesizer`` returns a fixed dict (all 9 keys) so the P1-P4
suite stays offline; ``build_brains`` wires the mock for ``mock`` and the real one
for ``real``.
"""
from __future__ import annotations

from ..llm.sdk_client import call_structured
from ..models import ResearchState

# The 9 §22 section keys (single source of truth, mirrored by NINE_SECTION_KEYS
# in synthesis/memo.py).
SECTION_KEYS = [
    "executive_answer",
    "albert_challenge_map",
    "can_cannot_say",
    "blocking",
    "required_human_decisions",
    "evidence_summary",
    "risks_assumptions",
    "recommended_next_action",
    "appendix",
]

_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in SECTION_KEYS},
    "required": SECTION_KEYS,
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a chief-of-staff writing a §22 decision-memo for a BU war-room. One "
    "job: write meeting-ready prose for EACH of the 9 memo sections, grounded ONLY "
    "in the supplied research state (evidence claims + Albert challenges + "
    "blockers). Do NOT invent facts or citations. Write in Traditional Chinese; "
    "keep technical terms untranslated. Each section is concise and decision-"
    "oriented. Return STRICT JSON per the schema (one string per section key)."
)


def _render_state(state: ResearchState) -> str:
    """A compact text view of the run state for the synthesis prompt."""
    issues = "\n".join(
        f"- [{n.status.value}] {n.title} (impact={n.impact}, conf={n.confidence})"
        for n in list(state.issue_map.values())[:20]
    ) or "(no issues)"
    challenges = "\n".join(
        f"- [{c.status.value}] {c.challenge}"
        for c in list(state.albert_challenge_map.values())[:20]
    ) or "(no Albert challenges)"
    claims = []
    for b in state.evidence[:10]:
        for c in b.claims[:5]:
            claims.append(f"- {c.claim} {c.source_refs}")
    claims_txt = "\n".join(claims[:30]) or "(no evidence claims)"
    return (
        f"ORIGINAL QUESTION:\n{state.original_question}\n\n"
        f"BRIEF:\n{state.research_brief or '(none)'}\n\n"
        f"ISSUES:\n{issues}\n\n"
        f"ALBERT CHALLENGES:\n{challenges}\n\n"
        f"EVIDENCE CLAIMS:\n{claims_txt}\n"
    )


class RealSynthesizer:
    """LLM synthesis brain: one structured call -> prose per §22 section."""

    def write_sections(self, state: ResearchState) -> dict[str, str]:
        user = (
            f"{_render_state(state)}\n\n"
            "Write the 9 §22 memo sections (executive_answer, albert_challenge_map, "
            "can_cannot_say, blocking, required_human_decisions, evidence_summary, "
            "risks_assumptions, recommended_next_action, appendix)."
        )
        raw = call_structured(_SYSTEM, user, _SCHEMA, model="haiku")
        # Normalize: always return ALL 9 keys, missing -> "" (assembly never KeyErrors).
        return {k: str(raw.get(k, "") or "") for k in SECTION_KEYS}


class MockSynthesizer:
    """Deterministic synthesis stub (zero LLM): a fixed dict with all 9 keys."""

    def write_sections(self, state: ResearchState) -> dict[str, str]:
        n_ch = len(state.albert_challenge_map)
        n_ev = len(state.evidence)
        body = {
            "executive_answer": f"（stub）對「{state.original_question}」的初步回答。",
            "albert_challenge_map": f"（stub）共 {n_ch} 條 Albert 質疑，依狀態標註。",
            "can_cannot_say": "（stub）可以說的：已研究的部分；不能說的：受阻部分。",
            "blocking": "（stub）阻擋點見下方標註的 blocker 清單。",
            "required_human_decisions": "（stub）需要人類定奪的決策列於此。",
            "evidence_summary": f"（stub）證據摘要：{n_ev} 個 evidence bundle。",
            "risks_assumptions": "（stub）主要風險與假設。",
            "recommended_next_action": "（stub）建議的下一步行動。",
            "appendix": "（stub）附錄：來源與引用。",
        }
        return {k: body[k] for k in SECTION_KEYS}
