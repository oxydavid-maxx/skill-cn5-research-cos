from typer.testing import CliRunner
from cn5_research_cos.cli import app

runner = CliRunner()


def test_init_then_show(tmp_path):
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    r1 = runner.invoke(app, ["init", "--question", "AI 能否做隔夜研究", "--run-id", "demo"], env=env)
    assert r1.exit_code == 0, r1.output
    assert (tmp_path / "demo" / "state.json").exists()
    r2 = runner.invoke(app, ["show", "demo"], env=env)
    assert r2.exit_code == 0, r2.output


def test_run_pauses_at_h6_then_resume_prints_summary_and_scores(tmp_path):
    """P3: interactive `cos run` runs the loop, prints per-iteration summaries,
    then PAUSES at the H6 final-review gate (the memo it gates is a P5 stub).
    `cos resume --choice confirm` continues from the checkpoint to the completion
    summary with readiness scores + the cost/latency/calls line."""
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    r = runner.invoke(app, ["run", "--question", "AI overnight?", "--run-id", "run1",
                            "--max-iterations", "8", "--allow-redirect"], env=env)
    assert r.exit_code == 0, r.output
    # Per-iteration Chinese summary headers printed during the loop.
    assert "Albert" in r.output
    # Paused at the H6 review gate, with a resume hint.
    assert "PAUSED" in r.output or "暫停" in r.output
    assert "cos resume" in r.output
    assert (tmp_path / "run1" / "state.json").exists()

    # Resume with confirm -> reaches the completion summary + metrics line.
    r2 = runner.invoke(app, ["resume", "run1", "--answer", "confirm"], env=env)
    assert r2.exit_code == 0, r2.output


def test_validate(tmp_path):
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    runner.invoke(app, ["init", "--question", "q", "--run-id", "v1"], env=env)
    r = runner.invoke(app, ["validate", "v1"], env=env)
    assert r.exit_code == 0, r.output
