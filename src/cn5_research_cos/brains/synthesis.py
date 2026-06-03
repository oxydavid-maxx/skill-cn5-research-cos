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

# Component A: the FINDINGS section — the primary deliverable. It is the research
# answer/artifact synthesized from state.evidence (cited [S-…], in the form the
# question asks), and it LEADS the deliverable (synthesis/memo.MEMO_ORDER). It is
# NOT a §22 decision section: SECTION_KEYS stays the 9-key §22 schema; the
# synthesizer fills `findings` PLUS the 9 keys in one structured call.
FINDINGS_KEY = "findings"
# The keys the synthesizer's structured call returns: the findings lead + the 9
# §22 sections (the supporting tail content).
ALL_OUTPUT_KEYS = [FINDINGS_KEY, *SECTION_KEYS]

_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in ALL_OUTPUT_KEYS},
    "required": ALL_OUTPUT_KEYS,
    "additionalProperties": False,
}

_SYSTEM = (
    "You are a research chief-of-staff DELIVERING the findings of a research run "
    "(like GPT-Researcher / Open Deep Research). Your PRIMARY output is the "
    "`findings` section: the answer/artifact that ANSWERS the original question, "
    "SYNTHESIZED ONLY from the supplied evidence claims, in the FORM the question "
    "asks (a comparison table, an analysis, a ranked list, …). EVERY factual "
    "statement in `findings` MUST carry its evidence citation as [S-…] (the source "
    "id from the evidence). Where there is NO evidence for something the question "
    "asks, write 'N/A（無證據）' — NEVER guess, NEVER fabricate a citation. "
    "The 9 §22 sections (executive_answer, albert_challenge_map, can_cannot_say, "
    "blocking, required_human_decisions, evidence_summary, risks_assumptions, "
    "recommended_next_action, appendix) are the SUPPORTING TAIL: they document the "
    "audit/decision posture, not the answer itself. Write in Traditional Chinese; "
    "keep technical terms untranslated. Return STRICT JSON per the schema (one "
    "string per key, including `findings`)."
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
    # Evidence is rendered with its [S-…] source ids so the findings can cite them
    # verbatim. Each claim line shows the claim + the source ids that back it.
    claims = []
    for b in state.evidence[:10]:
        for c in b.claims[:5]:
            refs = " ".join(f"[{sid}]" for sid in c.source_refs) or "[no source]"
            claims.append(f"- {c.claim} {refs}")
    claims_txt = "\n".join(claims[:30]) or "(no evidence claims)"
    sources = []
    for b in state.evidence[:10]:
        for s in b.sources[:5]:
            sources.append(f"- [{s.id}] {s.title} {s.url or ''}".rstrip())
    sources_txt = "\n".join(sources[:30]) or "(no sources)"
    return (
        f"ORIGINAL QUESTION:\n{state.original_question}\n\n"
        f"BRIEF:\n{state.research_brief or '(none)'}\n\n"
        f"EVIDENCE CLAIMS (cite these [S-…] in `findings`):\n{claims_txt}\n\n"
        f"SOURCES:\n{sources_txt}\n\n"
        f"ISSUES:\n{issues}\n\n"
        f"ALBERT CHALLENGES:\n{challenges}\n"
    )


class RealSynthesizer:
    """LLM synthesis brain: one structured call -> prose per §22 section."""

    def write_sections(self, state: ResearchState) -> dict[str, str]:
        user = (
            f"{_render_state(state)}\n\n"
            "FIRST write `findings`: the research answer to the ORIGINAL QUESTION, "
            "synthesized ONLY from the EVIDENCE CLAIMS above, in the form the "
            "question asks, with EVERY factual statement cited as [S-…]. Where the "
            "question asks for something with NO evidence, write 'N/A（無證據）' — "
            "do NOT guess. THEN write the 9 §22 supporting sections "
            "(executive_answer, albert_challenge_map, can_cannot_say, blocking, "
            "required_human_decisions, evidence_summary, risks_assumptions, "
            "recommended_next_action, appendix)."
        )
        raw = call_structured(_SYSTEM, user, _SCHEMA, model="haiku")
        # Normalize: always return findings + ALL 9 keys, missing -> "" so the
        # assembly never KeyErrors.
        return {k: str(raw.get(k, "") or "") for k in ALL_OUTPUT_KEYS}


class MockSynthesizer:
    """Deterministic synthesis stub (zero LLM): a fixed dict with all 9 keys."""

    def write_sections(self, state: ResearchState) -> dict[str, str]:
        n_ch = len(state.albert_challenge_map)
        n_ev = len(state.evidence)
        # Deterministic findings synthesized from evidence: each claim line cites
        # its [S-…] sources; with NO evidence the findings are an honest N/A (the
        # mock NEVER guesses).
        finding_lines: list[str] = []
        for b in state.evidence:
            for c in b.claims:
                refs = " ".join(f"[{sid}]" for sid in c.source_refs)
                finding_lines.append(f"- {c.claim} {refs}".rstrip())
        if finding_lines:
            findings = (f"（stub）針對「{state.original_question}」的研究發現"
                        "（已引用證據）：\n" + "\n".join(finding_lines))
        else:
            findings = (f"（stub）針對「{state.original_question}」目前尚無可引用之"
                        "證據：N/A（無證據，未臆測）。")
        body = {
            "findings": findings,
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
        return {k: body[k] for k in ALL_OUTPUT_KEYS}
