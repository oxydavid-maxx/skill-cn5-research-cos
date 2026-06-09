import cn5_research_cos.graph as g
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell, CellStatus,
    EvidenceBundle, FieldObservation, Source, SourceType, SourceQuality)


def _rs_with_cell():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|fabric"] = TaskCell(id="NXP|fabric", vendor="NXP",
        spec_group="fabric", objective="o", success_criteria=["packet_buffer"])
    return rs


def test_cell_covered_when_observation_fills_criterion():
    rs = _rs_with_cell()
    src = Source(id="S1", title="DS", url="https://nxp.com/x.pdf",
                 source_type=SourceType.primary, quality=SourceQuality.high)
    rs.evidence.append(EvidenceBundle(query="q", issue_id="NXP|fabric", sources=[src],
        observations=[FieldObservation(field="packet_buffer", value="128 kB", source_ref="S1")],
        public_exhausted=True))
    g.classify_grid_cells(rs)
    assert rs.task_grid.cells["NXP|fabric"].status == CellStatus.covered


def test_cell_open_when_empty_and_not_exhausted():
    rs = _rs_with_cell()
    src = Source(id="S1", title="x", url="https://x/p.html",
                 source_type=SourceType.secondary, quality=SourceQuality.medium)
    rs.evidence.append(EvidenceBundle(query="q", issue_id="NXP|fabric", sources=[src],
        observations=[], public_exhausted=False))
    g.classify_grid_cells(rs)
    assert rs.task_grid.cells["NXP|fabric"].status == CellStatus.open


def test_cell_na_when_empty_and_exhausted():
    rs = _rs_with_cell()
    src = Source(id="S1", title="x", url="https://x/p.html",
                 source_type=SourceType.secondary, quality=SourceQuality.medium)
    rs.evidence.append(EvidenceBundle(query="q", issue_id="NXP|fabric", sources=[src],
        observations=[], public_exhausted=True))
    g.classify_grid_cells(rs)
    assert rs.task_grid.cells["NXP|fabric"].status == CellStatus.na
