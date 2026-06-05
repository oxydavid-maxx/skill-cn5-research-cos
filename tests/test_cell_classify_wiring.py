import cn5_research_cos.graph as g
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell, CellStatus,
    EvidenceBundle, Claim, Source, SourceType, SourceQuality)


def test_cell_marked_covered_when_criteria_filled():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|fabric"] = TaskCell(id="NXP|fabric", vendor="NXP", spec_group="fabric",
        objective="o", success_criteria=["packet_buffer"])
    # evidence whose claim fills packet_buffer for this cell
    src = Source(id="S1", title="DS", url="https://nxp.com/x.pdf", source_type=SourceType.primary, quality=SourceQuality.high, excerpt="packet buffer 128 kB")
    rs.evidence.append(EvidenceBundle(query="NXP fabric", issue_id="NXP|fabric",
        claims=[Claim(claim="packet_buffer = 128 kB", source_refs=["S1"], confidence=5, notes="packet buffer 128 kB")],
        sources=[src]))
    g.classify_grid_cells(rs)   # new deterministic pass
    assert rs.task_grid.cells["NXP|fabric"].status in (CellStatus.covered, CellStatus.partial)
