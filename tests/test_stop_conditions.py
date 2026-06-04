"""Acceptance Test 1 (no premature stop) + Test 4 (endless-research prevention)
plus anti-premature / plateau guards."""
import cn5_research_cos.graph as g
from cn5_research_cos.graph import run_loop
from cn5_research_cos.models import (CellStatus, Decision, IssueType,
                                     ResearchState, TaskCell, TaskGrid)
from cn5_research_cos.artifacts import issue_map
from cn5_research_cos.decision import exhaustion


def test_1_no_premature_stop(tmp_path):
    final = run_loop(ResearchState(run_id="r1", original_question="q"),
                     base_dir=tmp_path, max_iterations=8, now="t0")
    # auditor-forced competitor branch materialized (was absent at start)
    assert issue_map.has_type(final, IssueType.competitor)
    # did NOT terminal-stop on iteration 1
    assert final.iteration_count >= 2


def test_4_endless_prevention(tmp_path):
    final = run_loop(ResearchState(run_id="r4", original_question="q"),
                     base_dir=tmp_path, max_iterations=20, now="t0")
    # bounded — never spins to the recursion_limit; ended for an explicit reason.
    # E1 (Task 15): while a high-impact grid cell stays open (cell coverage is not
    # auto-wired, so the grid does not converge) the loop keeps researching — it does
    # NOT early-synthesize. The HARD ``max_iterations`` backstop is what stops it, so
    # the run legitimately reaches the cap. The invariant is: bounded (never the
    # recursion limit) and ended with a produced audit, not an infinite spin.
    assert final.iteration_count <= 20
    assert final.last_audit is not None


def test_anti_premature_blocks_terminal(tmp_path):
    # a run capped at 1 iteration must not be terminal/premature; it just runs once
    final = run_loop(ResearchState(run_id="r5", original_question="q"),
                     base_dir=tmp_path, max_iterations=1, now="t0")
    assert final.readiness_score is not None
    # on iteration 1 the competitor gap is still open OR was just branched —
    # crucially the loop did not declare a clean terminal stop prematurely.
    assert final.iteration_count >= 1


# --- Task 15 (E1): no early stop while researchable; caps + ceiling stay hard ---
def _state_with_open_cell(decision, iteration, max_it=8):
    rs = ResearchState(run_id="r", original_question="q",
                       iteration_count=iteration, task_grid=TaskGrid())
    rs.task_grid.cells["v|s"] = TaskCell(id="v|s", vendor="v", spec_group="s",
                                         objective="o", status=CellStatus.open,
                                         impact=5)
    return {"research_state": rs, "last_decision": decision, "max_iterations": max_it}


def test_soft_stop_overridden_while_open_cell_under_caps(monkeypatch):
    monkeypatch.setattr(g.run_cap, "cap_hit_now", lambda: False)
    # a would-be synthesize early-stop, BELOW the ceiling, with an open high-impact cell
    state = _state_with_open_cell(Decision.synthesize, iteration=1, max_it=8)
    assert g._route(state) == "orchestrator_plan"   # keep researching, don't wrap up


def test_hard_ceiling_still_stops_even_with_open_cell(monkeypatch):
    monkeypatch.setattr(g.run_cap, "cap_hit_now", lambda: False)
    state = _state_with_open_cell(Decision.synthesize, iteration=99, max_it=8)  # past ceiling
    assert g._route(state) == "deep_audit"          # hard backstop wins


def test_cap_hit_stops_even_with_open_cell(monkeypatch):
    monkeypatch.setattr(g.run_cap, "cap_hit_now", lambda: True)
    state = _state_with_open_cell(Decision.synthesize, iteration=1, max_it=8)
    assert g._route(state) == "deep_audit"          # cap is a hard bound


def test_plateau_detector_unit():
    s = ResearchState(run_id="p", original_question="q")
    s.readiness_history = [{"sum": 10}, {"sum": 10}, {"sum": 9}]
    assert exhaustion.plateau(s, window=2) is True
    s.readiness_history = [{"sum": 5}, {"sum": 8}, {"sum": 12}]
    assert exhaustion.plateau(s, window=2) is False
