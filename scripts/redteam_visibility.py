"""Red-team visibility harness (P5b Task 5) — prove the live adversarial debate
(per-stage block incl. Albert's FULL output) reaches stdout, FLUSHED and
INCREMENTAL, under EVERY invocation form a colleague might use.

WHY: the hard user directive (2026-06-03) is that a colleague running ``cos run``
MUST be able to WATCH the debate live on screen, and NOTHING in the plumbing
(tee / cat / pipe / redirect / background / a non-tty subprocess PIPE) may swallow
it or hold it in a buffer until the process exits. This script is a tiny,
DETERMINISTIC mock-loop entrypoint (mock brains — no LLM, no network) so the
red-team can exercise that guarantee cheaply and repeatably, both from the
automated test (``tests/test_redteam_visibility.py``) and by hand.

WHAT IT DOES: runs the real convergence loop (``run_loop``) with mock brains and a
``StageReporter(sys.stdout)`` threaded in, so every stage — including the
``albert_audit`` block with each challenge's text/why/status/verdict/both risks —
is written to stdout and flushed PER STAGE. It prints a ``[[REDTEAM-START]]``
marker before the loop and a ``[[REDTEAM-END]]`` marker after, so a reader can
prove an Albert line arrived BEFORE the end marker (i.e. incrementally, not as a
single end-of-run dump).

----------------------------------------------------------------------------
THE 6 MANUAL INVOCATION FORMS (run each; you should SEE the Albert block in all):

  1. Direct TTY (you watch it live in your terminal):
        py -3 scripts/redteam_visibility.py

  2. Piped through `cat` (`| cat` strips the tty; output must still appear):
        py -3 scripts/redteam_visibility.py | cat
     (Windows PowerShell equivalent: `py -3 scripts/redteam_visibility.py | Out-Host`)

  3. Redirected to a file, then inspected (`> file`):
        py -3 scripts/redteam_visibility.py > out.txt ; type out.txt   (Windows)
        py -3 scripts/redteam_visibility.py > out.txt && cat out.txt    (POSIX)

  4. Non-tty subprocess with stdout=PIPE, read incrementally (what the automated
     red-team test does):
        py -3 -c "import subprocess,sys; p=subprocess.Popen([sys.executable,'scripts/redteam_visibility.py'],stdout=subprocess.PIPE,text=True,bufsize=1); [print(l,end='') for l in p.stdout]; p.wait()"

  5. PYTHONUNBUFFERED unset (prove visibility does NOT depend on the env flag —
     the reporter flushes explicitly, so output is incremental even without it):
        set PYTHONUNBUFFERED=         &  py -3 scripts/redteam_visibility.py   (Windows)
        unset PYTHONUNBUFFERED ; py -3 scripts/redteam_visibility.py            (POSIX)

  6. Background run, output captured to a file you tail (no attached terminal):
        Start-Process py -ArgumentList '-3','scripts/redteam_visibility.py' -RedirectStandardOutput bg.txt -NoNewWindow ; Get-Content bg.txt -Wait   (Windows PowerShell)
        py -3 scripts/redteam_visibility.py > bg.txt 2>&1 &  ; tail -f bg.txt    (POSIX)
----------------------------------------------------------------------------
"""
from __future__ import annotations

import argparse
import sys

START_MARKER = "[[REDTEAM-START]]"
END_MARKER = "[[REDTEAM-END]]"

# The HONEST ledger (spec 2026-06-03): name exactly what the visibility model
# defends and — just as loudly — what it does NOT. No "100%/invincible" claims.
DEFENDED = [
    "durable debate.md survives redirect/pipe/background/no-tty/pty/harness "
    "(it is on disk; it does not depend on a screen)",
    "accidental hide is refused (non-tty stdout AND stderr → exit 2 with guidance)",
    "real foreground terminal sees the debate live on flushed UTF-8 stderr/stdout",
]
NOT_DEFENDED = [
    "no screen exists (headless CI/cron/service) — nobody can paint pixels on a "
    "non-existent screen; we do NOT claim to",
    "a hostile pty wrapper (script/winpty/tmux) that owns the terminal — it elected "
    "to own the channel",
    "a user who CHOSE --allow-redirect / CN5_COS_ALLOW_REDIRECT=1 — they opted out "
    "on purpose (the durable file still has everything)",
]


