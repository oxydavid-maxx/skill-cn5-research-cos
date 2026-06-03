"""LLM source curator (P4b Component 2 — opt-in, on the heuristic survivors).

Reproduces the SHAPE of GPTR's ``curate_sources`` prompt contract WITHOUT its
framework glue. It is a FILTER, not a rewriter: the LLM judges each surviving
source on GPTR's REAL 5 dimensions and returns the IDS to KEEP; we return the
SAME ``Source`` objects (identity preserved), never rewritten/summarized.

The 5 dimensions (GPTR ``prompts.py::curate_sources``, source-verified):
  Relevance / Credibility / Currency / Objectivity / Quantitative-Value.

Robustness: on ANY parse/LLM failure we FALL BACK to the uncurated list (GPTR's
``curator.py`` behavior) — curation must never lose sources to an error. Off by
default behind the ``CN5_COS_CURATOR`` flag; uses the SMART/normal model via
``call_structured``.
"""
from __future__ import annotations

import os

from ..llm import sdk_client
from ..models import Source

_CURATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "kept_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kept_ids"],
    "additionalProperties": False,
}

_CURATOR_SYSTEM = (
    "You curate a list of research sources. One job: FILTER — keep only the "
    "sources worth retaining; DO NOT rewrite, summarize, condense, or re-title any "
    "source. Judge each source on FIVE dimensions: (1) Relevance to the issue; "
    "(2) Credibility / authority of the source; (3) Currency / recency; "
    "(4) Objectivity (penalize marketing / promotional spin); (5) Quantitative-Value "
    "(does it carry data/numbers rather than vague claims). Return STRICT JSON with "
    "'kept_ids' = the ids of the sources to KEEP (a subset of the input ids), in "
    "preference order. Return the SAME source-list shape — ids only, no rewriting."
)


def is_enabled() -> bool:
    """Curation is OPT-IN: enabled only when the ``CN5_COS_CURATOR`` flag is set."""
    return os.environ.get("CN5_COS_CURATOR") in ("1", "true", "True", "yes")


def curate(sources: list[Source], *, issue: str,
           model: str | None = None) -> list[Source]:
    """Filter ``sources`` via the LLM on the 5 dimensions, returning the kept
    sources (SAME objects). Falls back to the uncurated list on empty input or any
    failure. ``model`` defaults to the SMART/normal tier via the sdk wrapper."""
    if not sources:
        return []

    listing = "\n".join(
        f"- id={s.id} | title={s.title!r} | type={s.source_type.value} | "
        f"quality={s.quality.value} | url={s.url or '(none)'}"
        for s in sources
    )
    user = (
        f"ISSUE / QUESTION:\n{issue}\n\n"
        f"SOURCES (filter, don't rewrite):\n{listing}\n\n"
        "Return kept_ids = the subset of ids to keep, best first."
    )
    try:
        raw = sdk_client.call_structured(_CURATOR_SYSTEM, user, _CURATOR_SCHEMA,
                                         model=model)
        kept = raw.get("kept_ids")
        if not isinstance(kept, list):
            return list(sources)
    except Exception:  # noqa: BLE001 — never lose sources to a curation error
        return list(sources)

    by_id = {s.id: s for s in sources}
    out: list[Source] = []
    seen: set[str] = set()
    for sid in kept:
        s = by_id.get(sid)
        if s is not None and s.id not in seen:
            out.append(s)
            seen.add(s.id)
    # If the LLM returned a non-empty-but-all-unknown selection, fall back rather
    # than silently drop every source.
    if not out:
        return list(sources)
    return out
