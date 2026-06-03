"""Task 5 (P5b): red-team visibility — the live debate (incl. Albert's FULL output)
reaches stdout INCREMENTALLY through a non-tty subprocess PIPE, BEFORE process exit.

This is the MANDATORY red-team the user directed: prove that NOTHING in the
plumbing swallows the debate or holds it in a buffer until exit. We spawn the
deterministic mock-loop entrypoint (``scripts/redteam_visibility.py``) via
``subprocess.Popen(stdout=PIPE, bufsize=1)`` — a non-tty pipe — and read lines AS
THEY ARRIVE, asserting an ``[albert_audit]`` stage block + an Albert challenge line
appear BEFORE the ``[[REDTEAM-END]]`` marker (i.e. incrementally, not as one
end-of-run dump), and well before ``.wait()`` returns.

Deterministic (mock brains, no LLM/network), so it is part of the normal suite.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "redteam_visibility.py"
START = "[[REDTEAM-START]]"
END = "[[REDTEAM-END]]"


def _child_env() -> dict:
    """Child env: ensure the package is importable (src layout) WITHOUT relying on
    PYTHONUNBUFFERED — the reporter flushes explicitly, so incremental delivery must
    NOT depend on that flag (red-team form #5)."""
    env = dict(os.environ)
    src = str(REPO / "src")
    # Keep the WMI-hang sitecustomize shim on the path if the parent run used it,
    # so the child collects/imports without blocking on this Windows box. Harmless
    # elsewhere (it only patches platform.win32_ver).
    existing = env.get("PYTHONPATH", "")
    parts = [src] + ([existing] if existing else [])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env.pop("PYTHONUNBUFFERED", None)  # form #5: prove we don't depend on it
    return env


def test_albert_visible_through_subprocess_pipe():
    """Form #4: non-tty Popen with stdout=PIPE, lines read incrementally; an Albert
    challenge line is observed BEFORE the END marker and BEFORE the process exits."""
    assert SCRIPT.exists(), f"missing red-team entrypoint: {SCRIPT}"
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8", errors="replace",  # P5d: the child forces UTF-8 (guarantee #2)
        bufsize=1,                # line-buffered text pipe (non-tty)
        env=_child_env(),
        cwd=str(REPO),
    )
    saw_start = False
    saw_albert_header = False
    saw_albert_challenge = False
    saw_end = False
    albert_before_end = False
    albert_while_running = False
    lines: list[str] = []
    try:
        # Read AS THEY ARRIVE. The proof of INCREMENTAL (non-buffered) delivery is
        # twofold: (a) an Albert challenge line is read BEFORE the END marker line,
        # and (b) the child process is STILL RUNNING (proc.poll() is None) at the
        # moment that Albert line is read — if stdout were held in a buffer until
        # exit, nothing would be readable until the process had already terminated.
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            lines.append(line)
            if START in line:
                saw_start = True
            if "[albert_audit]" in line:
                saw_albert_header = True
            # A challenge body line from render_albert looks like "  [C-1] (open, ...".
            if saw_albert_header and line.lstrip().startswith("[C-") and "(" in line:
                if not saw_albert_challenge and proc.poll() is None:
                    albert_while_running = True
                saw_albert_challenge = True
            if END in line:
                saw_end = True
            if saw_albert_challenge and not saw_end:
                albert_before_end = True
            if saw_end:
                break
    finally:
        # Drain + reap so we never leak the child.
        try:
            proc.stdout.close()
        except Exception:
            pass
        proc.wait(timeout=60)

    out = "\n".join(lines)
    assert saw_start, f"never saw START marker; got:\n{out}"
    assert saw_albert_header, f"never saw [albert_audit] block; got:\n{out}"
    assert saw_albert_challenge, f"never saw an Albert challenge line; got:\n{out}"
    assert albert_before_end, (
        "Albert challenge did NOT arrive before the END marker — output was not "
        f"incremental (buffered until exit). got:\n{out}"
    )
    assert albert_while_running, (
        "Albert challenge line was only readable AFTER the child had exited — "
        f"output was buffered until process exit, not streamed live. got:\n{out}"
    )
    # A verdict line proves Albert's FULL block (not just a header) was streamed.
    assert "verdict:" in out, f"no Albert verdict line in stream; got:\n{out}"


def test_redteam_script_exit_code_zero():
    """The harness itself runs clean (exit 0) — a colleague can rely on it."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",  # P5d: the child forces UTF-8 (guarantee #2)
        env=_child_env(), cwd=str(REPO), timeout=120,
    )
    assert proc.returncode == 0, proc.stdout
    assert START in proc.stdout and END in proc.stdout
    assert "[albert_audit]" in proc.stdout
