"""Task 2 (P5d): best-effort LIVE sink — flushed stderr + forced UTF-8, plus a
fail-SILENT tty bonus.

Honest guarantee #2 (spec 2026-06-03): each block also goes to a flushed live
sink with forced UTF-8 (``reconfigure(encoding="utf-8")`` best-effort) so a real
foreground terminal sees it live with no mojibake. The optional ``CONOUT$`` /
``/dev/tty`` bonus is FAIL-SILENT: a raising tty handle must NOT break the run —
the durable file + the configured stream are still written. The tty bonus is
NEVER the guarantee and never raises.

Deterministic (stream/tty fakes only, no LLM).
"""
from __future__ import annotations

import io

from cn5_research_cos.observability.reporter import StageReporter


class _FlushRecordingStream(io.StringIO):
    """A StringIO that records whether flush() was called and supports
    reconfigure() (so the reporter's best-effort UTF-8 forcing is exercised)."""

    def __init__(self) -> None:
        super().__init__()
        self.flushed = False
        self.reconfigured = False

    def flush(self) -> None:  # type: ignore[override]
        self.flushed = True
        super().flush()

    def reconfigure(self, **kwargs) -> None:  # mimic a real TextIO
        self.reconfigured = True


def test_live_stream_flushed_and_utf8_forced():
    """The live (configured) stream is flushed per block and UTF-8 is forced
    best-effort (CJK round-trips with no mojibake)."""
    live = _FlushRecordingStream()
    r = StageReporter(stream=live)
    r.stage("albert_audit", "拷問：護城河被驗證了嗎？")
    assert live.flushed
    assert "拷問：護城河被驗證了嗎？" in live.getvalue()
    # forced UTF-8 is best-effort; when the stream supports reconfigure it is used.
    assert live.reconfigured


def test_reconfigure_failure_is_swallowed():
    """A stream whose reconfigure() raises must NOT break the reporter (best-effort
    UTF-8 forcing is fail-silent)."""

    class _BadReconfigure(io.StringIO):
        def reconfigure(self, **kwargs):
            raise RuntimeError("cannot reconfigure")

    live = _BadReconfigure()
    r = StageReporter(stream=live)
    r.stage("scope", "objective X")  # must not raise
    assert "objective X" in live.getvalue()


def test_tty_bonus_is_fail_silent(tmp_path, monkeypatch):
    """If the optional tty bonus handle RAISES, the run is unaffected: the durable
    file AND the configured stream are still written. The tty bonus never raises."""

    import cn5_research_cos.observability.reporter as rep

    def _raising_tty():
        raise OSError("no tty here")

    monkeypatch.setattr(rep, "_open_tty", _raising_tty, raising=True)

    live = io.StringIO()
    r = StageReporter(run_dir=tmp_path, stream=live)
    r.stage("albert_audit", "[C-1] (open) live + durable still work")  # must not raise

    # configured stream got it
    assert "[C-1] (open) live + durable still work" in live.getvalue()
    # durable file got it
    md = (tmp_path / "debate.md").read_text(encoding="utf-8")
    assert "[C-1] (open) live + durable still work" in md


def test_tty_bonus_written_when_available(tmp_path, monkeypatch):
    """When a tty handle opens, the block IS written to it (the bonus path runs);
    a write error on it is still swallowed."""
    import cn5_research_cos.observability.reporter as rep

    captured = []

    class _FakeTty:
        def write(self, s):
            captured.append(s)

        def flush(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(rep, "_open_tty", lambda: _FakeTty(), raising=True)

    live = io.StringIO()
    r = StageReporter(run_dir=tmp_path, stream=live)
    r.stage("decision", "next: synthesize")
    joined = "".join(captured)
    assert "next: synthesize" in joined
