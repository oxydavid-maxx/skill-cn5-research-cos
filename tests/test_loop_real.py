"""Loop wiring with --llm real, driven by SCRIPTED sdk_client returns (NO live LLM).

Proves the graph runs end-to-end with the real-brain bundle injected at the
factory hook: same topology, deterministic control, real nodes. The LLM calls
are monkeypatched so this stays fast/offline; live behavior is in the opt-in
tests. We patch both sdk_client functions because real brains funnel through them.
"""
from __future__ import annotations

import pytest

from cn5_research_cos.graph import run_loop
from cn5_research_cos.llm import sdk_client
from cn5_research_cos.models import ResearchState


def _fake_call_structured(system, user, schema, **kw):
    """Return a minimal schema-valid dict by inspecting which brain's schema this is."""
    props = set(schema.get("properties", {}))
    if "issues" in props:
        return {"issues": [
            {"title": "Root question", "description": "what to answer",
             "issue_type": "root_question", "impact": 4, "confidence": 1},
            {"title": "ROI", "description": "value",
             "issue_type": "roi", "impact": 4, "confidence": 1},
            {"title": "Competitor parity", "description": "do rivals have it",
             "issue_type": "competitor", "impact": 4, "confidence": 1},
        ]}
    if "counterarguments" in props:
        return {"counterarguments": ["possible selection bias"]}
    if "summary" in props:
        return {"summary": "Light cited summary [S-1].", "key_points": ["p"]}
    if "albert_challenge_readiness" in props:
        return {"albert_challenge_readiness": 4, "decision_readiness": 4,
                "research_exhaustion_readiness": 4, "human_bottleneck_clarity": 4,
                "should_continue": False, "reason": "saturated"}
    if "albert_challenges" in props:  # Albert simulator
        return {
            "verdict": "exhausted",
            "albert_challenges": [{"challenge": "why win?",
                                   "why_albert_would_ask": "parity",
                                   "status": "needs_bu_judgment"}],
            "weak_points": ["w"],
            "missing_business_context": [],
            "questions_albert_would_ask": [],
            "premature_end_risk": {"level": "low"},
            "research_drift_risk": {"level": "low"},
            "recommended_next_action": "synthesize",
            "rationale": "addressable saturated; residual is human.",
            "readiness_score_delta": 0,
        }
    if "sources" in props and "claims" in props and "missing_evidence" in props:
        # source_critic uses sources+claims but no missing_evidence key
        pass
    if props == {"sources", "claims"}:  # source_critic
        return {"sources": [], "claims": []}
    # researcher (websearch) — handled by the websearch fake
    return {"sources": [], "claims": []}


def _fake_websearch(system, user, schema, **kw):
    return {
        "sources": [{"title": "ODR overview", "url": "https://example.com/odr",
                     "source_type": "secondary", "quality": "medium"}],
        "claims": [{"claim": "Overnight autonomous research is increasingly viable",
                    "confidence": 3, "source_indices": [0], "notes": "n"}],
        "missing_evidence": ["cost data"],
        "coverage_gaps": ["internal benchmarks"],
    }


def test_loop_runs_with_real_brains(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk_client, "call_structured", _fake_call_structured)
    monkeypatch.setattr(sdk_client, "call_structured_websearch", _fake_websearch)

    final = run_loop(
        ResearchState(run_id="r-real", original_question="Can AI research overnight?"),
        base_dir=tmp_path, max_iterations=6, now="t0", llm="real",
    )
    # Loop produced a populated state via the real-brain bundle.
    assert final.readiness_score is not None
    assert final.iteration_count >= 1
    assert final.issue_map, "real issue_expander populated the issue map"
    assert final.evidence, "real researcher produced evidence bundles"
    # sources came from the (scripted) websearch path, mapped into Source models
    assert any(s.url for b in final.evidence for s in b.sources)
    assert final.last_audit is not None
    assert (tmp_path / "r-real" / "state.json").exists()
