"""Real-brain structured-output WIRING tests (deterministic, NO real LLM).

Each test monkeypatches the sdk_client call the brain uses with a SCRIPTED
return, then asserts the brain returns the right typed object. This validates
the node's schema wiring without spending an LLM call. Live behavior is covered
by the opt-in tests in test_real_live.py.
"""
from __future__ import annotations

from cn5_research_cos.brains import interfaces
from cn5_research_cos.brains.real import (RealCompressor, RealIssueExpander,
                                          RealResearcher, RealScorer,
                                          RealSkeptic, RealSourceCritic)
from cn5_research_cos.llm import sdk_client
from cn5_research_cos.models import (Claim, EvidenceBundle, IssueNode,
                                     IssueStatus, IssueType, ReadinessScore,
                                     ResearchState, Source, SourceQuality)


def _state() -> ResearchState:
    return ResearchState(run_id="r", original_question="Can AI research overnight?")


def test_real_brains_satisfy_protocols():
    assert isinstance(RealIssueExpander(), interfaces.IssueExpander)
    assert isinstance(RealResearcher(), interfaces.Researcher)
    assert isinstance(RealSourceCritic(), interfaces.SourceCritic)
    assert isinstance(RealSkeptic(), interfaces.Skeptic)
    assert isinstance(RealCompressor(), interfaces.Compressor)
    assert isinstance(RealScorer(), interfaces.Scorer)


def test_issue_expander_returns_typed_nodes(monkeypatch):
    scripted = {
        "issues": [
            {"title": "Root question", "description": "what to answer",
             "issue_type": "root_question", "impact": 4, "confidence": 1},
            {"title": "ROI", "description": "business value",
             "issue_type": "roi", "impact": 4, "confidence": 1},
        ]
    }
    monkeypatch.setattr(sdk_client, "call_structured", lambda *a, **k: scripted)
    state = _state()
    nodes = RealIssueExpander().expand(state, now="t0")
    assert len(nodes) == 2
    assert all(isinstance(n, IssueNode) for n in nodes)
    assert nodes[0].issue_type == IssueType.root_question
    assert nodes[1].issue_type == IssueType.roi
    # written into the state issue_map
    assert len(state.issue_map) == 2
    assert all(n.last_updated == "t0" for n in nodes)


def test_issue_expander_no_double_seed(monkeypatch):
    scripted = {"issues": [{"title": "X", "description": "d",
                            "issue_type": "risk", "impact": 3, "confidence": 1}]}
    monkeypatch.setattr(sdk_client, "call_structured", lambda *a, **k: scripted)
    state = _state()
    RealIssueExpander().expand(state, now="t0")
    again = RealIssueExpander().expand(state, now="t1")
    assert again == []  # already expanded -> no-op
    assert len(state.issue_map) == 1


def test_researcher_maps_websearch_findings(monkeypatch):
    scripted = {
        "claims": [
            {"claim": "Autonomous overnight research is feasible",
             "confidence": 4, "source_indices": [0], "notes": "n"},
        ],
        "sources": [
            {"title": "ODR paper", "url": "https://example.com/odr",
             "source_type": "primary", "quality": "high"},
        ],
        "missing_evidence": ["cost data"],
        "coverage_gaps": ["internal benchmarks"],
    }
    monkeypatch.setattr(sdk_client, "call_structured_websearch", lambda *a, **k: scripted)
    state = _state()
    from cn5_research_cos.artifacts import issue_map
    node = issue_map.add(state, title="Feasibility", description="d",
                         issue_type=IssueType.technical, status=IssueStatus.open, now="t0")
    bundle = RealResearcher().research(state, node.id)
    assert isinstance(bundle, EvidenceBundle)
    assert bundle.issue_id == node.id
    assert len(bundle.sources) == 1
    assert bundle.sources[0].url == "https://example.com/odr"
    assert bundle.sources[0].quality == SourceQuality.high
    assert len(bundle.claims) == 1
    # claim source_refs resolved from source_indices -> source ids
    assert bundle.claims[0].source_refs == [bundle.sources[0].id]
    assert bundle.missing_evidence == ["cost data"]


