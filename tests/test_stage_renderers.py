"""Task 2 (P5b): per-stage render helpers — reasonable-length KEY info, Albert FULL.

The Albert renderer is the debate core: it MUST show EVERY challenge's text + why
+ status + current_answer, plus the verdict + BOTH risks + recommended next action,
with NO truncation / slicing. The other renderers are concise (~3-8 lines) KEY-field
blocks, not raw state dumps. All pure + deterministic.
"""
from __future__ import annotations

from cn5_research_cos.models import (
    AlbertChallenge, AuditResult, AuditVerdict, ChallengeStatus, Decision,
    IssueNode, IssueStatus, IssueType, ReadinessScore, ResearchState, Risk,
)
from cn5_research_cos.observability.reporter import (
    render_albert, render_convergence, render_critique, render_decision,
    render_expand, render_readiness, render_research, render_scope,
)


def _audit_with_three_challenges() -> AuditResult:
    return AuditResult(
        verdict=AuditVerdict.rework,
        premature_end_risk=Risk.high,
        research_drift_risk=Risk.med,
        recommended_next_action=Decision.continue_research,
        rationale="尚有高影響挑戰未解，且有提前收斂風險",
        challenges=[
            AlbertChallenge(
                id="C-1", challenge="競品是否已有同等能力且更便宜？",
                why_albert_would_ask="若競品已內建，這個方案的差異化就站不住",
                current_answer="目前只有間接證據", status=ChallengeStatus.open,
                confidence=5, issue_id="I-3",
            ),
            AlbertChallenge(
                id="C-2", challenge="ROI 模型的客戶數假設是否過於樂觀？",
                why_albert_would_ask="若取客戶數打對折，整個 ROI 由正轉負",
                current_answer="已用保守值重算，仍為正",
                status=ChallengeStatus.resolved, confidence=4, issue_id="I-2",
            ),
            AlbertChallenge(
                id="C-3", challenge="這需要哪些我們沒有的內部資料才能定案？",
                why_albert_would_ask="缺內部成本資料就無法給 BU 拍板的數字",
                current_answer="", status=ChallengeStatus.needs_internal_data,
                confidence=3, issue_id="I-5",
            ),
        ],
    )


def test_render_albert_shows_every_challenge_full():
    audit = _audit_with_three_challenges()
    txt = render_albert(audit)
    # EVERY challenge fully present: text + why + status + current_answer.
    for ch in audit.challenges:
        assert ch.challenge in txt, f"missing challenge text {ch.id}"
        assert ch.why_albert_would_ask in txt, f"missing why for {ch.id}"
        assert ch.status.value in txt, f"missing status for {ch.id}"
        if ch.current_answer:
            assert ch.current_answer in txt, f"missing current_answer for {ch.id}"
    # verdict + both risks + recommended next action present.
    assert audit.verdict.value in txt
    assert "premature" in txt.lower() and audit.premature_end_risk.value in txt
    assert "drift" in txt.lower() and audit.research_drift_risk.value in txt
    assert audit.recommended_next_action.value in txt


def test_render_albert_not_truncated_with_many_challenges():
    """Even with many challenges, NONE is sliced away."""
    audit = AuditResult(
        verdict=AuditVerdict.continue_,
        challenges=[
            AlbertChallenge(id=f"C-{i}", challenge=f"挑戰{i}",
                            why_albert_would_ask=f"理由{i}",
                            status=ChallengeStatus.open, confidence=3)
            for i in range(7)
        ],
    )
    txt = render_albert(audit)
    for i in range(7):
        assert f"挑戰{i}" in txt
        assert f"理由{i}" in txt


def test_render_albert_handles_no_challenges():
    audit = AuditResult(verdict=AuditVerdict.exhausted)
    txt = render_albert(audit)
    assert audit.verdict.value in txt  # still shows verdict + risks


def test_render_readiness_shows_four_scores_and_reason():
    score = ReadinessScore(
        albert_challenge_readiness=3, decision_readiness=4,
        research_exhaustion_readiness=2, human_bottleneck_clarity=5,
        should_continue=True, reason="尚有一個高影響挑戰未解",
    )
    txt = render_readiness(score)
    assert "3" in txt and "4" in txt and "2" in txt and "5" in txt
    assert "尚有一個高影響挑戰未解" in txt
    assert "True" in txt or "continue" in txt.lower()


def test_render_convergence_shows_resolved_and_open_counts():
    rs = ResearchState(run_id="r", original_question="q")
    rs.albert_challenge_map = {
        "C-1": AlbertChallenge(id="C-1", challenge="a", status=ChallengeStatus.resolved, confidence=4),
        "C-2": AlbertChallenge(id="C-2", challenge="b", status=ChallengeStatus.open, confidence=5),
        "C-3": AlbertChallenge(id="C-3", challenge="c", status=ChallengeStatus.open, confidence=3),
    }
    txt = render_convergence(rs)
    # resolved 1 / open 2
    assert "1" in txt and "2" in txt
    assert "resolved" in txt.lower() or "已解" in txt
    assert "open" in txt.lower() or "未解" in txt


def test_render_scope_concise():
    rs = ResearchState(run_id="r", original_question="我們該不該做隔夜研究 agent？")
    rs.research_brief = "north star: 讓 BU head 能在戰情室拍板"
    txt = render_scope(rs)
    assert "隔夜研究 agent" in txt
    # concise: not a giant dump
    assert len(txt.splitlines()) <= 8


def test_render_expand_shows_issue_count_and_titles():
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map = {
        "I-1": IssueNode(id="I-1", title="競品能力", description="d",
                         issue_type=IssueType.competitor, status=IssueStatus.open,
                         impact=4, confidence=2),
        "I-2": IssueNode(id="I-2", title="ROI 模型", description="d",
                         issue_type=IssueType.roi, status=IssueStatus.open,
                         impact=5, confidence=1),
    }
    txt = render_expand(rs)
    assert "2" in txt  # issue count
    assert "競品能力" in txt and "ROI 模型" in txt


def test_render_research_shows_finding_per_issue():
    from cn5_research_cos.models import Claim, EvidenceBundle, Source
    rs = ResearchState(run_id="r", original_question="q")
    rs.evidence = [
        EvidenceBundle(
            query="競品能力", issue_id="I-1",
            claims=[Claim(claim="競品 A 尚無此功能", source_refs=["S-1"], confidence=3)],
            sources=[Source(id="S-1", title="某分析報告", url="http://x")],
        ),
    ]
    txt = render_research(rs)
    assert "競品能力" in txt
    assert "競品 A 尚無此功能" in txt


def test_render_critique_shows_challenges_raised():
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map = {
        "I-1": IssueNode(id="I-1", title="t", description="d",
                         issue_type=IssueType.risk, status=IssueStatus.open,
                         impact=3, confidence=2,
                         counterarguments=["但樣本數太小", "來源偏行銷"]),
    }
    txt = render_critique(rs)
    assert "但樣本數太小" in txt or "來源偏行銷" in txt


def test_render_decision_shows_action_and_rationale():
    txt = render_decision(Decision.continue_research, "仍有高價值方向")
    assert "continue_research" in txt
    assert "仍有高價值方向" in txt
