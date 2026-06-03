"""Task 1 (P5d): the durable ``runs/<id>/debate.md`` sink — the only real 100%.

The honest visibility model (spec 2026-06-03) makes the durable file the single
un-breakable guarantee: every per-stage debate block (incl. Albert's full output)
is appended to ``<run_dir>/debate.md``, flushed per block, and the write is
FAIL-CLOSED — an unwritable sink raises ``VisibilityContractError`` rather than
silently dropping the auditable record. This survives EVERY redirect / pipe /
background / no-tty / pty / harness case because it does not depend on a screen.

Mirrors ``skill-cn5-i-am-albert/albert/deliberation.py`` (durable
``deliberation.md`` + fail-closed append). Deterministic (file I/O only, no LLM).
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cn5_research_cos.observability.reporter import StageReporter
from cn5_research_cos.observability.errors import VisibilityContractError

REPO = Path(__file__).resolve().parents[1]


def test_blocks_persisted_to_debate_md(tmp_path):
    """Every stage() block lands in <run_dir>/debate.md (utf-8, content present)."""
    r = StageReporter(run_dir=tmp_path, stream=io.StringIO())
    r.stage("albert_audit", "C-1 the moat is unproven")
    r.stage("decision", "next: research")
    md = (tmp_path / "debate.md").read_text(encoding="utf-8")
    assert "C-1 the moat is unproven" in md
    assert "albert_audit" in md
    assert "decision" in md
    assert "next: research" in md


def test_debate_md_flushed_per_block(tmp_path):
    """The file holds the first block BEFORE the second is written (per-block flush,
    not a single end-of-run dump)."""
    r = StageReporter(run_dir=tmp_path, stream=io.StringIO())
    r.stage("scope", "objective X")
    mid = (tmp_path / "debate.md").read_text(encoding="utf-8")
    assert "objective X" in mid  # already on disk before stage 2
    r.stage("decision", "next: Y")
    end = (tmp_path / "debate.md").read_text(encoding="utf-8")
    assert "objective X" in end and "next: Y" in end


def test_debate_md_preserves_cjk(tmp_path):
    """CJK round-trips through the durable sink with no mojibake."""
    r = StageReporter(run_dir=tmp_path, stream=io.StringIO())
    r.stage("albert_audit", "拷問：這個護城河有被驗證嗎？")
    md = (tmp_path / "debate.md").read_text(encoding="utf-8")
    assert "拷問：這個護城河有被驗證嗎？" in md


def test_fail_closed_on_unwritable(tmp_path):
    """A write to an unwritable sink raises VisibilityContractError (fail-CLOSED):
    for an audit-driven cockpit, no auditable record ⇒ do not proceed silently."""
    # run_dir points at a path whose parent is a *file*, so mkdir/open must fail.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")
    run_dir = blocker / "child"  # parent is a file → cannot create/append
    with pytest.raises(VisibilityContractError):
        r = StageReporter(run_dir=run_dir, stream=io.StringIO())
        r.stage("albert_audit", "should fail closed")


def test_back_compat_no_run_dir_no_file(tmp_path):
    """run_dir is optional (back-compat): with no run_dir, no durable sink is written
    and the stream sink still works exactly as before P5d."""
    buf = io.StringIO()
    r = StageReporter(stream=buf)  # no run_dir
    r.stage("scope", "objective X")
    assert "objective X" in buf.getvalue()
    assert not (tmp_path / "debate.md").exists()


# ----- the headline guarantee: durable under stdout=devnull (no screen) ----- #
_DRIVER = (
    "import io,sys;"
    "from cn5_research_cos.observability.reporter import StageReporter;"
    "r=StageReporter(run_dir=sys.argv[1], stream=io.StringIO());"
    "r.stage('albert_audit','[C-1] (open) durable-under-devnull');"
    "r.stage('decision','next: stop')"
)


def _child_env() -> dict:
    env = dict(os.environ)
    src = str(REPO / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([src] + ([existing] if existing else []))
    return env


def test_debate_md_complete_under_stdout_devnull(tmp_path):
    """Spawn a child whose stdout is fully discarded (DEVNULL): the durable
    debate.md is STILL complete — the file does not depend on a screen existing."""
    run_dir = tmp_path / "run-x"
    with open(os.devnull, "wb") as devnull:
        proc = subprocess.run(
            [sys.executable, "-c", _DRIVER, str(run_dir)],
            stdout=devnull, stderr=devnull,
            env=_child_env(), cwd=str(REPO), timeout=60,
        )
    assert proc.returncode == 0
    md = (run_dir / "debate.md").read_text(encoding="utf-8")
    assert "[C-1] (open) durable-under-devnull" in md
    assert "next: stop" in md
