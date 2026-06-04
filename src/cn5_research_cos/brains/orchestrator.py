"""P8 §3 ① — the orchestrator: builds/updates the section-aware task grid each cycle
from the brief + prior results + Albert challenges + coverage gaps. Adaptive
re-decomposition (WebDART-style)."""
from __future__ import annotations
import re
from ..llm.sdk_client import call_structured
from ..models import ResearchState, TaskGrid, TaskCell, CellStatus

# Caps for the condensed orchestration prompt (root-cause fix: dumping the full
# ~9KB topic into a Sonnet structured call times out at 300s x 5 retries).
_CONDENSED_QUESTION_CAP = 2000   # vendor list + section headers + core task line
_BRIEF_SLICE = 500               # short slice of the brief, not the whole thing
_FALLBACK_QUESTION_CAP = 1500    # non-structured question fallback


def _condense_question(question: str) -> str:
    """Deterministically extract just the decomposition axes the orchestrator
    needs from a (possibly ~9KB) structured PK question:

    - the vendor list block (``廠商：`` / ``Vendors:`` followed by numbered lines),
    - the spec-GROUP section headers (lines starting with ``#`` / ``##`` — these
      ARE the spec_group axis, e.g. "Switch fabric", "TSN / AVB / timing"),
    - the core task line (``核心任務`` / ``核心任務：`` block, first line).

    Capped to ~``_CONDENSED_QUESTION_CAP`` chars. If no section headers are found
    (a non-structured question), fall back to the first ~1500 chars rather than
    dumping everything.
    """
    lines = question.splitlines()

    # (a) vendor block: from a vendor-list header until the next blank line.
    vendors: list[str] = []
    for i, ln in enumerate(lines):
        if re.match(r"^\s*(廠商|vendors?)\s*[：:]", ln, flags=re.IGNORECASE):
            vendors.append(ln.strip())
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    break
                vendors.append(nxt.strip())
            break

    # (b) spec-group section headers (Markdown-ish: lines starting with # / ##).
    headers = [ln.strip() for ln in lines if re.match(r"^\s*#{1,6}\s+\S", ln)]

    # (c) core task line: first non-empty line after a 核心任務 / core-task header.
    core: list[str] = []
    for i, ln in enumerate(lines):
        if re.match(r"^\s*(核心任務|core task)\s*[：:]?\s*$", ln, flags=re.IGNORECASE):
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    core.append(nxt.strip())
                    break
            break

    if not headers:
        # Non-structured question: don't dump 9KB.
        return question[:_FALLBACK_QUESTION_CAP]

    parts: list[str] = []
    if core:
        parts.append("核心任務：" + " ".join(core))
    if vendors:
        parts.append("\n".join(vendors))
    if headers:
        parts.append("規格分組（spec_group 軸）：\n" + "\n".join(f"- {h}" for h in headers))
    return "\n\n".join(parts)[:_CONDENSED_QUESTION_CAP]


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
        brief = (rs.research_brief or "")[:_BRIEF_SLICE]
        user = (f"問題（已濃縮為分解軸）：\n{_condense_question(rs.original_question)}\n\n"
                f"brief（節錄）：{brief}\n"
                f"成功形式：{rs.success_form or ''}\n已覆蓋 cell：{list(grid.cells)}\n"
                f"缺口/challenges：\n" + "\n".join(f"- {x}" for x in _gaps(rs)))
        # Fail-fast timeout policy: a generous single-ish shot with few retries so
        # a slow call fails clean instead of piling 5x300s on the real topic.
        raw = call_structured(_SYSTEM, user, _SCHEMA, model=None,
                              timeout_sec=600, attempts=2)
        for c in raw.get("cells", []):
            cid = f"{c['vendor']}|{c['spec_group']}"
            if cid not in grid.cells:
                grid.cells[cid] = TaskCell(
                    id=cid, vendor=c["vendor"], spec_group=c["spec_group"],
                    objective=c["objective"], output_format=c.get("output_format", ""),
                    boundaries=c.get("boundaries", ""), impact=int(c.get("impact", 3)),
                    status=CellStatus.open)
        return grid
