import pytest
from cn5_research_cos.store import new_run, save_snapshot, load_snapshot
from cn5_research_cos.graph import compile_with_checkpoint
from cn5_research_cos.models import ResearchState


def test_round_trip(tmp_path):
    s = new_run("q", run_id="r1", now="2026-06-01T00:00:00"); s.iteration_count = 2
    save_snapshot(s, base_dir=tmp_path)
    assert load_snapshot("r1", base_dir=tmp_path) == s


def test_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshot("nope", base_dir=tmp_path)


def test_langgraph_resume_continues_not_restarts(tmp_path):
    """LangGraph SqliteSaver: re-invoking with None replays from the checkpoint
    (continues) rather than restarting the loop from iteration 0."""
    run_dir = tmp_path / "rg"
    app, saver, conn = compile_with_checkpoint(run_dir)
    try:
        cfg = {"configurable": {"thread_id": "rg"}, "recursion_limit": 100}
        init = {
            "research_state": ResearchState(run_id="rg", original_question="q"),
            "base_dir": str(tmp_path), "now": "t0", "max_iterations": 6,
            "assume_brief": True,  # P8: this test exercises resume, not the H0 clarify gate
        }
        out1 = app.invoke(init, config=cfg)
        first_iter = out1["research_state"].iteration_count
        assert first_iter >= 1

        # checkpoint must hold the same progress
        snap = app.get_state(cfg)
        assert snap.values["research_state"].iteration_count == first_iter

        # resume with None — must NOT restart from 0
        out2 = app.invoke(None, config=cfg)
        assert out2["research_state"].iteration_count == first_iter
        assert out2["research_state"].iteration_count != 0
    finally:
        conn.close()
