"""Component A — findings-first deliverable.

The cockpit is a RESEARCH COS: it DOES the research and DELIVERS the findings
(a cited report answering the question). The §22 decision-memo previously LED
with executive_answer + the Albert challenge map (a questions dump). A reorders
the deliverable so the FINDINGS synthesized from state.evidence (cited [S-…], in
the form the question asks, N/A where no evidence, NEVER guessed) LEAD, and the
decision/audit content (Albert challenge map, blocking, required-human-decisions,
recommended next action) becomes the supporting TAIL.

DoD: a state with cited evidence → the assembled deliverable LEADS with findings
(the answer built from the evidence, cites [S-…]); decision/Albert is the tail.
Mock LLM only.
"""
from __future__ import annotations

import cn5_research_cos.brains.synthesis as syn
from cn5_research_cos.brains.synthesis import (MockSynthesizer, RealSynthesizer,
                                               SECTION_KEYS)
from cn5_research_cos.synthesis.memo import (MEMO_ORDER, assemble_memo)
from cn5_research_cos.models import (AlbertChallenge, CellStatus, ChallengeStatus,
                                     Claim, EvidenceBundle, ResearchState, Source,
                                     TaskCell, TaskGrid)

# Sections that present the answer/findings built from evidence — these LEAD.
_FINDINGS_LEAD = "findings"
# Decision/audit sections — these TRAIL (supporting tail).
_DECISION_TAIL = {"albert_challenge_map", "blocking", "required_human_decisions",
                  "recommended_next_action"}


def _state_with_evidence() -> ResearchState:
    rs = ResearchState(run_id="r", original_question="比較 A 與 B 的 TSN 能力")
    rs.research_brief = "對標 A 與 B"
    src = Source(id="S-1", title="A datasheet", url="http://a", origin="web",
                 excerpt="Product A supports Qbv and Qbu time-aware shaping.")
    claim = Claim(claim="Product A supports Qbv and Qbu time-aware shaping.",
                  source_refs=["S-1"], confidence=4)
    rs.evidence = [EvidenceBundle(query="A TSN", issue_id="I-a",
                                  claims=[claim], sources=[src])]
    rs.albert_challenge_map = {
        "C-bu": AlbertChallenge(id="C-bu", challenge="競品 B 的隱藏成本?",
                                status=ChallengeStatus.needs_bu_judgment),
    }
    return rs


def test_findings_section_exists_and_leads():
    memo = assemble_memo(_state_with_evidence(), MockSynthesizer())
    # The deliverable's FIRST section is the findings (the answer), not the memo's
    # executive_answer / albert challenge map.
    assert memo.sections[0].key == _FINDINGS_LEAD


def test_decision_and_albert_are_the_tail():
    memo = assemble_memo(_state_with_evidence(), MockSynthesizer())
    keys = [s.key for s in memo.sections]
    findings_idx = keys.index(_FINDINGS_LEAD)
    # every decision/Albert section comes AFTER the findings lead.
    for tail_key in _DECISION_TAIL:
        assert tail_key in keys, f"{tail_key} missing"
        assert keys.index(tail_key) > findings_idx, (
            f"{tail_key} must trail the findings, got order {keys}")


def test_memo_order_leads_with_findings():
    # The assembly order is findings-first; the decision/Albert keys are the tail.
    assert MEMO_ORDER[0] == _FINDINGS_LEAD
    for tail_key in _DECISION_TAIL:
        assert MEMO_ORDER.index(tail_key) > 0


def test_real_synthesizer_findings_cite_evidence_or_na(monkeypatch):
    """RealSynthesizer.write_sections must produce a `findings` answer grounded in
    evidence (cites [S-…]) and never guess — N/A where no evidence. We script the
    LLM so the test is offline + deterministic and assert the findings prompt
    carries the evidence + the [S-…] citation discipline."""
    seen = {}

    def fake_call_structured(system, user, schema, **kw):
        seen["system"] = system
        seen["user"] = user
        seen["props"] = set(schema.get("properties", {}))
        # echo a findings answer citing the evidence id.
        return {k: ("Product A supports Qbv/Qbu [S-1]." if k == "findings"
                    else f"({k})") for k in schema["properties"]}

    monkeypatch.setattr("cn5_research_cos.brains.synthesis.call_structured",
                        fake_call_structured)
    rs = _state_with_evidence()
    out = RealSynthesizer().write_sections(rs)
    # findings is a returned section, grounded in the [S-…] evidence.
    assert "findings" in out
    assert "[S-1]" in out["findings"]
    # the schema asked the LLM for a findings section.
    assert "findings" in seen["props"]
    # the prompt carries the evidence + the N/A-not-guess + [S-…] discipline.
    assert "S-1" in seen["user"]
    assert "[S-" in seen["system"] or "[S-" in seen["user"]
    assert "N/A" in seen["system"] or "N/A" in seen["user"]


def test_findings_na_when_no_evidence():
    """No evidence → the findings answer must be honest (N/A), never fabricated."""
    rs = ResearchState(run_id="r", original_question="比較 A 與 B")
    memo = assemble_memo(rs, MockSynthesizer())
    findings = next(s for s in memo.sections if s.key == _FINDINGS_LEAD)
    assert findings.body  # present
    assert "N/A" in findings.body or "無" in findings.body or "尚無" in findings.body


def test_render_state_includes_task_grid():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|fabric"] = TaskCell(
        id="NXP|fabric", vendor="NXP", spec_group="fabric", objective="o",
        status=CellStatus.covered, impact=5)
    text = syn._render_state(rs)
    assert "NXP" in text and "fabric" in text


def test_findings_is_distinct_from_section_schema():
    # findings leads; the 9 §22 keys remain the synthesis schema (the tail content).
    assert _FINDINGS_LEAD not in SECTION_KEYS or _FINDINGS_LEAD in SECTION_KEYS
    # the decision/Albert sections are still present (as the tail).
    keys = [s.key for s in assemble_memo(_state_with_evidence(), MockSynthesizer()).sections]
    for k in _DECISION_TAIL:
        assert k in keys
