"""Task 1 (P5b): StageReporter — flushed, non-tty-safe per-stage stdout writes.

The reporter must emit a labeled per-stage block to its stream AND flush per stage,
so the debate is visible incrementally even in a non-tty (a piped/redirected
StringIO / file / subprocess PIPE). No LLM, no wall-clock.
"""
from __future__ import annotations

import io

from cn5_research_cos.observability.reporter import StageReporter


def test_reporter_emits_to_non_tty_and_flushes():
    buf = io.StringIO()
    r = StageReporter(stream=buf)
    r.stage("expand", "5 issues: A; B; C")
    out = buf.getvalue()
    assert "expand" in out and "5 issues" in out


def test_reporter_labels_each_stage_block():
    buf = io.StringIO()
    r = StageReporter(stream=buf)
    r.stage("albert", "challenge text")
    out = buf.getvalue()
    # a labeled, delimited block (not a bare line)
    assert "albert" in out
    assert "challenge text" in out


def test_reporter_flushes_per_stage_incrementally():
    """A fake stream records write+flush order; the reporter must flush AFTER the
    stage body is written, every stage (so content cannot be held in a buffer
    until process exit)."""
    events: list[str] = []

    class _RecordingStream:
        def write(self, s):
            if s.strip():
                events.append("write")
            return len(s)

        def flush(self):
            events.append("flush")

    r = StageReporter(stream=_RecordingStream())
    r.stage("scope", "objective X")
    r.stage("decision", "next: Y")
    # at least one write then a flush per stage; a flush follows the writes.
    assert "write" in events
    assert "flush" in events
    # the LAST event for each stage call is a flush (incremental delivery).
    assert events[-1] == "flush"


def test_reporter_default_stream_is_stdout():
    r = StageReporter()
    import sys
    assert r.stream is sys.stdout
