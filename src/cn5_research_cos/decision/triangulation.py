"""P9 §D — cross-source triangulation + contradiction detection. Deterministic.
corroborated = >=2 sources agree OR 1 primary; weakly_sourced = single secondary;
contradiction = differing values, resolved by primary > recency > quality."""
from __future__ import annotations
from dataclasses import dataclass
from ..models import Source, SourceType, SourceQuality

_Q_RANK = {SourceQuality.high: 3, SourceQuality.medium: 2, SourceQuality.low: 1, SourceQuality.unknown: 0}


def _is_primary(s: Source) -> bool:
    return s.source_type in (SourceType.primary, SourceType.standard)


def _norm(v: str) -> str:
    return " ".join(str(v).strip().lower().split())


@dataclass
class TriResult:
    value: str | None
    status: str           # corroborated | weakly_sourced | none
    contradiction: bool
    all_values: dict      # normalized_value -> [source_id]


def triangulate(observations: list[tuple[str, Source]]) -> TriResult:
    """observations = [(value, source), ...] for ONE (product, field)."""
    if not observations:
        return TriResult(None, "none", False, {})
    groups: dict[str, list[Source]] = {}
    raw: dict[str, str] = {}
    for val, src in observations:
        k = _norm(val)
        groups.setdefault(k, []).append(src)
        raw[k] = val
    contradiction = len(groups) > 1
    # pick the winning value group: prefer a group with a primary; else most sources; else best quality
    def group_key(item):
        k, srcs = item
        has_primary = any(_is_primary(s) for s in srcs)
        best_q = max(_Q_RANK[s.quality] for s in srcs)
        return (has_primary, len(srcs), best_q)
    win_k, win_srcs = max(groups.items(), key=group_key)
    if any(_is_primary(s) for s in win_srcs) or len(win_srcs) >= 2:
        status = "corroborated"
    else:
        status = "weakly_sourced"
    return TriResult(raw[win_k], status, contradiction,
                     {k: [s.id for s in v] for k, v in groups.items()})
