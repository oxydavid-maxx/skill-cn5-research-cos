"""Two-altitude ranking pipeline (P4b Component 2): heuristic (always) then the
opt-in curator (flagged), applied to a bundle's sources AFTER research / source-
critique and BEFORE compress.

A FILTER: it drops sources (dedup/junk/low-relevance + optional LLM curation) and
re-prunes each claim's ``source_refs`` to the surviving sources so a claim never
keeps a dangling ref to a dropped source. Sources/claims are otherwise unmodified.
Deterministic except the opt-in curator (mocked in tests).
"""
from __future__ import annotations

import re

from ..models import EvidenceBundle
from . import curator, heuristic

_WORD_RE = re.compile(r"[^a-z0-9]+")


def _issue_keywords(bundle: EvidenceBundle) -> list[str]:
    """Keywords for the relevance heuristic = the issue/query words."""
    return [t for t in _WORD_RE.split((bundle.query or "").lower()) if len(t) > 2]


def apply(bundle: EvidenceBundle, *, top_k: int = 5,
          model: str | None = None) -> EvidenceBundle:
    """Rank+filter ``bundle.sources`` in place and re-prune claim refs.

    1. heuristic filter (always-on, deterministic);
    2. curator filter (only when ``curator.is_enabled()``), on the heuristic
       survivors;
    3. re-prune every claim's ``source_refs`` to the surviving source ids.
    Returns the same bundle (mutated)."""
    keywords = _issue_keywords(bundle)
    survivors = heuristic.rank(bundle.sources, issue_keywords=keywords, top_k=top_k)

    if curator.is_enabled() and survivors:
        survivors = curator.curate(survivors, issue=bundle.query, model=model)

    bundle.sources = survivors
    surviving_ids = {s.id for s in survivors}
    for c in bundle.claims:
        c.source_refs = [r for r in c.source_refs if r in surviving_ids]
    return bundle
