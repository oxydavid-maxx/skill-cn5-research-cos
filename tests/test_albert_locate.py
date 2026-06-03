"""Deterministic tests for Albert home discovery (P6 Task 1).

Discovery order:
  (1) $ALBERT_HOME
  (2) walk UP from cwd for a sibling skill-cn5-i-am-albert checkout
  (3) absent -> None (caller degrades VISIBLY; never silently fabricates)

A directory counts as a valid Albert home only if ``run_albert.py`` is present.
No network, no LLM. Uses tmp dirs + env monkeypatch. NEVER hardcodes a
user-local path. Mirrors brains/paperwork/locate.py.
"""
from __future__ import annotations

from pathlib import Path

from cn5_research_cos.albert import locate


def _make_home(root: Path, *, version: str | None = "7.7.7-test") -> Path:
    """Build a minimal valid Albert home (a skill-cn5-i-am-albert checkout)."""
    home = root / "skill-cn5-i-am-albert"
    home.mkdir(parents=True)
    (home / "run_albert.py").write_text("# stub entrypoint", encoding="utf-8")
    if version is not None:
        (home / ".claude-plugin").mkdir(parents=True)
        (home / ".claude-plugin" / "plugin.json").write_text(
            '{"name": "i-am-albert", "version": "%s"}' % version, encoding="utf-8"
        )
    return home


def test_env_var_honored(monkeypatch, tmp_path):
    home = _make_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))
    found = locate.find_albert_home()
    assert found is not None
    assert Path(found) == home


def test_env_var_pointing_at_invalid_dir_is_rejected(monkeypatch, tmp_path):
    # Env set but no run_albert.py -> not a valid home.
    bad = tmp_path / "not-albert"
    bad.mkdir()
    monkeypatch.setenv("ALBERT_HOME", str(bad))
    monkeypatch.chdir(tmp_path)  # no sibling checkout either
    assert locate.find_albert_home() is None


def test_sibling_checkout_discovery(monkeypatch, tmp_path):
    # tmp/skill-cn5-i-am-albert  — a sibling checkout above the cwd.
    home = _make_home(tmp_path)
    deep = tmp_path / "some" / "nested" / "workdir"
    deep.mkdir(parents=True)
    monkeypatch.delenv("ALBERT_HOME", raising=False)
    monkeypatch.chdir(deep)
    found = locate.find_albert_home()
    assert found is not None
    assert Path(found) == home


def test_absent_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ALBERT_HOME", raising=False)
    monkeypatch.chdir(tmp_path)  # isolated tmp, no sibling checkout
    assert locate.find_albert_home() is None


def test_env_var_takes_precedence_over_sibling(monkeypatch, tmp_path):
    env_home = _make_home(tmp_path / "envroot")
    sibling = _make_home(tmp_path / "siblingroot")
    monkeypatch.setenv("ALBERT_HOME", str(env_home))
    monkeypatch.chdir(tmp_path / "siblingroot")
    found = locate.find_albert_home()
    assert Path(found) == env_home != sibling


def test_albert_version_read_from_plugin_json(tmp_path):
    home = _make_home(tmp_path, version="7.7.7-test")
    assert locate.albert_version(home) == "7.7.7-test"


def test_albert_version_missing_returns_unknown(tmp_path):
    # A valid home with no version manifest reports "unknown" (not None / crash).
    home = _make_home(tmp_path, version=None)
    assert locate.albert_version(home) == "unknown"
