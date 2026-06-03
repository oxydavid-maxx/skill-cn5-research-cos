"""Detect-and-refuse guard — can't ACCIDENTALLY hide the live debate (P5d #3).

If a colleague runs ``cos run`` and BOTH stdout and stderr are non-interactive
(pipe / ``> file`` / ``2>&1 | tee`` / background), the live debate would be
silently hidden. The guard refuses (exit 2) with clear guidance UNLESS an explicit
escape was chosen: ``--allow-redirect``, an embedded/cockpit caller, or
``CN5_COS_ALLOW_REDIRECT=1``. The durable ``runs/<id>/debate.md`` still has the
full debate in every case — the refusal only prevents the *accidental* hide.

Mirrors ``skill-cn5-i-am-albert/run_albert.py::_redirect_refusal`` (+ ``_isatty``).
Deterministic — no LLM, no wall-clock.
"""
from __future__ import annotations

import os

REFUSAL_MESSAGE = (
    "cos 拒絕執行:辯論過程應即時顯示在終端機,但偵測到輸出被導走"
    "(pipe / > 檔案 / 2>&1 | tee / 背景執行),沒有任何互動式終端機可看。\n"
    "請直接在終端機跑(別加 | tee、> 檔案、2>&1 |、或丟背景)。\n"
    "完整存檔仍會在 runs/<id>/debate.md(可用 `cos watch <run_id>` 跟看)。\n"
    "若確實需要非互動執行,加 --allow-redirect(或設 CN5_COS_ALLOW_REDIRECT=1)。"
)


def _isatty(stream) -> bool:
    """True iff ``stream`` is an interactive TTY. A stream whose ``isatty`` raises
    or is absent is treated as NOT a tty (fail-closed toward refusal). Mirrors
    ``run_albert._isatty``."""
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001 - absent/raising isatty → not a tty
        return False


def refuse_if_hidden(streams, *, allow_redirect: bool, embedded: bool = False) -> str | None:
    """Return a refusal message (exit-2 sentinel) when the live debate would be
    ACCIDENTALLY hidden — i.e. NO stream is an interactive tty and no escape was
    chosen — else None.

    Escapes (any one → None): ``embedded`` (cockpit), ``allow_redirect`` (the
    ``--allow-redirect`` flag), or ``CN5_COS_ALLOW_REDIRECT=1`` in the env.
    """
    if embedded or allow_redirect or os.environ.get("CN5_COS_ALLOW_REDIRECT") == "1":
        return None
    if any(_isatty(s) for s in streams):
        return None
    return REFUSAL_MESSAGE
