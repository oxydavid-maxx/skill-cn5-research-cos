"""Real-Albert adapter tests (P6 Task 3) — subprocess MOCKED, no real Albert.

Covers:
  * ``build_albert_input(state)`` -> dict with the current answer/proposal + the
    SOT brief + the PRIOR OPEN challenges (so Albert tracks/resolves, feeding the
    P4b convergence engine).
  * ``RealAlbert.audit(state)`` writes the input json, invokes ``run_albert.py
    --input … --json-out <speed>`` (mocked ``subprocess.run`` returning a stdout
    PATH to a canned albert_challenge.json), parses via the cockpit contract ->
    ``AuditResult``; speed selected via ``audit_tier_for``.
  * Degrade guard: subprocess non-zero / missing-home / unparseable JSON -> a
    DEGRADED AuditResult that can NOT drive terminal_stop.

ALL subprocess invocations are mocked with canned ``--json-out`` JSON. NO real
Albert, NO network in this suite (the live test is opt-in, T5).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from cn5_research_cos.albert import real_adapter
from cn5_research_cos.albert.real_adapter import RealAlbert, build_albert_input
from cn5_research_cos.artifacts import challenge_map
from cn5_research_cos.models import (AuditResult, ChallengeStatus, Decision,
                                     ResearchState, Risk)


# A canned albert_challenge.json (the real run_albert.py --json-out shape: the
# top-level keys the cockpit contract.to_audit_result consumes).
CANNED_CHALLENGE = {
    "verdict": "rework",
    "albert_challenges": [
        {
            "challenge": "競品是否已有此能力?",
            "why_albert_would_ask": "Albert 一定會問競品比較",
            "current_answer": "尚未涵蓋競品",
            "status": "needs_external_research",
            "confidence": "high",
            "evidence_refs": ["NXP S32G3"],
            "missing_info": "competitor feature matrix",
            "blocking_owner": "Product owner",
            "next_action": "build matrix",
            "meeting_ready_response": "we have not named the competitor",
        }
    ],
    "weak_points": ["no moat articulated"],
    "premature_end_risk": {"level": "high"},
    "research_drift_risk": {"level": "low"},
    "recommended_next_action": "pull_human",
    "rationale": "blocked on internal data",
    "missing_business_context": ["target SOP year"],
    "questions_albert_would_ask": ["name the moat"],
    "recommended_next_probe": [{"probe": "feature matrix"}],
    "readiness_score_delta": -2,
    "degraded": False,
}


def _state(**kw) -> ResearchState:
    st = ResearchState(run_id="r1", original_question="該不該自建 AI 研究助手?", **kw)
    st.research_brief = "目標：回答自建可行性"
    return st


def _write_canned(run_dir: Path, payload: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    p = run_dir / "albert_challenge.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def _fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "skill-cn5-i-am-albert"
    home.mkdir(parents=True)
    (home / "run_albert.py").write_text("# stub", encoding="utf-8")
    return home


# --------------------------------------------------------------------------- #
# build_albert_input
# --------------------------------------------------------------------------- #
def test_build_input_includes_answer_brief_and_open_challenges():
    st = _state()
    st.final_memo = "draft answer body"
    challenge_map.upsert(st, challenge="競品如何?", status=ChallengeStatus.open,
                         current_answer="部分回答", confidence=5)
    payload = build_albert_input(st)
    blob = json.dumps(payload, ensure_ascii=False)
    assert st.original_question in blob
    # SOT brief carried
    assert "目標：回答自建可行性" in blob
    # the prior OPEN challenge is carried so Albert tracks/resolves it
    assert "競品如何?" in blob
    # cockpit mode marker for the input_adapter
    assert payload.get("mode") == "cockpit"


def test_build_input_open_challenges_only_live_ones():
    st = _state()
    live = challenge_map.upsert(st, challenge="open one", status=ChallengeStatus.open,
                                confidence=5)
    resolved = challenge_map.upsert(st, challenge="resolved one",
                                    status=ChallengeStatus.open, confidence=5)
    resolved.status = ChallengeStatus.resolved
    payload = build_albert_input(st)
    blob = json.dumps(payload, ensure_ascii=False)
    assert "open one" in blob
    assert "resolved one" not in blob


# --------------------------------------------------------------------------- #
# RealAlbert.audit — happy path (mocked subprocess)
# --------------------------------------------------------------------------- #
def test_audit_parses_canned_contract(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))
    run_dir = tmp_path / "albert-run"
    canned = _write_canned(run_dir, CANNED_CHALLENGE)

    calls = {}

    def fake_run(args, **kw):
        calls["args"] = args
        calls["kw"] = kw
        # run_albert.py --json-out prints the PATH to albert_challenge.json.
        return subprocess.CompletedProcess(args, 0, stdout=str(canned) + "\n", stderr="")

    monkeypatch.setattr(real_adapter.subprocess, "run", fake_run)

    st = _state()
    audit = RealAlbert(work_dir=tmp_path).audit(st)

    assert isinstance(audit, AuditResult)
    assert not audit.degraded
    assert audit.recommended_next_action == Decision.pull_human
    assert audit.premature_end_risk == Risk.high
    assert len(audit.challenges) == 1
    assert audit.challenges[0].confidence == 5  # "high" -> 5
    # subprocess was invoked on run_albert.py with --input + --json-out
    argv = calls["args"]
    assert any("run_albert.py" in str(a) for a in argv)
    assert "--input" in argv
    assert "--json-out" in argv


def test_audit_selects_speed_flag_via_audit_tier(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))
    run_dir = tmp_path / "albert-run"
    canned = _write_canned(run_dir, CANNED_CHALLENGE)
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = list(args)
        return subprocess.CompletedProcess(args, 0, stdout=str(canned), stderr="")

    monkeypatch.setattr(real_adapter.subprocess, "run", fake_run)

    st = _state()
    # final stage -> normal -> NO speed flag
    RealAlbert(work_dir=tmp_path, stage="final").audit(st)
    assert not any(f in seen["args"] for f in ("--flash", "--quick", "--fast"))

    # sentinel stage -> flash flag
    RealAlbert(work_dir=tmp_path, stage="sentinel").audit(st)
    assert "--flash" in seen["args"]


def test_audit_merges_into_challenge_map(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))
    run_dir = tmp_path / "albert-run"
    canned = _write_canned(run_dir, CANNED_CHALLENGE)
    monkeypatch.setattr(
        real_adapter.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0, stdout=str(canned), stderr=""),
    )
    st = _state()
    audit = RealAlbert(work_dir=tmp_path).audit(st)
    # the adapter exposes the parsed challenges; the graph node performs the
    # upsert into the map (so a direct merge here proves the AlbertChallenge shape
    # round-trips through challenge_map.upsert).
    for ch in audit.challenges:
        challenge_map.upsert(st, challenge=ch.challenge, status=ch.status,
                             confidence=ch.confidence or None,
                             evidence_refs=list(ch.evidence_refs) or None)
    assert len(st.albert_challenge_map) == 1
    only = next(iter(st.albert_challenge_map.values()))
    assert only.confidence == 5


# --------------------------------------------------------------------------- #
# Degrade guard
# --------------------------------------------------------------------------- #
def test_degrade_when_home_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("ALBERT_HOME", raising=False)
    monkeypatch.chdir(tmp_path)  # no sibling checkout
    # subprocess must NOT be called when home is absent.
    def boom(*a, **k):
        raise AssertionError("subprocess must not run when ALBERT_HOME is absent")
    monkeypatch.setattr(real_adapter.subprocess, "run", boom)

    audit = RealAlbert(work_dir=tmp_path).audit(_state())
    assert audit.degraded is True
    # a degraded audit can NEVER drive terminal_stop
    assert audit.recommended_next_action != Decision.terminal_stop
    assert audit.verdict.value != "exhausted"  # cannot count as a passed audit


def test_degrade_when_subprocess_nonzero(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))
    monkeypatch.setattr(
        real_adapter.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 2, stdout="", stderr="boom"),
    )
    audit = RealAlbert(work_dir=tmp_path).audit(_state())
    assert audit.degraded is True
    assert audit.recommended_next_action != Decision.terminal_stop


def test_degrade_when_json_unparseable(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))
    run_dir = tmp_path / "albert-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    bad = run_dir / "albert_challenge.json"
    bad.write_text("not json {{{", encoding="utf-8")
    monkeypatch.setattr(
        real_adapter.subprocess, "run",
        lambda args, **kw: subprocess.CompletedProcess(args, 0, stdout=str(bad), stderr=""),
    )
    audit = RealAlbert(work_dir=tmp_path).audit(_state())
    assert audit.degraded is True
    assert audit.recommended_next_action != Decision.terminal_stop


def test_degrade_when_timeout(monkeypatch, tmp_path):
    home = _fake_home(tmp_path)
    monkeypatch.setenv("ALBERT_HOME", str(home))

    def timeout_run(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=1)

    monkeypatch.setattr(real_adapter.subprocess, "run", timeout_run)
    audit = RealAlbert(work_dir=tmp_path).audit(_state())
    assert audit.degraded is True
    assert audit.recommended_next_action != Decision.terminal_stop
