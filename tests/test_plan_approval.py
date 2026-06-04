import cn5_research_cos.graph as g
from cn5_research_cos.models import ResearchState, TaskGrid, TaskCell, CellStatus

def _grid(*ids):
    grid = TaskGrid()
    for i in ids:
        grid.cells[i] = TaskCell(id=i, vendor=i, spec_group="s", objective="o", status=CellStatus.open)
    return grid

def test_h7_prompts_on_first_cycle(monkeypatch):
    hit = {}
    monkeypatch.setattr(g, "interrupt", lambda p: hit.setdefault("p", p) or {"approve": True})
    rs = ResearchState(run_id="r", original_question="q", task_grid=_grid("a"))
    g.node_plan_approval({"research_state": rs, "mode": "interactive"})
    assert "p" in hit

def test_h7_skips_on_small_rerank(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(g, "interrupt", lambda p: calls.__setitem__("n", calls["n"] + 1) or {"approve": True})
    rs = ResearchState(run_id="r", original_question="q", task_grid=_grid("a"))
    st = {"research_state": rs, "mode": "interactive"}
    g.node_plan_approval(st)
    g.node_plan_approval(st)
    assert calls["n"] == 1

def test_h7_reprompts_on_major_redecomposition(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(g, "interrupt", lambda p: calls.__setitem__("n", calls["n"] + 1) or {"approve": True})
    rs = ResearchState(run_id="r", original_question="q", task_grid=_grid("a"))
    st = {"research_state": rs, "mode": "interactive"}
    g.node_plan_approval(st)
    rs.task_grid = _grid("a", "b", "c", "d")
    g.node_plan_approval(st)
    assert calls["n"] == 2
