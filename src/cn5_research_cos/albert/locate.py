"""Resolve the external Albert skill home (skill-cn5-i-am-albert, never vendored).

Discovery order (deterministic, no LLM, no network):
  1. ``$ALBERT_HOME`` — explicit override (env or config-supplied).
  2. Walk UP from cwd looking for a sibling ``skill-cn5-i-am-albert`` checkout.
  3. Absent → return ``None`` (the caller degrades VISIBLY — a degraded audit can
     NOT drive ``terminal_stop`` — and NEVER silently fabricates an audit).

A directory counts as a valid Albert home only if ``run_albert.py`` is present
(the CLI entrypoint we invoke via subprocess — scripts-as-toolbox, NOT imported).
``albert_version(home)`` reads the version from ``<home>/.claude-plugin/plugin.json``
for run metadata; returns ``"unknown"`` (not ``None``/crash) when absent.

NEVER hardcodes a user-local path (e.g. ``D:/D-claude/skill-cn5-i-am-albert``).
Mirrors :mod:`cn5_research_cos.brains.paperwork.locate`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ENV_VAR = "ALBERT_HOME"

# The sibling checkout dir name (verified real): the user keeps
# ``skill-cn5-i-am-albert`` as a sibling under some ancestor of the cwd.
_SIBLING_NAME = "skill-cn5-i-am-albert"


def _is_valid_home(path: Path) -> bool:
    """An Albert home must exist and expose ``run_albert.py`` (the CLI we subprocess)."""
    try:
        return path.is_dir() and (path / "run_albert.py").is_file()
    except OSError:
        return False


def _from_env() -> Path | None:
    raw = os.environ.get(ENV_VAR)
    if not raw:
        return None
    candidate = Path(raw)
    return candidate if _is_valid_home(candidate) else None


def _from_sibling(start: Path | None = None) -> Path | None:
    """Walk UP from ``start`` (default cwd) for a sibling ``skill-cn5-i-am-albert``."""
    here = (start or Path.cwd()).resolve()
    for ancestor in (here, *here.parents):
        candidate = ancestor / _SIBLING_NAME
        if _is_valid_home(candidate):
            return candidate
    return None


def find_albert_home(*, start: Path | None = None) -> Path | None:
    """Return the resolved Albert home, or ``None`` if absent.

    ``start`` (test seam) overrides the directory the sibling walk begins from;
    production omits it and uses the cwd.
    """
    env_home = _from_env()
    if env_home is not None:
        return env_home
    return _from_sibling(start)


def albert_version(home: Path | str) -> str:
    """Read the Albert version from ``<home>/.claude-plugin/plugin.json``.

    Returns ``"unknown"`` when the manifest is missing or unparseable (the caller
    records ``"unknown"`` in run metadata rather than failing the run).
    """
    manifest = Path(home) / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unknown"
    version = data.get("version")
    return str(version) if version is not None else "unknown"
