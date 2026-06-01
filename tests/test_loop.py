from cn5_research_cos.graph import run_loop
from cn5_research_cos.models import ResearchState


def test_loop_terminates(tmp_path):
    final = run_loop(ResearchState(run_id="r", original_question="q"),
                     base_dir=tmp_path, max_iterations=8, now="t0")
    assert final.readiness_score is not None and final.iteration_count >= 1
    assert (tmp_path / "r" / "state.json").exists()
    assert final.research_brief  # brief node ran
