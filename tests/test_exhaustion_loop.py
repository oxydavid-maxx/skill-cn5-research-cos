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


def test_escalate_stamps_public_exhausted_true_when_drained(monkeypatch):
    import cn5_research_cos.brains.real as real
    from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell,
        EvidenceBundle, Source, SourceType, SourceQuality)
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|f"] = TaskCell(id="NXP|f", vendor="NXP", spec_group="f",
        objective="o", success_criteria=["packet_buffer"])
    src = Source(id="S-NXP|f-0", title="DS", url="https://nxp.com/x.pdf",
                 source_type=SourceType.primary, quality=SourceQuality.high)
    bundle = EvidenceBundle(query="q", issue_id="NXP|f", sources=[src])
    monkeypatch.setattr(real, "fetch_and_extract", lambda url, **kw: ("packet buffer 128 kB", "pymupdf4llm"), raising=False)
    monkeypatch.setattr(real.RealResearcher, "_extract_from_text",
        staticmethod(lambda text, sid, criteria=None: ([], [real.FieldObservation(field="packet_buffer", value="128 kB", source_ref=sid)])))
    out = real.RealResearcher()._escalate(bundle, rs)
    assert out.public_exhausted is True
    assert any(o.field == "packet_buffer" for o in out.observations)


def test_escalate_no_doc_url_is_vacuously_exhausted(monkeypatch):
    import cn5_research_cos.brains.real as real
    from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell,
        EvidenceBundle, Source, SourceType, SourceQuality)
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|f"] = TaskCell(id="NXP|f", vendor="NXP", spec_group="f",
        objective="o", success_criteria=["packet_buffer"])
    src = Source(id="S1", title="html", url="https://x.com/page.html",
                 source_type=SourceType.secondary, quality=SourceQuality.medium)
    bundle = EvidenceBundle(query="q", issue_id="NXP|f", sources=[src])
    out = real.RealResearcher()._escalate(bundle, rs)
    assert out.public_exhausted is True   # nothing fetchable -> fetch modality vacuously exhausted
