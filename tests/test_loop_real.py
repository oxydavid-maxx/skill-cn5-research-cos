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


_WEBSEARCH_RESULT = {
    "sources": [{"title": "ODR overview", "url": "https://example.com/odr",
                 "source_type": "secondary", "quality": "medium"}],
    "claims": [{"claim": "Overnight autonomous research is increasingly viable",
                "confidence": 3, "source_indices": [0], "notes": "n"}],
    "missing_evidence": ["cost data"],
    "coverage_gaps": ["internal benchmarks"],
}


def _fake_websearch(system, user, schema, **kw):
    return dict(_WEBSEARCH_RESULT)


# --- Fake SDK client so the REAL async fan-out path (AsyncSessionPool ->
# ClaudeSession.ask_async) runs OFFLINE/deterministically. The researcher now
# uses the async session pool (not call_structured_websearch), so we script the
# SDK client itself: every WebSearch turn yields the canned StructuredOutput. ---
class _ToolBlock:
    def __init__(self, payload):
        self.name = "StructuredOutput"
        self.input = payload


class _Assistant:
    def __init__(self, content):
        self.content = content


class _Result:
    def __init__(self):
        self.total_cost_usd = 0.001
        self.usage = {"input_tokens": 1, "output_tokens": 1}
        self.is_error = False


class _FakeWSClient:
    def __init__(self, options=None):
        self.options = options

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def query(self, user):
        self._last = user

    def receive_response(self):
        return self._gen()

    async def _gen(self):
        yield _Assistant([_ToolBlock(dict(_WEBSEARCH_RESULT))])
        yield _Result()


def test_loop_runs_with_real_brains(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk_client, "call_structured", _fake_call_structured)
    monkeypatch.setattr(sdk_client, "call_structured_websearch", _fake_websearch)
    # The real researcher's async fan-out uses the AsyncSessionPool/ClaudeSession;
    # patch the SDK client so it never spawns a real `claude` (offline + free).
    monkeypatch.setattr(sdk_client, "ClaudeSDKClient", _FakeWSClient)

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
