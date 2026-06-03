"""Phase 5c Task 3 — notify wired into the citation policy (continue, idempotent).

When ``synthesis.memo.route_citations`` routes a decision-critical claim to
``needs_supplement`` at the terminal/synthesize seam, the loop calls
``notify_supplement_needed`` ONCE per item (idempotent across iterations) with the
run_id + items, records a HumanTask, and CONTINUES — it never pauses/stops on it.
"""
from __future__ import annotations

import cn5_research_cos.graph as graph
from cn5_research_cos.brains import build_brains
from cn5_research_cos.models import (
    AuditResult, AuditVerdict, Claim, EvidenceBundle, IssueNode, IssueStatus,
    IssueType, ReadinessScore, ResearchState, Risk, Source,
)


def _critical_state() -> ResearchState:
    rs = ResearchState(run_id="run-xyz", original_question="q")
    rs.fallback_behavior_if_human_unavailable = None
    rs.last_audit = AuditResult(verdict=AuditVerdict.exhausted, degraded=False,
                                premature_end_risk=Risk.low,
                                research_drift_risk=Risk.low)
    rs.readiness_score = ReadinessScore(
        albert_challenge_readiness=5, decision_readiness=5,
        research_exhaustion_readiness=5, human_bottleneck_clarity=5,
        should_continue=False)
    for i in (1, 2):
        rs.issue_map[f"I-{i}"] = IssueNode(
            id=f"I-{i}", title=f"intent {i}", description="d",
            issue_type=IssueType.intent, status=IssueStatus.open,
            impact=5, confidence=2)
    src = Source(id="S-crit", title="src", url="http://y", origin="web",
                 excerpt="Totally unrelated content about cooking recipes.")
    claim = Claim(claim="decision-critical unverified claim", source_refs=["S-crit"],
                  confidence=5, notes="a quote that is not present in the source")
    rs.evidence.append(EvidenceBundle(query="q", issue_id="I-1",
                                      claims=[claim], sources=[src]))
    return rs


def test_notify_called_once_loop_continues(monkeypatch):
    calls = []
    monkeypatch.setattr(graph, "notify_supplement_needed",
                        lambda run_id, items, **kw: calls.append((run_id, list(items))) or True)
    rs = _critical_state()
    state = {"research_state": rs, "llm": "mock", "explicit_emit": False,
             "base_dir": "runs"}

    graph._build_and_gate_memo(state, rs)

    # notified once with run_id + the supplement items
    assert len(calls) == 1
    assert calls[0][0] == "run-xyz"
    assert len(calls[0][1]) == 1
    # a HumanTask exists; the loop continued (no exception, memo produced)
    assert rs.human_tasks
    assert rs.final_memo is not None
    assert "NOT EMITTED" not in rs.final_memo  # emitted, did not hard-block


def test_notify_idempotent_across_iterations(monkeypatch):
    calls = []
    monkeypatch.setattr(graph, "notify_supplement_needed",
                        lambda run_id, items, **kw: calls.append((run_id, list(items))) or True)
    rs = _critical_state()
    state = {"research_state": rs, "llm": "mock", "explicit_emit": False,
             "base_dir": "runs"}

    graph._build_and_gate_memo(state, rs)
    graph._build_and_gate_memo(state, rs)  # a second iteration

    # the same item is NOT re-emailed: still exactly one notify call.
    assert len(calls) == 1


def test_notify_at_most_once_even_with_NEW_items_each_iteration(monkeypatch):
    """Regression for the 2026-06-03 inbox-flood: on a hard topic every iteration
    produces NEW unverified-critical items. The OLD per-new-item logic emailed each
    iteration (flood). We email AT MOST ONCE PER RUN regardless of new items."""
    calls = []
    monkeypatch.setattr(graph, "notify_supplement_needed",
                        lambda run_id, items, **kw: calls.append((run_id, list(items))) or True)
    rs = _critical_state()
    state = {"research_state": rs, "llm": "mock", "explicit_emit": False,
             "base_dir": "runs"}

    graph._build_and_gate_memo(state, rs)            # iteration 1 → emails once

    # iteration 2 introduces a genuinely NEW decision-critical unverified claim
    # (different text) — the OLD code would email it; the fix must NOT.
    src2 = Source(id="S-crit2", title="src2", url="http://z", origin="web",
                  excerpt="Again unrelated text about gardening.")
    claim2 = Claim(claim="a SECOND decision-critical unverified claim",
                   source_refs=["S-crit2"], confidence=5,
                   notes="another quote absent from its source")
    rs.evidence.append(EvidenceBundle(query="q", issue_id="I-2",
                                      claims=[claim2], sources=[src2]))
    graph._build_and_gate_memo(state, rs)            # iteration 2 → must NOT re-email

    assert len(calls) == 1, f"flood: emailed {len(calls)} times (must be at most 1/run)"


def test_no_notify_when_nothing_to_supplement(monkeypatch):
    calls = []
    monkeypatch.setattr(graph, "notify_supplement_needed",
                        lambda *a, **k: calls.append(1) or True)
    rs = ResearchState(run_id="r", original_question="q")
    rs.last_audit = AuditResult(verdict=AuditVerdict.exhausted, degraded=False,
                                premature_end_risk=Risk.low,
                                research_drift_risk=Risk.low)
    rs.readiness_score = ReadinessScore(
        albert_challenge_readiness=5, decision_readiness=5,
        research_exhaustion_readiness=5, human_bottleneck_clarity=5,
        should_continue=False)
    state = {"research_state": rs, "llm": "mock", "explicit_emit": True}
    graph._build_and_gate_memo(state, rs)
    assert calls == []
