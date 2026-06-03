"""Task 4 (P5): Synthesizer Protocol + mock stub + RealSynthesizer."""
from cn5_research_cos.brains import build_brains
from cn5_research_cos.brains.interfaces import Synthesizer
from cn5_research_cos.brains.synthesis import (ALL_OUTPUT_KEYS, FINDINGS_KEY,
                                               RealSynthesizer, SECTION_KEYS)
from cn5_research_cos.brains import synthesis as synthmod
from cn5_research_cos.models import ResearchState


NINE = [
    "executive_answer", "albert_challenge_map", "can_cannot_say", "blocking",
    "required_human_decisions", "evidence_summary", "risks_assumptions",
    "recommended_next_action", "appendix",
]
# Component A: the synthesizer now returns the findings lead + the 9 §22 keys.
ALL_KEYS = [FINDINGS_KEY, *NINE]


def _state():
    return ResearchState(run_id="r", original_question="q")


def test_section_keys_are_the_nine():
    assert SECTION_KEYS == NINE


def test_build_brains_exposes_synthesizer():
    b = build_brains(llm="mock")
    assert isinstance(b.synthesizer, Synthesizer)
    out = b.synthesizer.write_sections(_state())
    assert isinstance(out, dict)
    assert "executive_answer" in out
    # findings lead + the 9 §22 keys.
    assert set(out.keys()) == set(ALL_KEYS)
    assert FINDINGS_KEY in out


def test_real_synthesizer_returns_findings_plus_nine_keys(monkeypatch):
    def fake(system, user, schema, **kw):
        return {k: f"prose for {k}" for k in ALL_KEYS}

    monkeypatch.setattr(synthmod, "call_structured", fake)
    out = RealSynthesizer().write_sections(_state())
    assert set(out.keys()) == set(ALL_KEYS)
    assert out["executive_answer"] == "prose for executive_answer"
    assert out[FINDINGS_KEY] == f"prose for {FINDINGS_KEY}"


def test_real_synthesizer_tolerates_missing_keys(monkeypatch):
    # A real model that omits a key must not crash assembly: missing -> "".
    def fake(system, user, schema, **kw):
        return {"executive_answer": "only this"}

    monkeypatch.setattr(synthmod, "call_structured", fake)
    out = RealSynthesizer().write_sections(_state())
    assert set(out.keys()) == set(ALL_KEYS)
    assert out["executive_answer"] == "only this"
    assert out["appendix"] == ""
    assert out[FINDINGS_KEY] == ""  # missing findings -> "" (assembly N/A fallback)


def test_all_output_keys_lead_with_findings():
    assert ALL_OUTPUT_KEYS[0] == FINDINGS_KEY
    assert ALL_OUTPUT_KEYS[1:] == SECTION_KEYS
