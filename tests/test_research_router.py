"""research-source router tests (P4a Task 5) — deterministic, no LLM.

--research-source {web,internal,auto,both} selects the Researcher per issue.
auto: internal if the brief marks internal docs/surveys relevant to the issue,
else web; both when the brief says cross-check internal-vs-market. Web
RealResearcher is UNCHANGED. build_brains wiring mirrors --llm.
"""
from __future__ import annotations

from pathlib import Path

from cn5_research_cos.brains import build_brains
from cn5_research_cos.brains.research_router import (RoutingResearcher,
                                                     route_for_issue)
from cn5_research_cos.models import IssueStatus, IssueType, ResearchState

SURVEY = Path(__file__).parent / "fixtures" / "paperwork-survey"


def _state(**kw) -> ResearchState:
    rs = ResearchState(run_id="r", original_question="q")
    for k, v in kw.items():
        setattr(rs, k, v)
    return rs


def _issue(rs, title):
    from cn5_research_cos.artifacts import issue_map
    return issue_map.add(rs, title=title, description=title,
                         issue_type=IssueType.technical, status=IssueStatus.open,
                         now="t", impact=4, confidence=1)


# --------------------------------------------------------------------------- #
# Pure auto routing
# --------------------------------------------------------------------------- #
def test_auto_routes_web_when_no_internal_signal():
    rs = _state()
    iss = _issue(rs, "market size of automotive I3C")
    assert route_for_issue(rs, iss.id, "auto") == "web"


def test_auto_routes_internal_when_survey_topic_matches():
    rs = _state(available_sources=[str(SURVEY)])
    iss = _issue(rs, "i2c-backward-compatibility")
    assert route_for_issue(rs, iss.id, "auto") == "internal"


def test_auto_routes_internal_when_documents_available_flag_set():
    rs = _state(internal_documents_available=True)
    iss = _issue(rs, "internal IP feature coverage")
    assert route_for_issue(rs, iss.id, "auto") == "internal"


def test_auto_routes_both_when_brief_says_cross_check():
    rs = _state(internal_documents_available=True,
                research_brief="必須 cross-check 內部 IP vs market 競品")
    iss = _issue(rs, "internal vs market positioning")
    assert route_for_issue(rs, iss.id, "auto") == "both"


def test_explicit_web_and_internal_override_auto():
    rs = _state(available_sources=[str(SURVEY)])
    iss = _issue(rs, "i2c-backward-compatibility")
    assert route_for_issue(rs, iss.id, "web") == "web"
    assert route_for_issue(rs, iss.id, "internal") == "internal"


# --------------------------------------------------------------------------- #
# RoutingResearcher dispatch
# --------------------------------------------------------------------------- #
class _FakeWeb:
    def research(self, state, issue_id):
        from cn5_research_cos.models import Claim, EvidenceBundle, Source
        return EvidenceBundle(query="w", issue_id=issue_id,
                              sources=[Source(id="W1", title="web")],
                              claims=[Claim(claim="web claim", source_refs=["W1"])])

    async def research_async(self, state, issue_id, *, pool=None):
        return self.research(state, issue_id)


class _FakeInternal:
    def research(self, state, issue_id, *, pdfs=None):
        from cn5_research_cos.models import Claim, EvidenceBundle, Source
        return EvidenceBundle(query="i", issue_id=issue_id,
                              sources=[Source(id="I1", title="internal")],
                              claims=[Claim(claim="internal claim", source_refs=["I1"])])

    async def research_async(self, state, issue_id, *, pool=None, pdfs=None):
        return self.research(state, issue_id)


def test_routing_researcher_dispatches_internal(monkeypatch):
    rs = _state(internal_documents_available=True)
    iss = _issue(rs, "internal IP detail")
    r = RoutingResearcher(_FakeWeb(), _FakeInternal(), source="auto")
    bundle = r.research(rs, iss.id)
    assert bundle.sources[0].id == "I1"


def test_routing_researcher_dispatches_web(monkeypatch):
    rs = _state()
    iss = _issue(rs, "external market trend")
    r = RoutingResearcher(_FakeWeb(), _FakeInternal(), source="auto")
    bundle = r.research(rs, iss.id)
    assert bundle.sources[0].id == "W1"


def test_routing_researcher_both_merges(monkeypatch):
    rs = _state(internal_documents_available=True,
                research_brief="cross-check 內部 vs market")
    iss = _issue(rs, "internal vs market")
    r = RoutingResearcher(_FakeWeb(), _FakeInternal(), source="auto")
    bundle = r.research(rs, iss.id)
    ids = {s.id for s in bundle.sources}
    assert ids == {"W1", "I1"}
    assert len(bundle.claims) == 2


def test_routing_researcher_async_dispatches(monkeypatch):
    import asyncio
    rs = _state(internal_documents_available=True)
    iss = _issue(rs, "internal detail")
    r = RoutingResearcher(_FakeWeb(), _FakeInternal(), source="auto")
    bundle = asyncio.run(r.research_async(rs, iss.id, pool=None))
    assert bundle.sources[0].id == "I1"


def test_satisfies_researcher_protocol():
    from cn5_research_cos.brains import interfaces
    r = RoutingResearcher(_FakeWeb(), _FakeInternal(), source="auto")
    assert isinstance(r, interfaces.Researcher)


# --------------------------------------------------------------------------- #
# build_brains wiring (mirrors --llm)
# --------------------------------------------------------------------------- #
def test_build_brains_accepts_research_source_mock():
    # mock + web is the unchanged default; internal/auto select RoutingResearcher
    brains = build_brains("mock", research_source="auto")
    assert isinstance(brains.researcher, RoutingResearcher)


def test_build_brains_web_keeps_plain_researcher():
    brains = build_brains("mock", research_source="web")
    # web-only keeps the original (non-routing) researcher
    assert not isinstance(brains.researcher, RoutingResearcher)
