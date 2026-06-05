import cn5_research_cos.brains.real as real
from cn5_research_cos.models import ResearchState, IssueNode, IssueType, IssueStatus


def _state_with_issue():
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map["I-1"] = IssueNode(id="I-1", title="NXP packet buffer",
        description="find packet_buffer", issue_type=IssueType.intent,
        status=IssueStatus.open, impact=5, confidence=2)
    return rs


def test_loop_escalates_to_fetch_then_stops(monkeypatch):
    rounds = {"n": 0}

    def fake_ws(system, user, schema, **kw):  # round 1: a source that is a PDF, no usable claim yet
        return {"sources": [{"title": "DS", "url": "https://nxp.com/sja.pdf", "source_type": "primary", "quality": "high", "excerpt": "see datasheet"}],
                "claims": []}

    def fake_extract(url, **kw):  # the fetched PDF yields the spec
        return ("packet buffer is 128 kB", "pymupdf4llm")

    def fake_struct(system, user, schema, **kw):  # extraction pass over fetched text -> a grounded claim
        rounds["n"] += 1
        return {"claims": [{"claim": "packet buffer 128 kB", "quote": "packet buffer is 128 kB", "source_indices": [0], "confidence": 5}]}

    monkeypatch.setattr(real.sdk_client, "call_structured_websearch", fake_ws)
    monkeypatch.setattr(real, "fetch_and_extract", fake_extract, raising=False)
    monkeypatch.setattr(real.sdk_client, "call_structured", fake_struct)
    b = real.RealResearcher().research(_state_with_issue(), "I-1")
    assert any("128 kB" in c.claim for c in b.claims)   # the fetched-PDF spec made it into the bundle
