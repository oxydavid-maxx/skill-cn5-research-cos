import cn5_research_cos.graph as g
from cn5_research_cos.decision import audit_tier
from cn5_research_cos.models import ResearchState, TaskGrid, TaskCell, CellStatus


def test_plan_stage_is_flash():
    rs = ResearchState(run_id="r", original_question="q")
    assert audit_tier.audit_tier_for("plan", rs) == "flash"


def test_plan_audit_skips_when_grid_unchanged():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["v|s"] = TaskCell(id="v|s", vendor="v", spec_group="s",
                                         objective="o", status=CellStatus.open)
    calls = {"n": 0}

    class _B:
        class _A:
            def audit(self, s): calls["n"] += 1; return None
        auditor = _A()
    st = {"research_state": rs, "brains": _B()}
    g.node_plan_audit(st); g.node_plan_audit(st)
    assert calls["n"] == 1
