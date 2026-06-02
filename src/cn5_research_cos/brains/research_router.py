"""Deterministic research-source router (P4a Task 5).

Selects which Researcher gathers evidence for each issue, behind a
``--research-source {web,internal,auto,both}`` selector (default ``auto``):

* ``web``      — always the web RealResearcher (P2b, UNCHANGED).
* ``internal`` — always the InternalDocResearcher (paperwork).
* ``auto``     — per issue (NO LLM): internal if the brief marks internal
  docs/surveys relevant to the issue, else web; ``both`` when the brief says to
  cross-check internal-vs-market.
* ``both``     — always run both and merge.

``route_for_issue`` is the pure routing decision (unit-tested). The
``RoutingResearcher`` adapts the decision into the existing ``Researcher``
Protocol (sync ``research`` + async ``research_async`` for the fan-out).
"""
from __future__ import annotations

import re

from ..models import EvidenceBundle, ResearchState
from .internal_doc import _survey_folders, _topics_overlap

# Brief phrases that mark an issue as needing an internal-vs-market cross-check.
_CROSS_CHECK_RE = re.compile(
    r"cross[\s-]?check|內部.*(?:vs|對比|比較).*(?:市場|market|競品)|"
    r"(?:market|市場|競品).*(?:vs|對比|比較).*內部",
    re.IGNORECASE,
)


def _issue_text(state: ResearchState, issue_id: str) -> str:
    node = state.issue_map.get(issue_id)
    if node is None:
        return issue_id
    return f"{node.title} {node.description or ''}"


def _internal_relevant(state: ResearchState, issue_id: str) -> bool:
    """Internal docs are relevant to THIS issue if the brief flags internal docs
    available, OR a brief survey's requirement_topics overlap the issue."""
    if state.internal_documents_available:
        return True
    issue_text = _issue_text(state, issue_id)
    import yaml
    for folder in _survey_folders(state):
        try:
            ref_map = yaml.safe_load(
                (folder / "reference-map.yaml").read_text(encoding="utf-8")
            ) or {}
        except Exception:  # noqa: BLE001 - unreadable survey -> not relevant
            continue
        if _topics_overlap(issue_text, ref_map.get("requirement_topics") or []):
            return True
    return False


def _cross_check_requested(state: ResearchState) -> bool:
    return bool(_CROSS_CHECK_RE.search(state.research_brief or ""))


def route_for_issue(state: ResearchState, issue_id: str, source: str) -> str:
    """Return the routing decision for one issue: 'web' | 'internal' | 'both'.

    Pure / deterministic (no LLM). Explicit ``web``/``internal`` override auto.
    """
    if source in ("web", "internal", "both"):
        return source
    # auto
    if _internal_relevant(state, issue_id):
        if _cross_check_requested(state):
            return "both"
        return "internal"
    return "web"


def _merge(primary: EvidenceBundle, secondary: EvidenceBundle) -> EvidenceBundle:
    """Merge two bundles (used by 'both'): concatenate sources/claims/gaps,
    keeping both origins. Order: primary first (stable)."""
    return EvidenceBundle(
        query=primary.query or secondary.query,
        issue_id=primary.issue_id or secondary.issue_id,
        sources=[*primary.sources, *secondary.sources],
        claims=[*primary.claims, *secondary.claims],
        contradictions=[*primary.contradictions, *secondary.contradictions],
        missing_evidence=[*primary.missing_evidence, *secondary.missing_evidence],
        suggested_followups=[*primary.suggested_followups, *secondary.suggested_followups],
        coverage_gaps=[*primary.coverage_gaps, *secondary.coverage_gaps],
    )


class RoutingResearcher:
    """Researcher that dispatches to web / internal per the deterministic route."""

    def __init__(self, web, internal, *, source: str = "auto") -> None:
        self._web = web
        self._internal = internal
        self._source = source

    def research(self, state: ResearchState, issue_id: str) -> EvidenceBundle:
        route = route_for_issue(state, issue_id, self._source)
        if route == "internal":
            return self._internal.research(state, issue_id)
        if route == "both":
            web = self._web.research(state, issue_id)
            internal = self._internal.research(state, issue_id)
            return _merge(web, internal)
        return self._web.research(state, issue_id)

    async def research_async(self, state: ResearchState, issue_id: str, *,
                             pool=None) -> EvidenceBundle:
        route = route_for_issue(state, issue_id, self._source)
        if route == "internal":
            return await self._internal.research_async(state, issue_id, pool=pool)
        if route == "both":
            web = await self._web.research_async(state, issue_id, pool=pool)
            internal = await self._internal.research_async(state, issue_id, pool=pool)
            return _merge(web, internal)
        return await self._web.research_async(state, issue_id, pool=pool)
