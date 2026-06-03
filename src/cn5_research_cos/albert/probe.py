"""One-time capability probe of the Albert CLI (P6 Task 4).

The per-iteration sentinel wants Albert ``--flash`` (a direct single Opus call).
``--flash`` is a CLI capability the external Albert may or may not expose yet, so
we PROBE it rather than assume: run ``run_albert.py --help`` and look for the
``--flash`` token. If the flag is absent (or the probe itself fails), the caller
falls back to the existing cheap simulator at the sentinel tier and LOGS it —
never fails the run.

scripts-as-toolbox: subprocess only, never imports Albert's package. Fail-silent
(returns ``False`` on any error). The result is cached per-home so the probe runs
at most once per process.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROBE_TIMEOUT = 30
_cache: dict[str, bool] = {}


def _python() -> list[str]:
    return ["py", "-3"] if sys.platform.startswith("win") else [sys.executable]


def albert_supports_flash(home: Path | str) -> bool:
    """True iff ``run_albert.py --help`` advertises ``--flash``. Fail-silent.

    Cached per resolved home path so the probe runs at most once per process.
    """
    key = str(Path(home))
    if key in _cache:
        return _cache[key]
    result = _probe(home)
    _cache[key] = result
    return result


def _probe(home: Path | str) -> bool:
    argv = [*_python(), str(Path(home) / "run_albert.py"), "--help"]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_PROBE_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    text = (proc.stdout or "") + (proc.stderr or "")
    return "--flash" in text


def reset_cache() -> None:
    """Clear the per-home probe cache (test seam)."""
    _cache.clear()
