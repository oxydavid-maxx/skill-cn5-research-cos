"""Two-altitude source ranking (P4b Component 2).

* ``heuristic`` — deterministic, always-on cheap filter (URL dedup, junk drop,
  keyword-overlap relevance + recency/authority, top-k). No LLM, no dependency.
* ``curator`` — opt-in LLM filter on the survivors (GPTR's 5 dimensions). FILTER
  not rewriter; falls back to uncurated on parse failure. Off by default.
"""
from . import curator, heuristic, pipeline

__all__ = ["heuristic", "curator", "pipeline"]
