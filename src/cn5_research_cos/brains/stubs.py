"""Deterministic stub brains (P1, zero LLM).

The determinism rules here are what make Acceptance Tests 1 & 4 pass:

* IssueExpanderStub seeds root/intent/roi/risk but NEVER competitor, so the
  AuditorStub can detect competitor's absence and force a branch (Test 1).
* AuditorStub: no competitor issue -> REWORK + high premature_end_risk + a
  competitor challenge. Once competitor exists and the loop has saturated
  (iteration_count >= STALE_AFTER), -> EXHAUSTED, low risk (Test 4 stop).
* ResearcherStub returns canned bundles; after STALE_AFTER it returns the
  identical bundle (saturation signal for Test 4).
* ScorerStub is a pure function of counts.
"""
from __future__ import annotations

from ..artifacts import issue_map
from ..models import (AlbertChallenge, AuditResult, AuditVerdict, ChallengeStatus,
                      Claim, Classification, Decision, EvidenceBundle, IssueNode,
                      IssueStatus, IssueType, ReadinessScore, ResearchState, Risk,
                      Source, SourceQuality, SourceType)
from .interfaces import Brains

MAX_CONCURRENT = 4
STALE_AFTER = 3

# Seed set — deliberately excludes IssueType.competitor.
_SEED = [
    ("根本問題：題目要回答什麼？", IssueType.root_question),
    ("提問者真正的意圖是什麼？", IssueType.intent),
    ("ROI / 商業價值如何？", IssueType.roi),
    ("主要風險與假設是什麼？", IssueType.risk),
]


class ClarifyGateStub:
    def check(self, state: ResearchState) -> bool:
        return True  # P1: always clarified; real interrupt is P3.


class BriefWriterStub:
    def write(self, state: ResearchState) -> None:
        state.research_brief = (
            f"目標：回答「{state.original_question}」並通過 Albert 質疑"
        )


class IssueExpanderStub:
    def expand(self, state: ResearchState, now: str) -> list[IssueNode]:
        created: list[IssueNode] = []
        if not state.issue_map:
            for title, itype in _SEED:
                node = issue_map.add(
                    state, title=title, description=title, issue_type=itype,
                    status=IssueStatus.open, now=now,
                    impact=4 if itype in (IssueType.roi, IssueType.root_question) else 3,
                    confidence=1,
                )
                created.append(node)
        return created


class SupervisorStub:
    def select(self, state: ResearchState) -> list[str]:
        ids = [
            n.id for n in state.issue_map.values()
            if n.status != IssueStatus.answered
            and n.status not in (
                IssueStatus.blocked_by_human,
                IssueStatus.blocked_by_internal_data,
                IssueStatus.blocked_by_permission,
                IssueStatus.blocked_by_decision,
            )
        ]
        return ids[:MAX_CONCURRENT]


class ResearcherStub:
    def research(self, state: ResearchState, issue_id: str) -> EvidenceBundle:
        node = state.issue_map.get(issue_id)
        title = node.title if node else issue_id
        saturated = state.iteration_count >= STALE_AFTER
        src = Source(
            id=f"S-{issue_id}", title=f"來源：{title}",
            source_type=SourceType.secondary, quality=SourceQuality.medium,
        )
        claim = Claim(
            claim=f"關於「{title}」的初步結論（stub）",
            source_refs=[src.id], confidence=3 if not saturated else 4,
            notes="canned" if not saturated else "saturated-identical",
        )
        return EvidenceBundle(
            query=title, issue_id=issue_id, claims=[claim], sources=[src],
            missing_evidence=[] if saturated else ["更多一手資料"],
            coverage_gaps=[] if saturated else [f"未檢查內部資料：{title}"],
        )


class SourceCriticStub:
    def review(self, bundle: EvidenceBundle) -> EvidenceBundle:
        return bundle  # passthrough (P1)


class CompressorStub:
    def compress(self, bundle: EvidenceBundle) -> EvidenceBundle:
        summary = f"摘要：{bundle.query} → {len(bundle.claims)} 條 claim"
        if summary not in bundle.suggested_followups:
            bundle.suggested_followups.append(summary)
        return bundle


class SkepticStub:
    def counter(self, state: ResearchState, bundle: EvidenceBundle) -> list[str]:
        return ["替代解釋（stub）：結論可能受 marketing bias 影響"]


