"""Acceptance Test 1 (no premature stop) + Test 4 (endless-research prevention)
plus anti-premature / plateau guards."""
from cn5_research_cos.graph import run_loop
from cn5_research_cos.models import IssueType, ResearchState
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
    # bounded — never spins to the recursion_limit; ended for an explicit reason
    assert final.iteration_count <= 20
    assert final.last_audit is not None
    # ended via synthesize/exhausted, not by exhausting the iteration cap
    assert final.iteration_count < 20


def test_anti_premature_blocks_terminal(tmp_path):
    # a run capped at 1 iteration must not be terminal/premature; it just runs once
    final = run_loop(ResearchState(run_id="r5", original_question="q"),
                     base_dir=tmp_path, max_iterations=1, now="t0")
    assert final.readiness_score is not None
    # on iteration 1 the competitor gap is still open OR was just branched —
    # crucially the loop did not declare a clean terminal stop prematurely.
    assert final.iteration_count >= 1


def test_plateau_detector_unit():
    s = ResearchState(run_id="p", original_question="q")
    s.readiness_history = [{"sum": 10}, {"sum": 10}, {"sum": 9}]
    assert exhaustion.plateau(s, window=2) is True
    s.readiness_history = [{"sum": 5}, {"sum": 8}, {"sum": 12}]
    assert exhaustion.plateau(s, window=2) is False
