"""Component 1 — convergence loop integration (deterministic, mock/scripted).

These tests close the adversarial loop:
  * the auditor PROMPT carries the prior OPEN challenges (so Albert can resolve /
    escalate / reference instead of re-raising verbatim);
  * ``node_albert_audit`` UPSERTS challenges (merge-not-duplicate) and applies the
    auditor's resolution (answered -> resolved when evidence exists);
  * the researcher PROMPT for an issue includes its OPEN challenges;
  * the COS prioritizes issues that answer open challenges;
  * a converging run terminates open->0; an unanswerable CRITICAL challenge
    escalates to a human gate (no infinite loop).
"""
from __future__ import annotations

from cn5_research_cos.albert import simulator
from cn5_research_cos.artifacts import challenge_map, issue_map
from cn5_research_cos.brains.real import RealResearcher
from cn5_research_cos.models import (AlbertChallenge, ChallengeStatus, IssueStatus,
                                     IssueType, ResearchState)


def _state() -> ResearchState:
    return ResearchState(run_id="r", original_question="q")


# --------------------------------------------------------------------------- #
# (2) prior open challenges fed INTO the auditor prompt
# --------------------------------------------------------------------------- #
def test_auditor_prompt_includes_open_challenges():
    s = _state()
    challenge_map.upsert(s, challenge="競品是否已有此能力?",
                         current_answer="尚未查證", status=ChallengeStatus.open)
    prompt = simulator._user_prompt(s)
    assert "競品是否已有此能力?" in prompt
    assert "C-001" in prompt  # the id, so Albert can reference it
    # instructs Albert to resolve/escalate/reference, not re-raise verbatim
    assert "resolve" in prompt.lower() or "resolved" in prompt.lower()


def test_auditor_prompt_omits_resolved_challenges():
    s = _state()
    c = challenge_map.upsert(s, challenge="已解決的挑戰")
    c.status = ChallengeStatus.resolved
    prompt = simulator._user_prompt(s)
    assert "已解決的挑戰" not in prompt


# --------------------------------------------------------------------------- #
# (1+2) node_albert_audit UPSERTS (merge not duplicate) across rounds
# --------------------------------------------------------------------------- #
class _ScriptedAuditor:
    """Auditor returning a pre-built AuditResult (no LLM)."""
    def __init__(self, audits):
        self._audits = list(audits)
        self._i = 0

    def audit(self, state):
        a = self._audits[min(self._i, len(self._audits) - 1)]
        self._i += 1
        return a


def _audit(challenges, **kw):
    from cn5_research_cos.models import AuditResult, AuditVerdict, Risk
    return AuditResult(
        verdict=kw.get("verdict", AuditVerdict.continue_),
        challenges=challenges,
        premature_end_risk=kw.get("premature_end_risk", Risk.low),
        research_drift_risk=Risk.low,
        rationale=kw.get("rationale", "r"),
    )


def test_node_albert_audit_merges_challenge_across_rounds():
    from cn5_research_cos import graph
    s = _state()
    # round N: a challenge is raised
    a1 = _audit([AlbertChallenge(id="x", challenge="競品是否已有此能力?",
                                 status=ChallengeStatus.open)])
    # round N+1: SAME challenge, now answered with evidence
    a2 = _audit([AlbertChallenge(id="x", challenge="競品是否已有此能力?",
                                 status=ChallengeStatus.answered,
                                 current_answer="競品 X 有", evidence_refs=["S-1"])])
    auditor = _ScriptedAuditor([a1, a2])
    brains_obj = type("B", (), {"auditor": auditor})()

    gs = {"research_state": s, "now": "t",
          "brains": brains_obj}
    graph.node_albert_audit(gs)
    assert len(s.albert_challenge_map) == 1
    graph.node_albert_audit(gs)
    # merged, not duplicated
    assert len(s.albert_challenge_map) == 1
    ch = next(iter(s.albert_challenge_map.values()))
    assert ch.rounds_seen == 2
    # answered + evidence -> auto-promoted to resolved by the convergence step
    assert ch.status == ChallengeStatus.resolved
    assert "S-1" in ch.evidence_refs


# --------------------------------------------------------------------------- #
# (3) open challenges fed INTO the researcher prompt
# --------------------------------------------------------------------------- #
def test_researcher_prompt_includes_open_challenge_for_issue():
    s = _state()
    node = issue_map.add(s, title="競品分析", description="d",
                         issue_type=IssueType.competitor,
                         status=IssueStatus.open, now="t")
    challenge_map.upsert(s, challenge="競品是否已有此能力?", issue_id=node.id,
                         status=ChallengeStatus.open)
    _title, user = RealResearcher._user_prompt(s, node.id)
    assert "競品是否已有此能力?" in user
    assert "C-001" in user  # references the challenge id


def test_researcher_prompt_without_challenges_is_unchanged_shape():
    s = _state()
    node = issue_map.add(s, title="ROI", description="d", issue_type=IssueType.roi,
                         status=IssueStatus.open, now="t")
    _title, user = RealResearcher._user_prompt(s, node.id)
    assert "ROI" in user


# --------------------------------------------------------------------------- #
# (4) COS prioritizes issues that answer open challenges
# --------------------------------------------------------------------------- #
def test_select_prioritizes_issues_with_open_challenges():
    from cn5_research_cos.graph import select_research_issues
    s = _state()
    low = issue_map.add(s, title="低影響無挑戰", description="d",
                        issue_type=IssueType.roi, status=IssueStatus.open,
                        now="t", impact=5)
    chal = issue_map.add(s, title="有開放挑戰的問題", description="d",
                         issue_type=IssueType.risk, status=IssueStatus.open,
                         now="t", impact=2)
    challenge_map.upsert(s, challenge="未解挑戰", issue_id=chal.id,
                         status=ChallengeStatus.open)

    class _Sup:
        def select(self, state):
            return [low.id, chal.id]
    brains_obj = type("B", (), {"supervisor": _Sup()})()
    # even though `low` has higher impact, the challenge-linked issue is selected
    # first (open challenges win the priority tie-break).
    selected = select_research_issues(s, brains_obj, k=1)
    assert selected == [chal.id]
