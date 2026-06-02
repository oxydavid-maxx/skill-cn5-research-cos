"""run_loop threads RunMetrics + opens a persistent session pool for real brains.

Deterministic: the sdk_client public entry points are monkeypatched (NO live
LLM), and we assert run_loop returns metrics and that a session pool is active
during a real run (so the persistent-session acceleration is wired, not just
present).
"""
from __future__ import annotations

from cn5_research_cos.graph import run_loop
from cn5_research_cos.llm import sdk_client
from cn5_research_cos.llm.metrics import RunMetrics
from cn5_research_cos.models import ResearchState


def _fake_call_structured(system, user, schema, **kw):
    # assert a pool is active during the real run (acceleration wired in)
    assert sdk_client._ACTIVE_POOL is not None
    props = set(schema.get("properties", {}))
    if "issues" in props:
        return {"issues": [
            {"title": "Root", "description": "d", "issue_type": "root_question",
             "impact": 4, "confidence": 1},
            {"title": "Competitor parity", "description": "d", "issue_type": "competitor",
             "impact": 4, "confidence": 1},
        ]}
    if "counterarguments" in props:
        return {"counterarguments": ["bias"]}
    if "summary" in props:
        return {"summary": "s [S-1].", "key_points": ["p"]}
    if "albert_challenge_readiness" in props:
        return {"albert_challenge_readiness": 4, "decision_readiness": 4,
                "research_exhaustion_readiness": 4, "human_bottleneck_clarity": 4,
                "should_continue": False, "reason": "ok"}
    if "albert_challenges" in props:
        return {"verdict": "exhausted",
                "albert_challenges": [{"challenge": "win?", "why_albert_would_ask": "p",
                                       "status": "needs_bu_judgment"}],
                "weak_points": [], "missing_business_context": [],
                "questions_albert_would_ask": [],
                "premature_end_risk": {"level": "low"},
                "research_drift_risk": {"level": "low"},
                "recommended_next_action": "synthesize",
                "rationale": "r", "readiness_score_delta": 0}
    return {"sources": [], "claims": []}


def _fake_websearch(system, user, schema, **kw):
    return {"sources": [{"title": "t", "url": "https://x", "source_type": "secondary",
                         "quality": "medium"}],
            "claims": [{"claim": "c", "confidence": 3, "source_indices": [0], "notes": "n"}],
            "missing_evidence": [], "coverage_gaps": []}


def test_run_loop_returns_metrics_and_opens_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk_client, "call_structured", _fake_call_structured)
    monkeypatch.setattr(sdk_client, "call_structured_websearch", _fake_websearch)

    metrics = RunMetrics()
    final, returned_metrics = run_loop(
        ResearchState(run_id="rm", original_question="Can AI research overnight?"),
        base_dir=tmp_path, max_iterations=6, now="t0", llm="real",
        metrics=metrics, return_metrics=True,
    )
    assert returned_metrics is metrics
    assert final.iteration_count >= 1
    # pool is closed again after the run
    assert sdk_client._ACTIVE_POOL is None


def test_run_loop_mock_back_compat(tmp_path):
    """No metrics arg, mock llm -> returns a bare ResearchState (P1 signature)."""
    final = run_loop(ResearchState(run_id="rb", original_question="q"),
                     base_dir=tmp_path, max_iterations=4, now="t0")
    assert isinstance(final, ResearchState)
    assert final.iteration_count >= 1
