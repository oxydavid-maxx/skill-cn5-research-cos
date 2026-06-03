"""Task 7 (P5): the terminal/synthesize seam (node_human_review) assembles + gates
the §22 memo and stores it onto rs.final_memo. The H6 interrupt remains the wired
seam before END (P3); enable_h6=False (run_loop default) passes through to END.
"""
from cn5_research_cos.graph import run_loop, _build_and_gate_memo
from cn5_research_cos.brains import build_brains
from cn5_research_cos.models import (
    AuditResult, AuditVerdict, ReadinessScore, ResearchState, Risk,
)


def test_run_loop_produces_final_memo(tmp_path):
    final = run_loop(ResearchState(run_id="r", original_question="q"),
                     base_dir=tmp_path, max_iterations=8, now="t0")
    # the memo was assembled + rendered at the terminal seam
    assert final.final_memo is not None
    assert "§22 Decision Memo" in final.final_memo
    # all 9 §22 section titles are present in the rendered memo
    for token in ("Executive Answer", "Albert Challenge Map", "Appendix"):
        assert token in final.final_memo


def test_build_and_gate_memo_emits_when_clean(tmp_path):
    rs = ResearchState(run_id="r", original_question="q")
    rs.last_audit = AuditResult(verdict=AuditVerdict.exhausted, degraded=False,
                                premature_end_risk=Risk.low,
                                research_drift_risk=Risk.low)
    rs.readiness_score = ReadinessScore(
        albert_challenge_readiness=5, decision_readiness=5,
        research_exhaustion_readiness=5, human_bottleneck_clarity=5,
        should_continue=False)
    state = {"research_state": rs, "llm": "mock", "explicit_emit": True}
    _build_and_gate_memo(state, rs)
    assert rs.final_memo is not None
    assert "NOT EMITTED" not in rs.final_memo
