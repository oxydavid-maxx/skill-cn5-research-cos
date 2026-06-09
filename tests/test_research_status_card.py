from cn5_research_cos.observability import reporter as R
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell, CellStatus)


def _grid_rs():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    def cell(cid, v, status, filled, total, stalled=0):
        c = TaskCell(id=cid, vendor=v, spec_group="f", objective="o",
                     success_criteria=[f"k{i}" for i in range(total)])
        c.status = status; c.last_filled = filled; c.stalled_cycles = stalled
        return c
    rs.task_grid.cells["NXP|f"] = cell("NXP|f", "NXP", CellStatus.partial, 3, 5)
    rs.task_grid.cells["BCM|f"] = cell("BCM|f", "Broadcom", CellStatus.blocked, 0, 4)
    rs.task_grid.cells["TI|f"] = cell("TI|f", "TI", CellStatus.na, 0, 4, stalled=3)
    rs.prev_coverage = 1
    rs.obs_prev["grid_moved"] = ["NXP|f"]
    return rs


def test_dashboard_shows_headline_delta_and_actions():
    rs = _grid_rs()
    out = R.render_research_status(rs)
    assert "研究現況" in out
    assert "%" in out and "▲" in out
    assert "NXP" in out and "Broadcom" in out and "TI" in out
    assert "需要你出手" in out or "需內部" in out
    assert rs.prev_coverage == 3


def test_no_progress_cycle_one_line():
    rs = _grid_rs()
    rs.obs_prev["grid_moved"] = []
    rs.prev_coverage = 3
    out = R.render_research_status(rs)
    assert "無新進展" in out
    assert "\n" not in out.strip()


def test_no_grid_returns_empty():
    rs = ResearchState(run_id="r", original_question="q")
    assert R.render_research_status(rs) == ""
