from cn5_research_cos.brains import build_brains
from cn5_research_cos.models import ResearchState, TaskGrid, CellStatus, AlbertChallenge, ChallengeStatus


def test_orchestrator_seeds_grid_from_brief():
    brains = build_brains("mock")
    rs = ResearchState(run_id="r", original_question="switch PK",
                       success_form="vendor x spec_group table")
    grid = brains.orchestrator.plan(rs)
    assert isinstance(grid, TaskGrid) and grid.cells


def test_orchestrator_adds_cells_for_uncovered_gaps():
    brains = build_brains("mock")
    rs = ResearchState(run_id="r", original_question="q")
    rs.task_grid = TaskGrid(axes=["vendor", "spec_group"])
    rs.albert_challenge_map["c1"] = AlbertChallenge(
        id="c1", challenge="NXP TSN gate-list depth unknown",
        status=ChallengeStatus.open, issue_id=None)
    grid = brains.orchestrator.plan(rs)
    assert any(c.status == CellStatus.open for c in grid.cells.values())
