"""P10a §C — per-cell synthesis: wires the deterministic gates grade_source (CRAG)
+ triangulate over the LLM's structured FieldObservations. No LLM here — code decides
which fields are FILLED, the winning value, and where sources contradict."""
from __future__ import annotations
from dataclasses import dataclass, field as _field

from ..models import EvidenceBundle, Source, TaskCell
from .retrieval_grade import grade_source
from .triangulation import triangulate


@dataclass
class CellSynthesis:
    filled: set[str] = _field(default_factory=set)        # fields with an accepted value
    chosen: dict[str, str] = _field(default_factory=dict) # field -> winning value
    contradictions: set[str] = _field(default_factory=set)
    weak: set[str] = _field(default_factory=set)          # only weakly_sourced


def synthesize_cell(cell: TaskCell, bundles: list[EvidenceBundle]) -> CellSynthesis:
    crit = set(cell.success_criteria)
    src_by_id: dict[str, Source] = {}
    for b in bundles:
        for s in b.sources:
            src_by_id[s.id] = s
    per_field: dict[str, list[tuple[str, Source]]] = {}
    for b in bundles:
        for o in b.observations:
            if o.field not in crit:
                continue                          # LLM cannot invent fields
            src = src_by_id.get(o.source_ref)
            if src is None:
                continue
            if grade_source(src) == "incorrect":  # CRAG: junk does not fill
                continue
            per_field.setdefault(o.field, []).append((o.value, src))
    syn = CellSynthesis()
    for fld, obs in per_field.items():
        tri = triangulate(obs)
        if tri.status in ("corroborated", "weakly_sourced"):
            syn.filled.add(fld)
            syn.chosen[fld] = tri.value
            if tri.status == "weakly_sourced":
                syn.weak.add(fld)
        if tri.contradiction:
            syn.contradictions.add(fld)
    return syn
