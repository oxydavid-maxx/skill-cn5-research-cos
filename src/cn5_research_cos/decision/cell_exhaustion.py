"""P9 §5 (f)+(h) — DETERMINISTIC exhaustion gate + classification over the LLM's extraction.
The LLM may only say "this field's value is X"; it CANNOT declare N/A. n/a is code-PROVABLE
(all modalities tried + field empty + no gated signal); needs_internal requires a gated signal."""
from __future__ import annotations
from ..models import TaskCell, CellStatus

MAX_CELL_ROUNDS_DEFAULT = 4
K_ROUNDS_NO_NEW = 2


def _criteria_met(cell: TaskCell, filled: set[str]) -> bool:
    crit = set(cell.success_criteria)
    return bool(crit) and crit.issubset(filled)


def public_exhausted(cell: TaskCell, *, filled: set[str], modalities_tried: set[str],
                     all_modalities: set[str], rounds_no_new: int) -> bool:
    if _criteria_met(cell, filled):
        return True
    if modalities_tried >= all_modalities:   # every modality tried
        return True
    return rounds_no_new >= K_ROUNDS_NO_NEW


def classify_cell(cell: TaskCell, *, filled: set[str], gated_detected: bool,
                  public_exhausted: bool) -> CellStatus:
    crit = set(cell.success_criteria)
    if crit and crit.issubset(filled):
        return CellStatus.covered
    if gated_detected and not crit.issubset(filled):
        return CellStatus.blocked        # = needs_internal (a gated source was code-detected)
    if filled:
        return CellStatus.partial
    if public_exhausted:
        return CellStatus.na             # public-exhausted, genuinely nothing (code-proven)
    return CellStatus.open               # NOT exhausted -> keep researching next round
