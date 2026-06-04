"""P8 §3 ① — the orchestrator: builds/updates the section-aware task grid each cycle
from the brief + prior results + Albert challenges + coverage gaps. Adaptive
re-decomposition (WebDART-style)."""
from __future__ import annotations
from ..llm.sdk_client import call_structured
from ..models import ResearchState, TaskGrid, TaskCell, CellStatus


def _gaps(rs: ResearchState) -> list[str]:
    g = []
    for ch in rs.albert_challenge_map.values():
        if getattr(ch.status, "value", ch.status) in ("open", "needs_internal_data", "needs_bu_judgment"):
            g.append(ch.challenge)
    for b in rs.evidence:
        g.extend(b.coverage_gaps)
    return g


class MockOrchestrator:
    def plan(self, rs: ResearchState) -> TaskGrid:
        grid = rs.task_grid or TaskGrid(axes=["vendor", "spec_group"])
        if not grid.cells:
            grid.cells["seed|core"] = TaskCell(
                id="seed|core", vendor="seed", spec_group="core",
                objective=rs.success_form or rs.original_question,
                status=CellStatus.open, impact=5)
        for i, gap in enumerate(_gaps(rs)):
            cid = f"gap|{i}"
            if cid not in grid.cells:
                grid.cells[cid] = TaskCell(id=cid, vendor="gap", spec_group=f"g{i}",
                                           objective=gap, status=CellStatus.open, impact=4)
        return grid


_SCHEMA = {"type": "object", "properties": {"cells": {"type": "array", "items": {
    "type": "object", "properties": {
        "vendor": {"type": "string"}, "spec_group": {"type": "string"},
        "objective": {"type": "string"}, "output_format": {"type": "string"},
        "boundaries": {"type": "string"}, "impact": {"type": "integer"}},
    "required": ["vendor", "spec_group", "objective"], "additionalProperties": False}}},
    "required": ["cells"], "additionalProperties": False}
_SYSTEM = ("You are the research ORCHESTRATOR. Decompose the question into a "
           "section-aware task grid: each cell = one (vendor x spec_group) research "
           "subtask that maps to ONE row/section of the final report. Update — do NOT "
           "duplicate covered cells; ADD cells for the gaps/challenges. Each cell needs "
           "objective + output_format + boundaries + impact(0-5). Strict JSON.")


class RealOrchestrator:
    def plan(self, rs: ResearchState) -> TaskGrid:
        grid = rs.task_grid or TaskGrid(axes=["vendor", "spec_group"])
        user = (f"問題：{rs.original_question}\nbrief：{rs.research_brief or ''}\n"
                f"成功形式：{rs.success_form or ''}\n已覆蓋 cell：{list(grid.cells)}\n"
                f"缺口/challenges：\n" + "\n".join(f"- {x}" for x in _gaps(rs)))
        raw = call_structured(_SYSTEM, user, _SCHEMA, model=None)
        for c in raw.get("cells", []):
            cid = f"{c['vendor']}|{c['spec_group']}"
            if cid not in grid.cells:
                grid.cells[cid] = TaskCell(
                    id=cid, vendor=c["vendor"], spec_group=c["spec_group"],
                    objective=c["objective"], output_format=c.get("output_format", ""),
                    boundaries=c.get("boundaries", ""), impact=int(c.get("impact", 3)),
                    status=CellStatus.open)
        return grid
