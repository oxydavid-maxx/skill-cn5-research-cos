import cn5_research_cos.graph as g
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell, CellStatus,
    EvidenceBundle, FieldObservation, Source, SourceType, SourceQuality)


def _rs():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|f"] = TaskCell(id="NXP|f", vendor="NXP", spec_group="f",
        objective="o", success_criteria=["packet_buffer"])
    return rs


def _bundle_with_obs():
    src = Source(id="S1", title="DS", url="https://nxp.com/x.pdf",
                 source_type=SourceType.primary, quality=SourceQuality.high)
    return EvidenceBundle(query="q", issue_id="NXP|f", sources=[src],
        observations=[FieldObservation(field="packet_buffer", value="128 kB", source_ref="S1")],
        public_exhausted=True)


def test_changed_cell_resets_stall_and_records_moved():
    rs = _rs()
    rs.evidence.append(_bundle_with_obs())
    g.classify_grid_cells(rs)
    cell = rs.task_grid.cells["NXP|f"]
    assert cell.stalled_cycles == 0 and cell.last_status == CellStatus.covered and cell.last_filled == 1
    assert "NXP|f" in rs.obs_prev.get("grid_moved", [])


def test_unchanged_cell_increments_stall():
    rs = _rs()
    rs.evidence.append(_bundle_with_obs())
    g.classify_grid_cells(rs)
    rs.obs_prev["grid_moved"] = []
    g.classify_grid_cells(rs)
    cell = rs.task_grid.cells["NXP|f"]
    assert cell.stalled_cycles == 1 and "NXP|f" not in rs.obs_prev.get("grid_moved", [])
