"""--albert sim|real hot-swap + degrade + flash-availability probe (P6 Task 4).

Subprocess MOCKED throughout — no real Albert, no network.

  * ``build_brains(albert="sim")`` (default) keeps RealAlbertSimulator (the 391
    prior tests stay green); ``albert="real"`` wires RealAlbert at the sentinel +
    deep-audit tiers, behind the SAME Auditor seam.
  * ALBERT_HOME absent + ``--albert real`` -> the audit degrades VISIBLY (a
    degraded AuditResult that cannot drive terminal_stop); the loop continues.
  * flash-availability probe: ``albert_supports_flash(home)`` checks
    ``run_albert.py --help`` for ``--flash``. Absent -> the sentinel falls back to
    the simulator and LOGS it (never fails).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cn5_research_cos.albert import probe as albert_probe
from cn5_research_cos.albert.real_adapter import RealAlbert
from cn5_research_cos.albert.simulator import RealAlbertSimulator
from cn5_research_cos.brains import build_brains
from cn5_research_cos.models import Decision


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    albert_probe.reset_cache()
    yield
    albert_probe.reset_cache()


def _fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "skill-cn5-i-am-albert"
    home.mkdir(parents=True)
    (home / "run_albert.py").write_text("# stub", encoding="utf-8")
    return home


# --------------------------------------------------------------------------- #
# build_brains --albert seam
# --------------------------------------------------------------------------- #
def test_default_albert_is_sim_simulator():
    # mock + default keeps the deterministic stub auditor (P1 path unchanged).
    brains = build_brains("mock")
    assert not isinstance(brains.auditor, RealAlbert)


def test_real_llm_default_albert_sim_keeps_simulator():
    brains = build_brains("real", albert="sim")
    assert isinstance(brains.auditor, RealAlbertSimulator)
    # deep auditor is the tier wrapper around the simulator
    assert not isinstance(getattr(brains.deep_auditor, "base", None), RealAlbert)


def test_real_llm_albert_real_wires_real_albert(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))
    # Albert advertises --flash -> sentinel is the real adapter (no sim fallback).
    monkeypatch.setattr(albert_probe, "albert_supports_flash", lambda home: True)
    brains = build_brains("real", albert="real")
    assert isinstance(brains.auditor, RealAlbert)
    # deep auditor delegates to a RealAlbert too (tier wrapper .base)
    assert isinstance(getattr(brains.deep_auditor, "base", None), RealAlbert)


def test_real_albert_no_flash_sentinel_falls_back_to_simulator(monkeypatch, tmp_path, capsys):
    home = _fake_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))
    # Albert lacks --flash -> sentinel falls back to the simulator + logs it; the
    # deep-audit gate still uses real Albert.
    monkeypatch.setattr(albert_probe, "albert_supports_flash", lambda home: False)
    brains = build_brains("real", albert="real")
    assert isinstance(brains.auditor, RealAlbertSimulator)
    assert isinstance(getattr(brains.deep_auditor, "base", None), RealAlbert)
    assert "no --flash" in capsys.readouterr().err


def test_albert_real_rejects_with_mock_llm():
    # real Albert needs the real brain stack; mock+real is a config error.
    with pytest.raises((ValueError, NotImplementedError)):
        build_brains("mock", albert="real")


def test_unknown_albert_value_rejected():
    with pytest.raises((ValueError, NotImplementedError)):
        build_brains("real", albert="bogus")


# --------------------------------------------------------------------------- #
# Degrade-visibly when home absent under --albert real
# --------------------------------------------------------------------------- #
def test_real_albert_degrades_when_home_absent(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ALBERT_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    brains = build_brains("real", albert="real")
    from cn5_research_cos.models import ResearchState
    audit = brains.auditor.audit(ResearchState(run_id="r", original_question="q"))
    assert audit.degraded is True
    assert audit.recommended_next_action != Decision.terminal_stop
    err = capsys.readouterr().err
    assert "DEGRADED" in err  # visible warning


# --------------------------------------------------------------------------- #
# flash-availability probe
# --------------------------------------------------------------------------- #
def test_flash_probe_true_when_help_lists_flash(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setattr(
        albert_probe.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0,
                                                       stdout="--flash --quick", stderr=""),
    )
    assert albert_probe.albert_supports_flash(home) is True


def test_flash_probe_false_when_help_lacks_flash(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setattr(
        albert_probe.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0,
                                                       stdout="--quick --fast", stderr=""),
    )
    assert albert_probe.albert_supports_flash(home) is False


def test_flash_probe_false_on_error(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)

    def boom(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr(albert_probe.subprocess, "run", boom)
    # probe failure must NOT raise — it degrades to "no flash".
    assert albert_probe.albert_supports_flash(home) is False
