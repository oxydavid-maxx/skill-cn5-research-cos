"""CLI session-state persistence test for the SOT clarify flow (deterministic).

Uses CN5_COS_CLARIFY_STEP=scripted to inject a deterministic scripted StepFn so
the clarify CLI can be driven without an LLM and the turn-based session state
(dialogue + checkpoint) persists across separate CLI invocations.
"""
from __future__ import annotations

import os

from typer.testing import CliRunner

from cn5_research_cos.cli import app
from cn5_research_cos.sot.brief import load_latest, BriefStatus

runner = CliRunner()


def _env(tmp_path):
    return {
        **os.environ,
        "CN5_COS_BASE_DIR": str(tmp_path),
        "CN5_COS_CLARIFY_STEP": "scripted",  # inject deterministic step
    }


def test_clarify_turn_based_persists_and_converges(tmp_path, monkeypatch):
    env = _env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    rid = "run-cli"
    # turn 1: seed with topic -> scripted 1/4 -> questions, not converged
    r1 = runner.invoke(app, ["clarify", "--question", "underspecified topic",
                             "--run-id", rid])
    assert r1.exit_code == 0, r1.output
    assert "未收斂" in r1.output or "question" in r1.output.lower() or "問題" in r1.output

    # turn 2: answer -> scripted 3/4 -> still not converged
    r2 = runner.invoke(app, ["clarify", "--answer", "answer 1", "--run-id", rid])
    assert r2.exit_code == 0, r2.output

    # turn 3: answer -> scripted 4/4 -> CONVERGED -> brief.v1 written
    r3 = runner.invoke(app, ["clarify", "--answer", "answer 2", "--run-id", rid])
    assert r3.exit_code == 0, r3.output
    assert "收斂" in r3.output or "converged" in r3.output.lower()

    b = load_latest(rid, base_dir=str(tmp_path))
    assert b.version == 1
    assert b.objective  # populated by the scripted compile


def test_brief_command_shows_latest(tmp_path, monkeypatch):
    env = _env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    rid = "run-brief"
    runner.invoke(app, ["clarify", "--question", "t", "--run-id", rid])
    runner.invoke(app, ["clarify", "--answer", "a1", "--run-id", rid])
    runner.invoke(app, ["clarify", "--answer", "a2", "--run-id", rid])

    r = runner.invoke(app, ["brief", rid])
    assert r.exit_code == 0, r.output
    assert "SOT Brief" in r.output


def test_brief_missing_run_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("CN5_COS_BASE_DIR", str(tmp_path))
    r = runner.invoke(app, ["brief", "nope"])
    assert r.exit_code != 0


def test_revise_brief_bumps_version_and_supersedes(tmp_path, monkeypatch):
    env = _env(tmp_path)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    rid = "run-rev"
    runner.invoke(app, ["clarify", "--question", "t", "--run-id", rid])
    runner.invoke(app, ["clarify", "--answer", "a1", "--run-id", rid])
    runner.invoke(app, ["clarify", "--answer", "a2", "--run-id", rid])

    r = runner.invoke(app, ["revise-brief", rid, "--field", "deliverable",
                            "--value", "一頁式 memo"])
    assert r.exit_code == 0, r.output

    v2 = load_latest(rid, base_dir=str(tmp_path))
    assert v2.version == 2
    assert v2.deliverable == "一頁式 memo"
    # prior version superseded
    from cn5_research_cos.sot.brief import load_version
    assert load_version(rid, 1, base_dir=str(tmp_path)).status == BriefStatus.superseded
