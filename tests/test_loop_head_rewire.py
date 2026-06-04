from cn5_research_cos.graph import build_graph, run_loop
from cn5_research_cos.models import ResearchState


def test_orchestration_nodes_wired():
    g = build_graph()
    nodes = set(g.nodes)
    assert {"clarify", "orchestrator_plan", "plan_audit", "plan_approval"} <= nodes


def test_loop_runs_orchestrator_and_builds_grid():
    rs = ResearchState(run_id="r", original_question="q",
                       decision_criterion="c", success_form="t",
                       research_brief="b", fallback_behavior_if_human_unavailable="f")
    out = run_loop(rs, base_dir="runs", max_iterations=1, llm="mock")
    assert out.task_grid is not None
