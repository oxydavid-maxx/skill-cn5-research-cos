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


# --------------------------------------------------------------------------- #
# P5c: per-CLAIM verbatim quote. The schema must expose a `quote` field (a
# verbatim span copied from one of the claim's cited sources), and _build_bundle
# must map it into claim.notes — which is what citation/verify reads via
# _quote_of. Without this, _quote_of falls back to claim.claim (the synthesized,
# paraphrased claim text) which is never a verbatim source substring -> the web
# verify wrongly rejects every real claim.
# --------------------------------------------------------------------------- #
def test_research_schema_has_per_claim_quote_field():
    from cn5_research_cos.brains.real import _RESEARCH_SCHEMA
    claim_props = _RESEARCH_SCHEMA["properties"]["claims"]["items"]["properties"]
    assert "quote" in claim_props, "research schema must expose a per-claim `quote`"
    assert claim_props["quote"]["type"] == "string"


def test_build_bundle_maps_quote_into_notes():
    """The per-claim `quote` (verbatim source span) is stored in claim.notes so
    citation/verify's _quote_of reads the verbatim quote, not the claim text."""
    excerpt = (
        "The MIPI I3C controller assigns each device a dynamic address during the "
        "DAA procedure before any data transfer can begin on the bus."
    )
    quote = "assigns each device a dynamic address during the DAA procedure"
    raw = {
        "sources": [{
            "title": "MIPI I3C spec", "url": "http://x",
            "source_type": "secondary", "quality": "high", "excerpt": excerpt,
        }],
        "claims": [{
            "claim": "I3C uses dynamic address assignment",  # paraphrase, NOT verbatim
            "source_indices": [0], "confidence": 4, "quote": quote,
        }],
    }
    bundle = RealResearcher._build_bundle(raw, "DAA addressing", "I-1")
    claim = bundle.claims[0]
    # the verbatim quote landed in notes (where _quote_of reads it)...
    assert claim.notes == quote
    # ...and it is a genuine substring of the cited source's excerpt.
    assert claim.notes in bundle.sources[0].excerpt
    # the synthesized claim text remains separate and is NOT used as the quote.
    assert claim.claim != claim.notes


def test_quote_field_drives_web_verification():
    """End-to-end through _build_bundle: the per-claim quote (substring of the
    source excerpt) makes the web verifier pass even though claim.claim is a
    paraphrase that would NOT verify."""
    excerpt = (
        "The MIPI I3C controller assigns each device a dynamic address during the "
        "DAA procedure before any data transfer can begin on the bus."
    )
    quote = "assigns each device a dynamic address during the DAA procedure"
    raw = {
        "sources": [{
            "title": "spec", "url": "http://x", "source_type": "secondary",
            "quality": "high", "excerpt": excerpt,
        }],
        "claims": [{
            "claim": "I3C uses dynamic address assignment",
            "source_indices": [0], "confidence": 4, "quote": quote,
        }],
    }
    bundle = RealResearcher._build_bundle(raw, "t", "I-1")
    sources = {s.id: s for s in bundle.sources}
    source_texts = {s.id: s.excerpt for s in bundle.sources}
    results = cverify.verify_claims(bundle.claims, sources, source_texts)
    assert results[0].verified is True
