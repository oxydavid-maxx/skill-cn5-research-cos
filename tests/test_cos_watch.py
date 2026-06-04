"""Task 4 (P5d): `cos watch <run_id>` tails runs/<run_id>/debate.md, and the
run/run-auto StageReporter is constructed with run_dir so the debate persists.

`cos watch` lets a colleague follow the war-room debate with ONE command and no
knowledge of tail/paths. Deterministic (file I/O + CliRunner, no LLM).
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cn5_research_cos.cli import app

runner = CliRunner()


def test_watch_prints_existing_debate(tmp_path):
    """`cos watch <id>` prints the existing debate.md content (--no-follow so it
    returns immediately for the test)."""
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    run_dir = tmp_path / "runw"
    run_dir.mkdir(parents=True)
    (run_dir / "debate.md").write_text(
        "=== [albert_audit] ===\n[C-1] (open) the moat is unproven\n\n",
        encoding="utf-8",
    )
    r = runner.invoke(app, ["watch", "runw", "--no-follow"], env=env)
    assert r.exit_code == 0, r.output
    assert "[C-1] (open) the moat is unproven" in r.output


def test_watch_missing_run_errors(tmp_path):
    """A missing run / debate.md → a clear non-zero exit, not a crash."""
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    r = runner.invoke(app, ["watch", "nope", "--no-follow"], env=env)
    assert r.exit_code != 0


def test_run_auto_persists_debate_md(tmp_path):
    """run-auto wires run_dir into the StageReporter → runs/<id>/debate.md exists
    and contains an Albert block after the loop (the durable guarantee end-to-end)."""
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    r = runner.invoke(app, ["run-auto", "--question", "AI overnight?",
                            "--run-id", "rapersist", "--max-iterations", "6",
                            "--allow-redirect",
                            "--assume-brief"], env=env)  # P8: tests debate persistence, not the H0 clarify gate
    assert r.exit_code == 0, r.output
    debate = tmp_path / "rapersist" / "debate.md"
    assert debate.exists(), r.output
    md = debate.read_text(encoding="utf-8")
    assert "[albert_audit]" in md
    # an Albert challenge / verdict line proves the FULL block persisted
    assert "verdict:" in md


def test_run_interactive_persists_debate_md(tmp_path):
    """`cos run` (interactive) also wires run_dir → debate.md exists with an
    Albert block."""
    env = {"CN5_COS_BASE_DIR": str(tmp_path)}
    r = runner.invoke(app, ["run", "--question", "AI overnight?", "--run-id",
                            "runpersist", "--max-iterations", "6",
                            "--allow-redirect",
                            "--assume-brief"], env=env)  # P8: tests debate persistence, not the H0 clarify gate
    assert r.exit_code == 0, r.output
    debate = tmp_path / "runpersist" / "debate.md"
    assert debate.exists(), r.output
    assert "[albert_audit]" in debate.read_text(encoding="utf-8")
