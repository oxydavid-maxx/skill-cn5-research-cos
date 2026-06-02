"""Supervisor fan-out cap / skip-answered / dedup tests (deterministic).

These exercise the graph-level selection wrapper `select_research_issues`, which
sits on top of `brains.supervisor.select` and enforces the P2 acceleration
budget: top-K highest-impact OPEN issues, never re-research answered issues, and
dedup identical research queries within a run.
"""
from __future__ import annotations

import os

from cn5_research_cos.artifacts import issue_map
from cn5_research_cos.brains import build_brains
from cn5_research_cos.graph import DEFAULT_MAX_RESEARCH_PER_ITER, select_research_issues
from cn5_research_cos.models import IssueStatus, IssueType, ResearchState


def _state_with_issues(specs) -> ResearchState:
    """specs: list of (title, impact, status)."""
    rs = ResearchState(run_id="r", original_question="q")
    for title, impact, status in specs:
        issue_map.add(rs, title=title, description=title,
                      issue_type=IssueType.technical, status=status, now="t",
                      impact=impact, confidence=1)
    return rs


def test_selects_at_most_k_by_impact():
    rs = _state_with_issues([
        ("low", 1, IssueStatus.open),
        ("high", 5, IssueStatus.open),
        ("mid", 3, IssueStatus.open),
        ("highest", 5, IssueStatus.open),
        ("lowest", 0, IssueStatus.open),
    ])
    brains = build_brains("mock")
    selected = select_research_issues(rs, brains, k=3)
    assert len(selected) == 3
    # ordered by impact descending; the two impact-5 first, then impact-3
    titles = [rs.issue_map[i].title for i in selected]
    assert set(titles[:2]) == {"high", "highest"}
    assert titles[2] == "mid"
    # the impact-0/1 issues were dropped by the cap
    assert "low" not in titles and "lowest" not in titles


def test_excludes_answered_and_blocked():
    rs = _state_with_issues([
        ("done", 5, IssueStatus.answered),
        ("open1", 4, IssueStatus.open),
        ("blocked", 5, IssueStatus.blocked_by_human),
        ("open2", 3, IssueStatus.open),
    ])
    brains = build_brains("mock")
    selected = select_research_issues(rs, brains, k=5)
    titles = [rs.issue_map[i].title for i in selected]
    assert "done" not in titles
    assert "blocked" not in titles
    assert set(titles) == {"open1", "open2"}


def test_dedup_identical_queries_within_run():
    rs = _state_with_issues([
        ("Same query", 5, IssueStatus.open),
        ("Other", 4, IssueStatus.open),
    ])
    brains = build_brains("mock")
    first = select_research_issues(rs, brains, k=3)
    assert {rs.issue_map[i].title for i in first} == {"Same query", "Other"}
    # second pass: both titles already researched this run -> dedup'd out
    second = select_research_issues(rs, brains, k=3)
    assert second == []


def test_k_defaults_from_env(monkeypatch):
    monkeypatch.setenv("CN5_COS_MAX_RESEARCH_PER_ITER", "2")
    rs = _state_with_issues([
        ("a", 5, IssueStatus.open),
        ("b", 4, IssueStatus.open),
        ("c", 3, IssueStatus.open),
    ])
    brains = build_brains("mock")
    selected = select_research_issues(rs, brains)  # k=None -> read env
    assert len(selected) == 2


def test_default_k_is_three():
    assert DEFAULT_MAX_RESEARCH_PER_ITER == 3
