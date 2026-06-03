"""Task 2 (P5): the web researcher captures a per-source verbatim excerpt so the
P4b citation verifier (web difflib >= 0.85) has source text to verify against.

NOTE (deviation from plan): RealResearcher.research routes through
``sdk_client.call_structured_websearch`` (not ``call_structured``), and the real
research schema maps claims to sources via ``source_indices`` (0-based) with the
verbatim quote stashed in ``notes`` — so this test monkeypatches the real entry
point and uses the real field shapes. Intent (excerpt populated + readable by
citation/verify) is unchanged.
"""
from cn5_research_cos.brains.real import RealResearcher
from cn5_research_cos.models import IssueNode, IssueStatus, IssueType, ResearchState
from cn5_research_cos.llm import sdk_client
from cn5_research_cos.citation import verify as cverify


def _state_with_issue() -> ResearchState:
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map["I-1"] = IssueNode(
        id="I-1", title="DAA addressing", description="how DAA assigns addresses",
        issue_type=IssueType.technical, status=IssueStatus.open, impact=3, confidence=1,
    )
    return rs


def test_web_source_carries_excerpt(monkeypatch):
    excerpt = "The controller assigns a dynamic address during DAA."

    def fake(system, user, schema, **kw):
        return {
            "sources": [{
                "title": "MIPI I3C spec", "url": "http://x",
                "source_type": "secondary", "quality": "high",
                "excerpt": excerpt,
            }],
            "claims": [{
                "claim": "DAA assigns addresses",
                "source_indices": [0],
                "confidence": 4,
                "notes": "assigns a dynamic address",
            }],
        }

    monkeypatch.setattr(sdk_client, "call_structured_websearch", fake)
    rs = _state_with_issue()
    bundle = RealResearcher().research(rs, "I-1")

    assert bundle.sources, "expected at least one source"
    src = bundle.sources[0]
    assert src.origin == "web"
    assert src.excerpt == excerpt

    # The excerpt is exactly what citation/verify reads as the source text: the
    # claim's verbatim quote (notes) is found in it via difflib >= 0.85.
    sources = {s.id: s for s in bundle.sources}
    source_texts = {s.id: s.excerpt for s in bundle.sources}
    results = cverify.verify_claims(bundle.claims, sources, source_texts)
    assert results[0].verified is True
    assert results[0].origin == "web"
