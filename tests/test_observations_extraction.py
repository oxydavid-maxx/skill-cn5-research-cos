import cn5_research_cos.brains.real as real
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell)


def test_build_bundle_maps_observations_filtering_unknown_fields():
    raw = {
        "sources": [{"title": "DS", "url": "https://nxp.com/x.pdf",
                     "source_type": "primary", "quality": "high"}],
        "claims": [],
        "observations": [
            {"field": "packet_buffer", "value": "128 kB", "quote": "...", "confidence": 5, "source_indices": [0]},
            {"field": "not_a_criterion", "value": "x", "source_indices": [0]},
        ],
    }
    b = real.RealResearcher._build_bundle(raw, "t", "NXP|f", ["packet_buffer", "vlan_table"])
    assert len(b.observations) == 1
    o = b.observations[0]
    assert o.field == "packet_buffer" and o.value == "128 kB" and o.source_ref == "S-NXP|f-0"


def test_extract_from_text_returns_claims_and_observations(monkeypatch):
    def fake_struct(system, user, schema, **kw):
        return {"claims": [{"claim": "pb 128", "quote": "packet buffer 128 kB", "confidence": 5}],
                "observations": [{"field": "packet_buffer", "value": "128 kB", "quote": "packet buffer 128 kB", "confidence": 5}]}
    monkeypatch.setattr(real.sdk_client, "call_structured", fake_struct)
    claims, obs = real.RealResearcher._extract_from_text("doc text", "S-1", ["packet_buffer"])
    assert claims and claims[0].source_refs == ["S-1"]
    assert obs and obs[0].field == "packet_buffer" and obs[0].source_ref == "S-1"


def test_cell_criteria_lookup():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|f"] = TaskCell(id="NXP|f", vendor="NXP", spec_group="f",
        objective="o", success_criteria=["packet_buffer"])
    assert real.RealResearcher._cell_criteria(rs, "NXP|f") == ["packet_buffer"]
    assert real.RealResearcher._cell_criteria(rs, "missing") == []
