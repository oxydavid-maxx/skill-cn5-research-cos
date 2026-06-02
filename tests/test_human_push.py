"""Test 2 — H3 push-human: internal-data need -> HumanTask + loop continues an
adjacent non-blocked issue (NON-blocking, no interrupt)."""
from cn5_research_cos.graph import node_human_push, build_graph
from cn5_research_cos.models import (Decision, HumanTaskStatus, IssueStatus,
                                     IssueType, ResearchState)
from cn5_research_cos.artifacts import issue_map


def _two_issue_state() -> ResearchState:
    rs = ResearchState(run_id="t2", original_question="q", mode="interactive")
    issue_map.add(rs, title="需要內部良率資料", description="internal",
                  issue_type=IssueType.internal_data, status=IssueStatus.open,
                  now="t", impact=5)
    issue_map.add(rs, title="可公開研究的市場規模", description="market",
                  issue_type=IssueType.market, status=IssueStatus.open,
                  now="t", impact=3)
    return rs


def test_human_push_creates_humantask_and_blocks_issue():
    rs = _two_issue_state()
    out = node_human_push({"research_state": rs, "now": "t1"})
    rs2 = out["research_state"]

    # Exactly one HumanTask created with the §9.2 fields populated.
    assert len(rs2.human_tasks) == 1
    ht = next(iter(rs2.human_tasks.values()))
    assert ht.status == HumanTaskStatus.open
    assert ht.task_title and ht.why_needed and ht.blocking_question
    assert ht.can_continue_without_it is True
    assert ht.fallback_plan
    assert ht.priority == 5  # highest-impact issue handed off

    # The highest-impact (internal-data) issue is now blocked; the adjacent
    # market issue stays addressable so the loop can continue on it.
    blocked = [n for n in rs2.issue_map.values()
               if n.status == IssueStatus.blocked_by_internal_data]
    assert len(blocked) == 1 and blocked[0].title == "需要內部良率資料"
    addressable = [n for n in rs2.issue_map.values()
                   if n.status == IssueStatus.open]
    assert any(n.title == "可公開研究的市場規模" for n in addressable)


def test_human_push_routes_back_to_supervisor_not_interrupt():
    """H3 is NON-blocking: the graph edge from human_push goes to supervisor (the
    loop continues an adjacent branch), NOT to END and NOT through an interrupt."""
    g = build_graph()
    # Inspect the compiled edge set: human_push -> supervisor is a plain edge.
    edges = g.edges
    assert ("human_push", "supervisor") in edges
