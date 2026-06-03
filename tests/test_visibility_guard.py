"""Task 3 (P5d): the detect-and-refuse guard — can't ACCIDENTALLY hide the debate.

Honest guarantee #3 (spec 2026-06-03): at startup, if NEITHER stdout NOR stderr is
an interactive TTY, the run REFUSES (exit 2) with a clear "請在終端機跑;若確需非
互動執行,加 --allow-redirect" message. Escapes: ``allow_redirect`` (the
``--allow-redirect`` flag), an ``embedded``/cockpit flag, and the
``CN5_COS_ALLOW_REDIRECT=1`` env var. With an escape the run proceeds; the durable
``debate.md`` still has everything either way.

Mirrors ``run_albert.py::_redirect_refusal`` (+ ``_isatty``). Deterministic
(stream fakes only, no LLM).
"""
from __future__ import annotations

from cn5_research_cos.observability.guard import refuse_if_hidden


class _FakeStream:
    def __init__(self, isatty: bool, raises: bool = False) -> None:
        self._isatty = isatty
        self._raises = raises

    def isatty(self) -> bool:
        if self._raises:
            raise OSError("no fileno")
        return self._isatty


def _notty() -> _FakeStream:
    return _FakeStream(isatty=False)


def _tty() -> _FakeStream:
    return _FakeStream(isatty=True)


def test_refuses_when_no_tty():
    """No stream is an interactive tty AND no escape → refusal (non-None)."""
    msg = refuse_if_hidden([_notty(), _notty()], allow_redirect=False, embedded=False)
    assert msg is not None
    assert "--allow-redirect" in msg
    assert "終端機" in msg  # the CJK guidance


def test_allows_when_a_tty_present():
    """At least one interactive tty → no refusal (None)."""
    assert refuse_if_hidden([_notty(), _tty()], allow_redirect=False) is None


def test_allows_with_redirect_flag():
    """--allow-redirect escape: proceed even with no tty."""
    assert refuse_if_hidden([_notty(), _notty()], allow_redirect=True) is None


def test_allows_when_embedded():
    """cockpit/embedded escape: proceed even with no tty."""
    assert refuse_if_hidden([_notty(), _notty()], allow_redirect=False, embedded=True) is None


def test_allows_with_env(monkeypatch):
    """CN5_COS_ALLOW_REDIRECT=1 escape: proceed even with no tty."""
    monkeypatch.setenv("CN5_COS_ALLOW_REDIRECT", "1")
    assert refuse_if_hidden([_notty(), _notty()], allow_redirect=False) is None


def test_env_other_value_does_not_escape(monkeypatch):
    """Only the exact value 1 escapes; an empty/other value still refuses."""
    monkeypatch.setenv("CN5_COS_ALLOW_REDIRECT", "0")
    assert refuse_if_hidden([_notty(), _notty()], allow_redirect=False) is not None


def test_isatty_exception_treated_as_not_a_tty():
    """A stream whose isatty() raises is treated as NOT a tty (fail-closed toward
    refusal), mirroring run_albert._isatty."""
    msg = refuse_if_hidden([_FakeStream(isatty=False, raises=True)], allow_redirect=False)
    assert msg is not None
