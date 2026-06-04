import cn5_research_cos.graph as g
from cn5_research_cos.decision import convergence
from cn5_research_cos.models import ResearchState, TaskGrid, TaskCell, CellStatus


class _B:
    class _O:
        def plan(self, rs):
            grid = rs.task_grid or TaskGrid()
            grid.cells.setdefault("v|s", TaskCell(id="v|s", vendor="v", spec_group="s",
                                  objective="o", status=CellStatus.open, impact=5))
            return grid
    orchestrator = _O()


def test_orchestrator_node_sets_grid():
    rs = ResearchState(run_id="r", original_question="q")
    out = g.node_orchestrator_plan({"research_state": rs, "brains": _B()})
    assert out["research_state"].task_grid.cells["v|s"].impact == 5


def test_grid_converged_only_when_no_open_high_impact():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["v|s"] = TaskCell(id="v|s", vendor="v", spec_group="s",
                                         objective="o", status=CellStatus.open, impact=5)
    assert convergence.grid_converged(rs) is False
    rs.task_grid.cells["v|s"].status = CellStatus.covered
    assert convergence.grid_converged(rs) is True
