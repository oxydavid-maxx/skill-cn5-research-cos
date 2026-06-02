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


def test_run_prints_summary_and_scores(tmp_path):
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    r = runner.invoke(app, ["run", "--question", "AI overnight?", "--run-id", "run1",
                            "--max-iterations", "8"], env=env)
    assert r.exit_code == 0, r.output
    # Chinese iteration summary headers + readiness scores present
    assert "Albert" in r.output
    assert "readiness" in r.output.lower() or "就緒" in r.output or "分數" in r.output
    # P2 acceleration: a cost/latency/calls summary line is always printed
    assert "cost=$" in r.output and "latency=" in r.output and "calls=" in r.output
    assert (tmp_path / "run1" / "state.json").exists()


def test_validate(tmp_path):
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    runner.invoke(app, ["init", "--question", "q", "--run-id", "v1"], env=env)
    r = runner.invoke(app, ["validate", "v1"], env=env)
    assert r.exit_code == 0, r.output
