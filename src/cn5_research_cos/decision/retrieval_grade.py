"""P9 §E — deterministic CRAG grade-gate. correct=use, ambiguous=refine+fetch-more,
incorrect=discard+escalate. Grades by source metadata (no LLM)."""
from __future__ import annotations
from ..models import Source, SourceType, SourceQuality


def grade_source(s: Source) -> str:
    if s.source_type in (SourceType.primary, SourceType.standard) or s.quality == SourceQuality.high:
        return "correct"
    if s.quality == SourceQuality.low or s.source_type == SourceType.marketing:
        return "incorrect"
    return "ambiguous"
