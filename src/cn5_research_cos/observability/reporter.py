"""StageReporter — flushed, non-tty-safe per-stage stdout writer (P5b Task 1).

The hard requirement (user directive 2026-06-03): a colleague running ``cos run``
MUST be able to WATCH the adversarial debate live on screen, and the per-stage
output MUST still arrive when stdout is piped / redirected / captured by a
subprocess ``stdout=PIPE`` / run in the background — incrementally, NOT held in a
buffer until process exit.

Design choice: PLAIN ``stream.write(...) + stream.flush()`` rather than a Rich
``Console``. Rich auto-detects a non-tty and, while it still writes, its markup /
soft-wrap behaviour and any future ``force_terminal`` regressions are an avoidable
risk for the ONE guarantee that matters here (bytes reach the pipe, flushed, per
stage). A plain write+flush is the simplest thing that provably emits in every
invocation form and is trivially red-teamable (Task 5). No LLM, no wall-clock.
"""
from __future__ import annotations

import sys
from typing import TextIO


class StageReporter:
    """Writes a labeled, delimited per-stage block to ``stream`` and FLUSHES after
    every stage so the content is delivered incrementally (never buffered until
    process exit). Works with any text stream: ``sys.stdout``, a ``StringIO``, a
    real file, or a subprocess-captured pipe.

    The reporter is intentionally dumb: a node renders its block (see
    ``render_*`` helpers) and hands the finished string to ``stage(name, body)``.
    The reporter only labels + writes + flushes.
    """

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream: TextIO = stream if stream is not None else sys.stdout

    def stage(self, name: str, body: str) -> None:
        """Write a ``=== [name] ===`` header, the body, and a trailing blank line,
        then FLUSH. The flush is the guarantee that the block reaches the pipe now
        (not at process exit)."""
        block = f"=== [{name}] ===\n{body}\n\n"
        self.stream.write(block)
        # Flush AFTER the whole block so a reader sees the complete stage at once,
        # and so the next stage cannot be coalesced into a single end-of-run dump.
        self.stream.flush()

    def line(self, text: str) -> None:
        """Emit a single flushed line (used by harnesses / the red-team script for
        start/end markers outside a stage block)."""
        self.stream.write(text + "\n")
        self.stream.flush()
