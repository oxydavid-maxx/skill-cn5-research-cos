from cn5_research_cos.decision import cell_synthesis as cs
from cn5_research_cos.models import (TaskCell, EvidenceBundle, FieldObservation,
    Source, SourceType, SourceQuality)


def _cell():
    return TaskCell(id="NXP|f", vendor="NXP", spec_group="f", objective="o",
                    success_criteria=["packet_buffer", "vlan_table"])


def _bundle(obs, srcs):
    return EvidenceBundle(query="q", issue_id="NXP|f", observations=obs, sources=srcs)


def test_primary_observation_fills_field():
    s = Source(id="S1", title="DS", url="https://nxp.com/x.pdf",
               source_type=SourceType.primary, quality=SourceQuality.high)
    o = FieldObservation(field="packet_buffer", value="128 kB", source_ref="S1")
    syn = cs.synthesize_cell(_cell(), [_bundle([o], [s])])
    assert "packet_buffer" in syn.filled and syn.chosen["packet_buffer"] == "128 kB"


def test_incorrect_source_observation_dropped():
    s = Source(id="S2", title="blog", url="http://b", source_type=SourceType.marketing,
               quality=SourceQuality.low)   # grade_source -> "incorrect"
    o = FieldObservation(field="packet_buffer", value="999 kB", source_ref="S2")
    syn = cs.synthesize_cell(_cell(), [_bundle([o], [s])])
    assert "packet_buffer" not in syn.filled


def test_contradiction_resolved_by_primary():
    s_blog = Source(id="B", title="b", url="http://b", source_type=SourceType.secondary,
                    quality=SourceQuality.medium)
    s_ds = Source(id="DS", title="ds", url="https://nxp.com/x.pdf",
                  source_type=SourceType.primary, quality=SourceQuality.high)
    obs = [FieldObservation(field="vlan_table", value="1024", source_ref="B"),
           FieldObservation(field="vlan_table", value="4096", source_ref="DS")]
    syn = cs.synthesize_cell(_cell(), [_bundle(obs, [s_blog, s_ds])])
    assert syn.chosen["vlan_table"] == "4096" and "vlan_table" in syn.contradictions


def test_field_outside_criteria_ignored():
    s = Source(id="S1", title="DS", url="https://nxp.com/x.pdf",
               source_type=SourceType.primary, quality=SourceQuality.high)
    o = FieldObservation(field="not_a_criterion", value="x", source_ref="S1")
    syn = cs.synthesize_cell(_cell(), [_bundle([o], [s])])
    assert syn.filled == set()
