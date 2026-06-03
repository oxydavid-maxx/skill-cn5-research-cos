"""LIVE opt-in test for the REAL external Albert (P6 Task 5).

Gated by BOTH ``CN5_COS_LLM_TESTS=1`` (the live gate, mirrors the suite) AND a
discoverable ``ALBERT_HOME`` (env set or the sibling skill-cn5-i-am-albert
checkout present). Skips cleanly otherwise so CI without Albert stays green, and
collects without error.

Why this test is REQUIRED (mocked tests are not sufficient): a live-only
subprocess / encoding / --json-out path-shape / contract-drift bug passes the
mocked adapter tests — only running the REAL Albert FSM and mapping its real
``albert_challenge.json`` catches it. This is the closed-loop the P4b convergence
engine was built for, now driven by the real reviewer.

The controller runs this (real Albert is 5+ min at --quick); the dev suite skips.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cn5_research_cos.albert.locate import find_albert_home
from cn5_research_cos.albert.real_adapter import RealAlbert
from cn5_research_cos.artifacts import challenge_map
from cn5_research_cos.decision import convergence
from cn5_research_cos.models import (AuditResult, ChallengeStatus, ResearchState)

_LLM = os.environ.get("CN5_COS_LLM_TESTS") == "1"
_HOME = find_albert_home()

pytestmark = pytest.mark.skipif(
    not (_LLM and _HOME is not None),
    reason="set CN5_COS_LLM_TESTS=1 AND a discoverable ALBERT_HOME to run",
)


def _seed_state(tmp_path: Path) -> ResearchState:
    rs = ResearchState(
        run_id="albert-live",
        original_question="該不該自建一個 BU 專屬的 AI 研究助手？市場上已有競品。",
    )
    rs.research_brief = (
        "提案：BU 自建 AI 研究助手。市場已有競品，BU 有戰略意圖與預算，"
        "但技術複雜度、市場時機、內部資料優勢、執行風險尚未釐清。"
    )
    rs.final_memo = (
        "我們建議自建，因為功能比競品多、價格更好，且可重用既有 IP 趕上時程。"
        "客戶表達強烈興趣，建議直接承諾客戶並進入可行性階段。"
    )
    return rs


def test_real_albert_quick_audit_returns_real_challenges(tmp_path):
    """One real --quick Albert audit -> a valid contract -> AuditResult with REAL
    challenges (not degraded)."""
    rs = _seed_state(tmp_path)
    audit = RealAlbert(work_dir=tmp_path, stage="pre_synthesize").audit(rs)

    assert isinstance(audit, AuditResult)
    # A live --quick run that completed must NOT be degraded; if Albert genuinely
    # failed, the degrade guard fires and we surface that honestly rather than
    # pretending success.
    assert not audit.degraded, (
        "real Albert --quick audit degraded — inspect ALBERT_HOME / run_albert.py"
    )
    assert audit.challenges, "real Albert returned no challenges"
    # The real reviewer attaches its rationale + a verdict.
    assert audit.rationale
    assert audit.verdict is not None


def test_real_albert_convergence_consumes_across_two_rounds(tmp_path):
    """The convergence loop CONSUMES real Albert: round 1 raises challenges into
    the map; round 2 (with a strengthened answer + the prior open challenges fed
    back in) must move at least one challenge forward — resolve, escalate, or be
    tracked by id rather than re-raised as a brand-new duplicate."""
    rs = _seed_state(tmp_path)
    auditor = RealAlbert(work_dir=tmp_path, stage="quick")

    # --- round 1: raise + record into the challenge map (mirrors node_albert_audit)
    a1 = auditor.audit(rs)
    assert not a1.degraded
    for ch in a1.challenges:
        merged = challenge_map.upsert(
            rs, challenge=ch.challenge,
            why_albert_would_ask=ch.why_albert_would_ask or None,
            current_answer=ch.current_answer or None,
            status=ch.status, confidence=ch.confidence or None,
            evidence_refs=list(ch.evidence_refs) or None, issue_id=ch.issue_id,
        )
        if merged.status == ChallengeStatus.answered and merged.evidence_refs:
            merged.status = ChallengeStatus.resolved
    convergence.record_signal(rs)
    round1_open = convergence.open_count(rs)
    round1_total = len(rs.albert_challenge_map)
    assert round1_total > 0

    # --- strengthen the answer (simulate a research round closing a gap) ---
    rs.final_memo = (
        rs.final_memo
        + "\n補充：競品為 NXP S32G3（16nm，量產中）與 Renesas R-Car X5H（3nm，已公告）；"
        "我們的差異化護城河為 X，NXP 18 個月內無法複製，理由為 Y。"
        "客戶已提供 LOI，含 SOP 日期與年量。已指定單一 PL 共同簽署 spec/business/schedule。"
    )

    # --- round 2: feed the prior OPEN challenges back in; consume the result ---
    a2 = auditor.audit(rs)
    assert not a2.degraded
    before_total = len(rs.albert_challenge_map)
    for ch in a2.challenges:
        merged = challenge_map.upsert(
            rs, challenge=ch.challenge,
            why_albert_would_ask=ch.why_albert_would_ask or None,
            current_answer=ch.current_answer or None,
            status=ch.status, confidence=ch.confidence or None,
            evidence_refs=list(ch.evidence_refs) or None, issue_id=ch.issue_id,
        )
        if merged.status == ChallengeStatus.answered and merged.evidence_refs:
            merged.status = ChallengeStatus.resolved
    convergence.record_signal(rs)
    after_total = len(rs.albert_challenge_map)

    # Convergence evidence: the map did NOT simply double (dedup/merge happened OR
    # challenges were resolved/escalated), i.e. round 2 carried the dialogue
    # forward rather than re-raising every challenge as a brand-new entry.
    resolved = convergence.resolved_count(rs)
    escalated = convergence.escalated_count(rs)
    moved_forward = (
        resolved + escalated > 0                       # some challenge closed/handed off
        or after_total < before_total + len(a2.challenges)  # some merged onto a prior id
        or convergence.open_count(rs) < round1_open    # net open count fell
    )
    assert moved_forward, (
        f"no convergence: r1_open={round1_open} r1_total={round1_total} "
        f"before={before_total} after={after_total} resolved={resolved} "
        f"escalated={escalated}"
    )
