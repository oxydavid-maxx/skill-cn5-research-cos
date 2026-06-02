"""Resolve the external paperwork plugin home (gerrit, never vendored).

Discovery order (deterministic, no LLM, no network):
  1. ``$CN5_PAPERWORK_HOME`` — explicit override (env or config-supplied).
  2. Walk UP from cwd looking for a sibling
     ``cn5dd2/CN5DD2_common/plugins/paperwork`` checkout.
  3. Absent → return ``None`` (the caller degrades to web-only with a VISIBLE
     warning — never silently fabricates internal evidence).

A directory counts as a valid paperwork home only if ``scripts/pdf2md.py`` is
present (the preflight check from the spec). ``paperwork_version`` reads the
plugin version from ``<home>/.claude-plugin/plugin.json`` for run metadata.

NEVER hardcodes a user-local path (e.g. ``D:/D-claude/cn5dd2/...``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ENV_VAR = "CN5_PAPERWORK_HOME"

# The sibling-checkout relative layout (verified real): the gerrit CN5DD2_common
# checkout exposes the plugin at this path under some ancestor of the cwd.
_SIBLING_SUFFIX = ("cn5dd2", "CN5DD2_common", "plugins", "paperwork")


def _is_valid_home(path: Path) -> bool:
    """A paperwork home must exist and expose ``scripts/pdf2md.py``."""
    try:
        return path.is_dir() and (path / "scripts" / "pdf2md.py").is_file()
    except OSError:
        return False


def _from_env() -> Path | None:
    raw = os.environ.get(ENV_VAR)
    if not raw:
        return None
    candidate = Path(raw)
    return candidate if _is_valid_home(candidate) else None


def _from_sibling(start: Path | None = None) -> Path | None:
    """Walk UP from ``start`` (default cwd) for a sibling checkout."""
    here = (start or Path.cwd()).resolve()
    for ancestor in (here, *here.parents):
        candidate = ancestor.joinpath(*_SIBLING_SUFFIX)
        if _is_valid_home(candidate):
            return candidate
    return None


def find_paperwork_home(*, start: Path | None = None) -> Path | None:
    """Return the resolved paperwork home, or ``None`` if absent.

    ``start`` (test seam) overrides the directory the sibling walk begins from;
    production omits it and uses the cwd.
    """
    env_home = _from_env()
    if env_home is not None:
        return env_home
    return _from_sibling(start)


def paperwork_version(home: Path | str) -> str | None:
    """Read the plugin version from ``<home>/.claude-plugin/plugin.json``.

    Returns ``None`` when the manifest is missing or unparseable (the caller
    records ``None`` in run metadata rather than failing the run).
    """
    manifest = Path(home) / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version")
    return str(version) if version is not None else None
