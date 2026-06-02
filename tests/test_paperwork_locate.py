"""Deterministic tests for paperwork home discovery (P4a Task 1).

Discovery order:
  (1) $CN5_PAPERWORK_HOME
  (2) walk UP from cwd for a sibling cn5dd2/CN5DD2_common/plugins/paperwork
  (3) absent -> None (caller degrades)

No network, no LLM. Uses tmp dirs + env monkeypatch. NEVER hardcodes a
user-local path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cn5_research_cos.brains.paperwork import locate

FIXTURE_HOME = Path(__file__).parent / "fixtures" / "paperwork-home"


def _make_home(root: Path) -> Path:
    """Build a minimal valid paperwork home under ``root``."""
    home = root / "plugins" / "paperwork"
    (home / "scripts").mkdir(parents=True)
    (home / ".claude-plugin").mkdir(parents=True)
    (home / "scripts" / "pdf2md.py").write_text("# stub", encoding="utf-8")
    (home / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "paperwork", "version": "1.2.3"}', encoding="utf-8"
    )
    return home


def test_env_var_honored(monkeypatch, tmp_path):
    home = _make_home(tmp_path)
    monkeypatch.setenv("CN5_PAPERWORK_HOME", str(home))
    found = locate.find_paperwork_home()
    assert found is not None
    assert Path(found) == home


def test_env_var_pointing_at_invalid_dir_is_rejected(monkeypatch, tmp_path):
    # Env set but the dir has no scripts/pdf2md.py -> not a valid home.
    bad = tmp_path / "not-paperwork"
    bad.mkdir()
    monkeypatch.setenv("CN5_PAPERWORK_HOME", str(bad))
    monkeypatch.chdir(tmp_path)  # no sibling checkout either
    assert locate.find_paperwork_home() is None


def test_sibling_checkout_discovery(monkeypatch, tmp_path):
    # tmp/cn5dd2/CN5DD2_common/plugins/paperwork  (the real layout)
    common = tmp_path / "cn5dd2" / "CN5DD2_common"
    home = _make_home(common)
    # cwd is a DEEP subdir; discovery must walk UP to find the sibling tree.
    deep = tmp_path / "some" / "nested" / "workdir"
    deep.mkdir(parents=True)
    monkeypatch.delenv("CN5_PAPERWORK_HOME", raising=False)
    monkeypatch.chdir(deep)
    found = locate.find_paperwork_home()
    assert found is not None
    assert Path(found) == home


def test_absent_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("CN5_PAPERWORK_HOME", raising=False)
    monkeypatch.chdir(tmp_path)  # isolated tmp, no sibling checkout
    assert locate.find_paperwork_home() is None


def test_env_var_takes_precedence_over_sibling(monkeypatch, tmp_path):
    env_home = _make_home(tmp_path / "envroot")
    sibling = _make_home(tmp_path / "cn5dd2" / "CN5DD2_common")
    monkeypatch.setenv("CN5_PAPERWORK_HOME", str(env_home))
    monkeypatch.chdir(tmp_path)
    found = locate.find_paperwork_home()
    assert Path(found) == env_home != sibling


def test_paperwork_version_read_from_plugin_json():
    v = locate.paperwork_version(FIXTURE_HOME)
    assert v == "9.9.9-test"


def test_paperwork_version_missing_returns_none(tmp_path):
    assert locate.paperwork_version(tmp_path) is None
