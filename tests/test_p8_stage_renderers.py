"""P8 (visibility): live-stream renderers for the 4 orchestration nodes
(clarify / orchestrator / plan_audit / plan_approval).

Two layers, mirroring test_stage_renderers.py + test_reporter_wiring.py:

1. RENDERER layer — each ``render_*`` returns a non-empty str for a POPULATED
   ResearchState AND a safe ``(…)`` placeholder (never crashes) for an EMPTY one.
2. NODE layer — calling the node with a stub reporter injected via
   ``state["reporter"]`` and a minimal brains stub results in the reporter
   receiving a ``stage(<name>, <non-empty body>)`` call. For node_clarify /
   node_plan_approval the interrupt is monkeypatched away so the run does not
   suspend.
"""
from __future__ import annotations

import cn5_research_cos.graph as g
from cn5_research_cos.models import (
    AuditResult, AuditVerdict, AlbertChallenge, CellStatus, ChallengeStatus,
    Decision, ResearchState, Risk, TaskCell, TaskGrid,
)
from cn5_research_cos.observability.reporter import (
    render_clarify, render_orchestrator, render_plan_approval, render_plan_audit,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _grid_two_cells() -> TaskGrid:
    grid = TaskGrid()
    grid.cells["NXP|switch"] = TaskCell(
        id="NXP|switch", vendor="NXP", spec_group="switch",
        objective="比較 NXP 車用乙太交換器規格", status=CellStatus.open, impact=5)
    grid.cells["Marvell|phy"] = TaskCell(
        id="Marvell|phy", vendor="Marvell", spec_group="phy",
        objective="Marvell PHY 100BASE-T1 支援度", status=CellStatus.partial, impact=4)
    return grid


def _populated_state() -> ResearchState:
    rs = ResearchState(run_id="r", original_question="車用乙太網交換器選型 PK")
    rs.task_grid = _grid_two_cells()
    rs.last_audit = AuditResult(
        verdict=AuditVerdict.rework,
        premature_end_risk=Risk.high,
        research_drift_risk=Risk.med,
        weak_points=["缺少實測延遲數據", "成本假設未驗證"],
        challenges=[AlbertChallenge(id="C-1", challenge="競品是否已內建此能力？",
                                    status=ChallengeStatus.open, confidence=5)],
    )
    rs.clarify_converged = True
    rs.steering_events.append({"kind": "plan-approval", "first_cycle": True,
                              "cells": ["NXP|switch", "Marvell|phy"]})
    return rs


# --------------------------------------------------------------------------- #
# Renderer layer
# --------------------------------------------------------------------------- #
def test_render_orchestrator_lists_grid_cells():
    rs = _populated_state()
    txt = render_orchestrator(rs)
    assert txt and isinstance(txt, str)
    assert "2 cells" in txt
    assert "NXP" in txt and "Marvell" in txt
    assert "impact=5" in txt


def test_render_orchestrator_empty_is_safe_placeholder():
    rs = ResearchState(run_id="r", original_question="q")
    txt = render_orchestrator(rs)
    assert isinstance(txt, str) and txt.startswith("(")


def test_render_plan_audit_shows_verdict_and_risks():
    rs = _populated_state()
    txt = render_plan_audit(rs)
    assert txt and isinstance(txt, str)
    assert "rework" in txt
    assert "high" in txt and "med" in txt
    assert "缺少實測延遲數據" in txt or "競品是否已內建此能力？" in txt


def test_render_plan_audit_empty_is_safe_placeholder():
    rs = ResearchState(run_id="r", original_question="q")
    txt = render_plan_audit(rs)
    assert isinstance(txt, str) and txt.startswith("(")


def test_render_plan_approval_shows_cells_and_first_cycle():
    rs = _populated_state()
    txt = render_plan_approval(rs)
    assert txt and isinstance(txt, str)
    assert "2" in txt  # cells presented
    assert "NXP|switch" in txt
    assert "first_cycle" in txt


def test_render_plan_approval_empty_is_safe():
    rs = ResearchState(run_id="r", original_question="q")
    txt = render_plan_approval(rs)
    assert isinstance(txt, str) and "cells presented: 0" in txt


def test_render_clarify_converged():
    rs = ResearchState(run_id="r", original_question="q",
                       decision_criterion="RFQ", success_form="table",
                       research_brief="scope x",
                       fallback_behavior_if_human_unavailable="public-only")
    rs.clarify_converged = True
    txt = render_clarify(rs)
    assert txt and "converged: True" in txt


def test_render_clarify_missing_and_questions():
    rs = ResearchState(run_id="r", original_question="q")
    rs.steering_events.append({"kind": "clarify-ask",
                              "questions": ["決策準則為何？", "成功長什麼樣？"],
                              "missing": ["purpose", "success"]})
    txt = render_clarify(rs)
    assert "converged: False" in txt
    assert "purpose" in txt
    assert "決策準則為何？" in txt


def test_render_clarify_empty_is_safe():
    rs = ResearchState(run_id="r", original_question="q")
    txt = render_clarify(rs)
    assert isinstance(txt, str) and "converged:" in txt


# --------------------------------------------------------------------------- #
# Node layer — reporter receives a stage(name, body) call
# --------------------------------------------------------------------------- #
class _RecordingReporter:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def stage(self, name, body):
        self.calls.append((name, body))


class _OrchBrains:
    class _O:
        def plan(self, rs):
            grid = rs.task_grid or _grid_two_cells()
            return grid
    orchestrator = _O()
    issue_expander = None


class _AuditBrains:
    class _A:
        def audit(self, rs):
            return AuditResult(verdict=AuditVerdict.continue_,
                               premature_end_risk=Risk.low,
                               research_drift_risk=Risk.low)
    auditor = _A()


def _has_stage(reporter, name):
    return [b for (n, b) in reporter.calls if n == name]


def test_node_orchestrator_plan_reports_orchestrator_stage():
    rep = _RecordingReporter()
    rs = ResearchState(run_id="r", original_question="q")
    rs.task_grid = _grid_two_cells()
    g.node_orchestrator_plan({"research_state": rs, "brains": _OrchBrains(),
                              "reporter": rep})
    bodies = _has_stage(rep, "orchestrator")
    assert bodies and bodies[0].strip()


def test_node_plan_audit_reports_plan_audit_stage():
    rep = _RecordingReporter()
    rs = _populated_state()
    g.node_plan_audit({"research_state": rs, "brains": _AuditBrains(),
                       "reporter": rep})
    bodies = _has_stage(rep, "plan_audit")
    assert bodies and bodies[0].strip()


def test_node_plan_approval_reports_plan_approval_stage(monkeypatch):
    monkeypatch.setattr(g, "interrupt", lambda payload: {"answer": "approve"})
    rep = _RecordingReporter()
    rs = _populated_state()
    g.node_plan_approval({"research_state": rs, "brains": _OrchBrains(),
                          "reporter": rep, "mode": "interactive"})
    bodies = _has_stage(rep, "plan_approval")
    assert bodies and bodies[0].strip()


def test_node_clarify_reports_clarify_stage_before_interrupt(monkeypatch):
    seen = {}

    def _fake_interrupt(payload):
        # By the time interrupt is reached, the clarify block must already be sent.
        seen["reported_before_interrupt"] = bool(_has_stage(rep, "clarify"))
        return {"answer": "x"}

    monkeypatch.setattr(g, "interrupt", _fake_interrupt)
    rep = _RecordingReporter()

    class _ClarBrains:
        class _Clar:
            def ask(self, rs, missing):
                return [f"Q:{m}" for m in missing]
        clarifier = _Clar()

    rs = ResearchState(run_id="r", original_question="q")  # nothing pinned -> interrupt
    g.node_clarify({"research_state": rs, "brains": _ClarBrains(),
                    "reporter": rep, "mode": "interactive"})
    bodies = _has_stage(rep, "clarify")
    assert bodies and bodies[0].strip()
    assert seen.get("reported_before_interrupt") is True