class AuditorStub:
    def audit(self, state: ResearchState) -> AuditResult:
        if not issue_map.has_type(state, IssueType.competitor):
            ch = AlbertChallenge(
                id="C-AUDIT",
                challenge="競品是否已有此能力?",
                why_albert_would_ask="Albert 一定會問競品比較",
                status=ChallengeStatus.open,
                classification=Classification.addressable,
            )
            return AuditResult(
                verdict=AuditVerdict.rework,
                challenges=[ch],
                premature_end_risk=Risk.high,
                research_drift_risk=Risk.low,
                recommended_next_action=Decision.branch,
                rationale="尚未涵蓋競品角度，Albert 會挑戰；必須先補上。",
                questions_albert_would_ask_next=["競品是否已有此能力?"],
                recommended_next_probe="competitor",
            )
        if state.iteration_count >= STALE_AFTER:
            return AuditResult(
                verdict=AuditVerdict.exhausted,
                premature_end_risk=Risk.low,
                research_drift_risk=Risk.low,
                recommended_next_action=Decision.synthesize,
                rationale="可定址問題已研究飽和，剩餘為人類/內部資料瓶頸。",
            )
        return AuditResult(
            verdict=AuditVerdict.continue_,
            premature_end_risk=Risk.med,
            research_drift_risk=Risk.low,
            recommended_next_action=Decision.continue_research,
            rationale="競品已涵蓋，但研究尚未飽和，繼續。",
        )


class ScorerStub:
    def score(self, state: ResearchState) -> ReadinessScore:
        total = len(state.issue_map) or 1
        answered = sum(
            1 for n in state.issue_map.values()
            if n.status == IssueStatus.answered
        )
        # research exhaustion grows with answered ratio
        exhaustion = min(5, round(5 * answered / total))
        # albert readiness is high only once competitor is covered
        albert = 4 if issue_map.has_type(state, IssueType.competitor) else 1
        decision = min(5, exhaustion + (1 if albert >= 4 else 0))
        # human bottleneck clarity: high once residual blockers are explicit
        residual = any(
            n.status in (
                IssueStatus.blocked_by_human,
                IssueStatus.blocked_by_internal_data,
                IssueStatus.blocked_by_permission,
                IssueStatus.blocked_by_decision,
            )
            for n in state.issue_map.values()
        )
        human = 5 if residual else (4 if exhaustion >= 4 else 2)
        scores = [albert, decision, exhaustion, human]
        should_continue = min(scores) < 4
        return ReadinessScore(
            albert_challenge_readiness=albert,
            decision_readiness=decision,
            research_exhaustion_readiness=exhaustion,
            human_bottleneck_clarity=human,
            should_continue=should_continue,
            reason="stub 計分：依已答比例 + 競品涵蓋 + 殘餘瓶頸明確度",
        )


def build_mock_brains() -> Brains:
    """The P1 deterministic stub bundle (zero LLM)."""
    return Brains(
        clarify_gate=ClarifyGateStub(),
        brief_writer=BriefWriterStub(),
        issue_expander=IssueExpanderStub(),
        supervisor=SupervisorStub(),
        researcher=ResearcherStub(),
        source_critic=SourceCriticStub(),
        compressor=CompressorStub(),
        skeptic=SkepticStub(),
        auditor=AuditorStub(),
        scorer=ScorerStub(),
    )


def build_brains(llm: str = "mock") -> Brains:
    """Brain-bundle factory (injection hook).

    - ``"mock"`` -> P1 deterministic stubs (the 33 tests stay green).
    - ``"real"`` -> P2b real cheap-LLM narrow brains + Albert simulator.

    The graph topology + all loop/COS control are identical for both; only the
    node implementations differ.
    """
    if llm == "mock":
        return build_mock_brains()
    if llm == "real":
        # Imported lazily so the deterministic 'mock' path never imports the LLM
        # stack (keeps the P1 suite import-light and offline).
        from .real import (RealCompressor, RealIssueExpander, RealResearcher,
                           RealScorer, RealSkeptic, RealSourceCritic)
        from ..albert.simulator import RealAlbertSimulator

        return Brains(
            # control-plane / not-yet-real-in-P2b nodes reuse the deterministic
            # implementations (clarify interrupt = P3; brief = SOT/P2a front-end;
            # supervisor selection is deterministic control, not a brain).
            clarify_gate=ClarifyGateStub(),
            brief_writer=BriefWriterStub(),
            supervisor=SupervisorStub(),
            # real narrow LLM brains:
            issue_expander=RealIssueExpander(),
            researcher=RealResearcher(),
            source_critic=RealSourceCritic(),
            compressor=RealCompressor(),
            skeptic=RealSkeptic(),
            auditor=RealAlbertSimulator(),
            scorer=RealScorer(),
        )
    raise NotImplementedError(
        f"Unknown llm={llm!r}; expected 'mock' or 'real'."
    )
