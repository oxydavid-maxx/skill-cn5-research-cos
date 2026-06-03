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

import sys

START_MARKER = "[[REDTEAM-START]]"
END_MARKER = "[[REDTEAM-END]]"


def main(argv: list[str] | None = None) -> int:
    # Imported lazily so `--help`/import is cheap and the module has no import-time
    # side effects.
    import tempfile

    from cn5_research_cos.models import ResearchState
    from cn5_research_cos.observability.reporter import StageReporter

    # A flushed, non-tty-safe reporter on stdout: the whole point of the red-team.
    reporter = StageReporter(sys.stdout)
    reporter.line(START_MARKER)  # flushed start sentinel (proves stream is live)

    # Mock brains (default llm="mock") → fully deterministic, no LLM / no network.
    rs = ResearchState(
        run_id="redteam",
        original_question="我們該不該做隔夜自主研究 agent？（red-team 可見性驗證）",
    )
    with tempfile.TemporaryDirectory() as base:
        # run_loop threads the reporter into the (non-checkpointed) GraphState; each
        # node flushes its stage block to stdout AS THE LOOP RUNS.
        from cn5_research_cos.graph import run_loop
        run_loop(rs, base_dir=base, max_iterations=4, now="t0", reporter=reporter)

    reporter.line(END_MARKER)  # flushed end sentinel (must arrive AFTER Albert)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
