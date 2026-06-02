"""CLI tests for P3 HITL commands: run (interactive pause), resume, steer, run-auto."""
from typer.testing import CliRunner

from cn5_research_cos.cli import app
from cn5_research_cos.store import load_snapshot, save_snapshot
from cn5_research_cos.models import IssueStatus, IssueType, ResearchState
from cn5_research_cos.artifacts import issue_map

runner = CliRunner()


def _seed_pull_state(base_dir, rid="cliplull"):
    """Persist a run whose state will route to a human_pull gate on cos run."""
    rs = ResearchState(run_id=rid, original_question="AI 隔夜研究?", mode="interactive")
    issue_map.add(rs, title="intent", description="d", issue_type=IssueType.intent,
                  status=IssueStatus.open, now="t", impact=5)
    rs.steering_events.append({
        "kind": "request_pull", "context": "方向不明", "why": "高影響互斥",
        "options": ["A: ROI 先", "B: 競品先", "C: 並行"], "ai_recommendation": "A",
        "default_if_no_response": "A", "consumed": False,
    })
    save_snapshot(rs, base_dir=base_dir)
    return rid


def test_run_auto_reaches_stop(tmp_path):
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    r = runner.invoke(app, ["run-auto", "--question", "AI overnight?",
                            "--run-id", "ra1", "--max-iterations", "8"], env=env)
    assert r.exit_code == 0, r.output
    assert "停止原因" in r.output or "stop" in r.output.lower()
    assert (tmp_path / "ra1" / "state.json").exists()


def test_steer_appends_event(tmp_path):
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    runner.invoke(app, ["init", "--question", "q", "--run-id", "st1"], env=env)
    r = runner.invoke(app, ["steer", "st1", "改成優先研究競品"], env=env)
    assert r.exit_code == 0, r.output
    state = load_snapshot("st1", base_dir=tmp_path)
    steers = [e for e in state.steering_events if e.get("kind") == "steer"]
    assert steers and steers[-1]["text"] == "改成優先研究競品"


def test_run_interactive_pauses_at_gate_and_resume_continues(tmp_path):
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    rid = _seed_pull_state(tmp_path, "cliint")
    # cos run resumes the seeded run (state.json), runs until the pull gate pauses.
    r = runner.invoke(app, ["run", "--run-id", rid, "--resume-state",
                            "--max-iterations", "6"], env=env)
    assert r.exit_code == 0, r.output
    assert "PAUSED" in r.output or "暫停" in r.output
    assert "cos resume" in r.output  # tells the human how to resume
    # The ask payload is shown.
    assert "ROI 先" in r.output

    # cos resume continues from the checkpoint with the human's choice.
    r2 = runner.invoke(app, ["resume", rid, "--choice", "B"], env=env)
    assert r2.exit_code == 0, r2.output
    state = load_snapshot(rid, base_dir=tmp_path)
    answers = [e for e in state.steering_events if e.get("kind") == "pull_answer"]
    assert answers and answers[-1]["choice"] == "B"