def test_source_critic_annotates_quality(monkeypatch):
    scripted = {
        "sources": [{"id": "S-1", "quality": "low", "source_type": "marketing"}],
        "claims": [{"index": 0, "confidence": 2, "notes": "weak source"}],
    }
    monkeypatch.setattr(sdk_client, "call_structured", lambda *a, **k: scripted)
    bundle = EvidenceBundle(
        query="q", issue_id="I-1",
        sources=[Source(id="S-1", title="Vendor blog", quality=SourceQuality.unknown)],
        claims=[Claim(claim="c", source_refs=["S-1"], confidence=4)],
    )
    out = RealSourceCritic().review(bundle)
    assert isinstance(out, EvidenceBundle)
    assert out.sources[0].quality == SourceQuality.low
    assert out.claims[0].confidence == 2


def test_skeptic_returns_counterarguments(monkeypatch):
    scripted = {"counterarguments": ["selection bias", "marketing spin"]}
    monkeypatch.setattr(sdk_client, "call_structured", lambda *a, **k: scripted)
    out = RealSkeptic().counter(_state(), EvidenceBundle(query="q"))
    assert out == ["selection bias", "marketing spin"]


def test_compressor_adds_cited_summary(monkeypatch):
    scripted = {"summary": "Overnight research feasible [S-1].", "key_points": ["p1"]}
    monkeypatch.setattr(sdk_client, "call_structured", lambda *a, **k: scripted)
    bundle = EvidenceBundle(query="q", sources=[Source(id="S-1", title="t")])
    out = RealCompressor().compress(bundle)
    assert isinstance(out, EvidenceBundle)
    assert any("Overnight research feasible" in s for s in out.suggested_followups)


def test_scorer_returns_readiness(monkeypatch):
    scripted = {
        "albert_challenge_readiness": 3, "decision_readiness": 2,
        "research_exhaustion_readiness": 2, "human_bottleneck_clarity": 4,
        "should_continue": True, "reason": "still gaps",
    }
    monkeypatch.setattr(sdk_client, "call_structured", lambda *a, **k: scripted)
    out = RealScorer().score(_state())
    assert isinstance(out, ReadinessScore)
    assert out.albert_challenge_readiness == 3
    assert out.should_continue is True


# --------------------------------------------------------------------------- #
# RealResearcher async path (P2 accel increment 2)
# --------------------------------------------------------------------------- #
def test_researcher_async_uses_pool(monkeypatch):
    """research_async routes its WebSearch through the pool's run_with_retry (so
    rate-limit retries release the permit), returning the same typed bundle."""
    import asyncio

    scripted = {
        "sources": [{"title": "ODR", "url": "https://x/odr",
                     "source_type": "secondary", "quality": "medium"}],
        "claims": [{"claim": "viable", "confidence": 3, "source_indices": [0]}],
        "missing_evidence": ["cost"], "coverage_gaps": ["internal"],
    }

    class _FakePool:
        def __init__(self):
            self.calls = []

        async def run_with_retry(self, user, **kw):
            self.calls.append(kw)
            return scripted

    pool = _FakePool()
    state = _state()
    bundle = asyncio.run(RealResearcher().research_async(state, "I1", pool=pool))

    assert isinstance(bundle, EvidenceBundle)
    assert bundle.issue_id == "I1"
    assert len(bundle.sources) == 1 and bundle.sources[0].id == "S-I1-0"
    assert bundle.claims and bundle.claims[0].source_refs == ["S-I1-0"]
    # it actually went through the pool's retry-with-release path
    assert len(pool.calls) == 1
    assert pool.calls[0]["schema"] is not None
    # acquired WITH the WebSearch tool
    assert pool.calls[0]["allowed_tools"] == ["WebSearch"]


def test_researcher_async_falls_back_to_sync_without_pool(monkeypatch):
    """research_async(pool=None) uses the sync websearch call (back-compat)."""
    import asyncio

    scripted = {"sources": [], "claims": []}
    monkeypatch.setattr(sdk_client, "call_structured_websearch",
                        lambda *a, **k: scripted)
    bundle = asyncio.run(RealResearcher().research_async(_state(), "I2", pool=None))
    assert isinstance(bundle, EvidenceBundle)
    assert bundle.issue_id == "I2"
