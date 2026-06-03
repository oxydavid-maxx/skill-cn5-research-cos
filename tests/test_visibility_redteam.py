"""Task 5 (P5d): the HONEST red-team — durable debate.md ALWAYS / refuse-if-hidden
/ no-overclaim grep / honesty ledger.

The honest model (spec 2026-06-03) has THREE guarantees and NO "100%/invincible"
overclaim:
  1. durable runs/<id>/debate.md (fail-closed) — survives EVERY redirect/pipe/
     background/no-tty case (this test proves it under each form);
  2. best-effort live (flushed UTF-8) — covered by tests/test_reporter_live.py;
  3. detect-and-refuse — a non-tty run without --allow-redirect exits 2 (proved
     here), and the escape works (proved here).
This test REPORTS what is and is NOT defended (the ledger) and structurally
forbids overclaim language. Breaking honestly is the correct result; lying is not.

Deterministic: a mock-loop subprocess (mock brains, no LLM/network) writes the
durable file; we assert the FILE (not the screen) in every adversarial form.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "redteam_visibility.py"


def _child_env() -> dict:
    env = dict(os.environ)
    src = str(REPO / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([src] + ([existing] if existing else []))
    env.pop("PYTHONUNBUFFERED", None)
    # Critically: do NOT leak an --allow-redirect escape from the parent env, so the
    # refuse test below sees a genuinely hidden (non-tty, no-escape) child.
    env.pop("CN5_COS_ALLOW_REDIRECT", None)
    return env


def _assert_debate_complete(run_dir: Path, form: str) -> None:
    """The durable debate.md exists and contains a FULL Albert block (challenge +
    verdict) — the one real 100%, asserted on the FILE, not the screen."""
    debate = run_dir / "debate.md"
    assert debate.exists(), f"[{form}] no durable debate.md at {debate}"
    md = debate.read_text(encoding="utf-8")
    assert "[albert_audit]" in md, f"[{form}] no albert_audit block in debate.md:\n{md[:500]}"
    assert "verdict:" in md, f"[{form}] no Albert verdict line in debate.md (block truncated?)"
    assert "[C-" in md, f"[{form}] no Albert challenge line in debate.md"


# --------------------------------------------------------------------------- #
# Guarantee #1: durable debate.md is COMPLETE under EVERY adversarial form.
# Each form runs the SAME child (--run-dir <tmp> --allow-redirect so the loop runs)
# but hides/redirects the *screen* differently; the file must be complete anyway.
# --------------------------------------------------------------------------- #
def test_durable_under_stdout_to_file(tmp_path):
    """`> file`: stdout fully redirected to a file; debate.md still complete."""
    run_dir = tmp_path / "r"
    outfile = tmp_path / "out.txt"
    with open(outfile, "wb") as fh:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--allow-redirect"],
            stdout=fh, stderr=fh, env=_child_env(), cwd=str(REPO), timeout=120,
        )
    assert proc.returncode == 0
    _assert_debate_complete(run_dir, "> file")


def test_durable_under_pipe_to_cat(tmp_path):
    """`| cat`-equivalent: stdout piped to another process; debate.md still complete."""
    run_dir = tmp_path / "r"
    producer = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--allow-redirect"],
        stdout=subprocess.PIPE, env=_child_env(), cwd=str(REPO),
    )
    # a trivial `cat` consumer: read everything (drains the pipe so producer finishes)
    consumer = subprocess.run(
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
        stdin=producer.stdout, timeout=120,
    )
    producer.stdout.close()
    producer.wait(timeout=120)
    assert producer.returncode == 0
    assert consumer.returncode == 0
    _assert_debate_complete(run_dir, "| cat")


def test_durable_under_2to1_merge(tmp_path):
    """`2>&1` into a file: stderr merged into stdout into a file; debate.md complete."""
    run_dir = tmp_path / "r"
    outfile = tmp_path / "merged.txt"
    with open(outfile, "wb") as fh:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--allow-redirect"],
            stdout=fh, stderr=subprocess.STDOUT, env=_child_env(), cwd=str(REPO), timeout=120,
        )
    assert proc.returncode == 0
    _assert_debate_complete(run_dir, "2>&1")


def test_durable_under_stdout_devnull(tmp_path):
    """`> NUL`/`/dev/null`: stdout fully discarded; debate.md still complete (the
    file does not depend on a screen)."""
    run_dir = tmp_path / "r"
    with open(os.devnull, "wb") as devnull:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--allow-redirect"],
            stdout=devnull, stderr=devnull, env=_child_env(), cwd=str(REPO), timeout=120,
        )
    assert proc.returncode == 0
    _assert_debate_complete(run_dir, "> devnull")


def test_durable_under_background_pipes(tmp_path):
    """Background `&`-equivalent: detached non-tty pipes, parent does other work,
    then reaps; debate.md complete on disk."""
    run_dir = tmp_path / "r"
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--allow-redirect"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_child_env(), cwd=str(REPO),
    )
    # parent does NOT read the pipes immediately (background-ish); just reap at end.
    out, err = proc.communicate(timeout=120)  # drains + waits
    assert proc.returncode == 0, (out, err)
    _assert_debate_complete(run_dir, "background")


def test_durable_under_nontty_pipe(tmp_path):
    """Plain non-tty subprocess with both stdin/out/err = pipes; debate.md complete."""
    run_dir = tmp_path / "r"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--allow-redirect"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_child_env(), cwd=str(REPO), timeout=120,
    )
    assert proc.returncode == 0
    _assert_debate_complete(run_dir, "non-tty pipe")


# --------------------------------------------------------------------------- #
# Guarantee #3: detect-and-refuse — a hidden (non-tty) run without --allow-redirect
# EXITS 2 with guidance; WITH the escape (flag or env) it runs + the file is complete.
# --------------------------------------------------------------------------- #
def test_refuse_when_hidden_without_escape(tmp_path):
    """Non-tty pipes, NO --allow-redirect, NO env escape → exit 2 + guidance, and
    the loop did NOT run (no debate.md)."""
    run_dir = tmp_path / "r"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir)],  # no --allow-redirect
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        env=_child_env(), cwd=str(REPO), timeout=120,
    )
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "--allow-redirect" in combined
    assert "終端機" in combined
    assert not (run_dir / "debate.md").exists()


def test_escape_with_flag_runs_and_file_complete(tmp_path):
    """The --allow-redirect flag escapes the guard → loop runs, debate.md complete."""
    run_dir = tmp_path / "r"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir), "--allow-redirect"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_child_env(), cwd=str(REPO), timeout=120,
    )
    assert proc.returncode == 0
    _assert_debate_complete(run_dir, "escape flag")


def test_escape_with_env_runs_and_file_complete(tmp_path):
    """CN5_COS_ALLOW_REDIRECT=1 escapes the guard → loop runs, debate.md complete."""
    run_dir = tmp_path / "r"
    env = _child_env()
    env["CN5_COS_ALLOW_REDIRECT"] = "1"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--run-dir", str(run_dir)],  # no flag; env escapes
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, cwd=str(REPO), timeout=120,
    )
    assert proc.returncode == 0
    _assert_debate_complete(run_dir, "escape env")


# --------------------------------------------------------------------------- #
# Honesty ledger: the script prints DEFENDED vs NOT-DEFENDED.
# --------------------------------------------------------------------------- #
def test_honesty_ledger_prints_defended_and_not_defended():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--ledger"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        env=_child_env(), cwd=str(REPO), timeout=60,
    )
    assert proc.returncode == 0
    out = proc.stdout
    assert "[DEFENDED]" in out
    assert "[NOT-DEFENDED]" in out
    # The three things we do NOT defend must be named honestly.
    assert "headless" in out
    assert "pty" in out
    assert "--allow-redirect" in out


# --------------------------------------------------------------------------- #
# No-overclaim structural grep: no visibility-claim source/doc/test uses
# "100% / invincible / nothing can block / un-blockable / 完全避免...擋" EXCEPT
# where the mention NEGATES the overclaim (e.g. "we do NOT claim 100%").
# --------------------------------------------------------------------------- #
_OVERCLAIM_TERMS = [
    "invincible",
    "nothing can block",
    "un-blockable",
    "unblockable",
    "un-suppressable",
    "unsuppressable",
]
# Lines that NEGATE an overclaim (or use the ONE honest exception — the durable
# file being "the only real 100%") are allowed: they ARE the honest framing. A line
# is treated as honest if it contains one of these markers.
_NEGATION_MARKERS = [
    # explicit negations / refutations of the overclaim
    "do NOT claim", "do not claim", "no overclaim", "no 100%", 'no "100%',
    'not "100%', "not 100%", "NEGATE", "negate", "不宣稱", "不主張",
    "stated honestly", "we do NOT", "we will NOT", "will NOT use", "並不保證",
    "不保證", "supersedes", "refuted", "peer review", "replace any",
    "no 100%/invincible", "invincible\" claim", "invincible claim",
    # the DEFENDED/NOT-DEFENDED ledger lines are honest by construction
    "defended", "not-defended",
    # the ONE honest exception: the durable FILE is the only real 100% (a guarantee
    # about content-on-disk, not about pixels on a screen). Spec sanctions this.
    "real 100%", "the 100%)", "(the 100%", "only real",
]

# The red-team test file itself necessarily contains the banned terms (as the
# denylist data + the assertion message), so it is excluded from its own scan.
_EXCLUDE_NAMES = {"test_visibility_redteam.py"}


def _scan_files():
    targets = []
    targets += list((REPO / "src").rglob("*.py"))
    targets += list((REPO / "docs" / "spec").glob("2026-06-03-phase5*"))
    targets += list((REPO / "tests").glob("test_*visib*.py"))
    targets += list((REPO / "tests").glob("test_*redteam*.py"))
    targets += list((REPO / "scripts").glob("*.py"))
    readme = REPO / "README.md"
    if readme.exists():
        targets.append(readme)
    return [p for p in targets if p.name not in _EXCLUDE_NAMES]


def _line_is_negation(line: str) -> bool:
    low = line.lower()
    return any(m.lower() in low for m in _NEGATION_MARKERS)


def test_no_overclaim_language_in_visibility_sources():
    """Structural enforcement of the honest model: a visibility-claim file must NOT
    assert "100%/invincible/nothing-can-block/un-blockable/完全避免...擋" UNLESS the
    line negates the overclaim (the honest-limits framing). This is the gate the
    spec demands — wording is enforced by a test, not just prose."""
    offenders: list[str] = []
    for path in _scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _line_is_negation(line):
                continue
            low = line.lower()
            for term in _OVERCLAIM_TERMS:
                if term in low:
                    offenders.append(f"{path}:{i}: {line.strip()}")
            # "100%" only counts as overclaim in a visibility-claim context: a bare
            # token near 'visib'/'screen'/'debate'/'block'/'pixel' that isn't negated.
            if "100%" in line:
                ctx = low
                if any(k in ctx for k in ("visib", "screen", "debate", "block",
                                          "pixel", "terminal", "畫面", "辯論")):
                    offenders.append(f"{path}:{i}: {line.strip()}")
            # the specific banned CJK overclaim phrasing
            if "完全避免" in line and "擋" in line:
                offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, (
        "overclaim language found in visibility-claim files (use the three honest "
        "guarantees instead, or NEGATE the overclaim explicitly):\n" + "\n".join(offenders)
    )