def print_honesty_ledger(out=None) -> None:
    """Print the DEFENDED vs NOT-DEFENDED honesty ledger. This is the whole point of
    P5d: report honestly which adversaries are handled and which are not, with NO
    overclaim language."""
    w = (out or sys.stdout)
    w.write("=== VISIBILITY HONESTY LEDGER ===\n")
    w.write("DEFENDED:\n")
    for item in DEFENDED:
        w.write(f"  [DEFENDED] {item}\n")
    w.write("NOT-DEFENDED (stated honestly — no 100%/invincible claim):\n")
    for item in NOT_DEFENDED:
        w.write(f"  [NOT-DEFENDED] {item}\n")
    w.flush()


def main(argv: list[str] | None = None) -> int:
    # Imported lazily so `--help`/import is cheap and the module has no import-time
    # side effects.
    import tempfile

    from cn5_research_cos.models import ResearchState
    from cn5_research_cos.observability.guard import refuse_if_hidden
    from cn5_research_cos.observability.reporter import StageReporter, _force_utf8

    # Force UTF-8 on the consoles BEFORE the guard writes its (CJK) refusal, so the
    # refusal + the live debate render with no mojibake on any machine.
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)

    ap = argparse.ArgumentParser(prog="redteam_visibility")
    ap.add_argument("--run-dir", dest="run_dir", default=None,
                    help="durable debate.md sink dir (P5d). If omitted, a temp dir is used.")
    ap.add_argument("--allow-redirect", dest="allow_redirect", action="store_true",
                    help="escape the refuse-if-hidden guard (mirror cos --allow-redirect).")
    ap.add_argument("--ledger", dest="ledger", action="store_true",
                    help="print the DEFENDED vs NOT-DEFENDED honesty ledger and exit 0.")
    args = ap.parse_args(argv if argv is not None else [])

    if args.ledger:
        print_honesty_ledger()
        return 0

    # P5d guarantee #3: refuse-if-hidden BEFORE doing anything, so the red-team can
    # prove the guard fires on a non-tty subprocess (exit 2) unless --allow-redirect
    # / CN5_COS_ALLOW_REDIRECT=1. The durable file is still written when we proceed.
    refusal = refuse_if_hidden((sys.stdout, sys.stderr), allow_redirect=args.allow_redirect)
    if refusal is not None:
        sys.stderr.write(refusal + "\n")
        sys.stderr.flush()
        return 2

    # A flushed, non-tty-safe reporter on stdout: the whole point of the red-team.
    # P5d: also give it run_dir so the debate persists durably (fail-closed) — the
    # adversary cannot hide what is on disk.
    rs = ResearchState(
        run_id="redteam",
        original_question="我們該不該做隔夜自主研究 agent？（red-team 可見性驗證）",
    )

    def _run(run_dir, base):
        reporter = StageReporter(sys.stdout, run_dir=run_dir)
        reporter.line(START_MARKER)  # flushed start sentinel (proves stream is live)
        # run_loop threads the reporter into the (non-checkpointed) GraphState; each
        # node flushes its stage block to stdout AS THE LOOP RUNS + appends to debate.md.
        from cn5_research_cos.graph import run_loop
        run_loop(rs, base_dir=base, max_iterations=4, now="t0", reporter=reporter)
        reporter.line(END_MARKER)  # flushed end sentinel (must arrive AFTER Albert)

    if args.run_dir is not None:
        with tempfile.TemporaryDirectory() as base:
            _run(args.run_dir, base)
    else:
        with tempfile.TemporaryDirectory() as base:
            _run(base, base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
