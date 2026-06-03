"""Phase 5c Task 1 — confidence-based citation routing (cite / drop / notify).

Replaces the old "any unverified KEY claim -> hard-block the whole memo" with the
user's 2026-06-03 policy. Per claim, after the (now-fixed) verbatim verify:

  * verified (coverage >= 0.85) -> CITE (in ``cited``);
  * unverified AND NOT critical -> DROP (in ``dropped``; not cited, NO HumanTask,
    no fabrication — the claim simply is not presented as evidence);
  * unverified AND critical (decision-critical via ``risk.classify_pull`` +
    high-impact owning issue) -> NEEDS SUPPLEMENT (a ``HumanTask`` is created and
    returned in ``needs_supplement``), surfaced in the memo's "What We Cannot Say"
    / "Required Human Decisions" sections, NEVER as verified fact.

The loop NEVER blocks/pauses on this — the memo can STILL emit; unverified-critical
items only appear, clearly flagged, in the cannot-say / required-decisions sections.
This SUPERSEDES the old hard citation block for criticality routing while keeping
the correctness invariant (an unverified-critical claim is never presented as fact).
"""
from __future__ import annotations

from cn5_research_cos.synthesis.memo import (assemble_memo, render_memo,
                                             route_citations)
from cn5_research_cos.synthesis.gates import check_emission
from cn5_research_cos.brains.synthesis import MockSynthesizer
from cn5_research_cos.models import (
    AuditResult, AuditVerdict, Claim, EvidenceBundle, IssueNode, IssueStatus,
    IssueType, ReadinessScore, ResearchState, Risk, Source,
)

_LONG_EXCERPT = (
    "According to the MIPI Alliance specification and multiple independent "
    "vendor implementations, the I3C controller assigns each device a dynamic "
    "address during the dynamic address assignment (DAA) procedure before any "
    "data transfer can begin on the bus."
)


def _critical_state() -> ResearchState:
    """A state whose ``risk.classify_pull`` is HIGH: >=2 high-impact OPEN intent
    issues with no safe fallback. Audit ran clean + readiness met so the only
    thing that could refuse the memo is the citation routing under test."""
    rs = ResearchState(run_id="r", original_question="q")
    rs.fallback_behavior_if_human_unavailable = None  # no safe default
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
    return rs


def _verified_claim() -> tuple[Claim, Source]:
    src = Source(id="S-ok", title="MIPI I3C spec", url="http://x", origin="web",
                 excerpt=_LONG_EXCERPT)
    claim = Claim(
        claim="I3C performs dynamic address assignment", source_refs=["S-ok"],
        confidence=5,
        notes="the I3C controller assigns each device a dynamic address during the dynamic address assignment (DAA) procedure",
    )
    return claim, src


def _unverified_claim(text: str, conf: int, sid: str) -> tuple[Claim, Source]:
    src = Source(id=sid, title="src", url="http://y", origin="web",
                 excerpt="Totally unrelated content about cooking recipes.")
    claim = Claim(claim=text, source_refs=[sid], confidence=conf,
                  notes="a quote that is not present in the source at all")
    return claim, src


def test_unverified_critical_drops_and_flags_not_blocks():
    rs = _critical_state()
    # a low-impact issue carries the verified + the non-critical claim; the
    # high-impact issue (I-1) carries the decision-critical one.
    rs.issue_map["I-low"] = IssueNode(
        id="I-low", title="minor", description="d", issue_type=IssueType.technical,
        status=IssueStatus.open, impact=1, confidence=2)
    claim_v, src_v = _verified_claim()
    claim_minor, src_minor = _unverified_claim("minor aside", 1, "S-min")
    claim_crit, src_crit = _unverified_claim("decision-critical unverified", 5, "S-crit")
    rs.evidence.append(EvidenceBundle(
        query="q", issue_id="I-low",
        claims=[claim_v, claim_minor], sources=[src_v, src_minor]))
    # attach the critical claim to a high-impact issue so it is decision-critical.
    rs.evidence.append(EvidenceBundle(
        query="q", issue_id="I-1", claims=[claim_crit], sources=[src_crit]))

    res = route_citations(rs)

    assert claim_v.claim in [c.claim for c in res.cited]
    assert claim_minor.claim in [c.claim for c in res.dropped]
    assert claim_crit.claim in [t.requested_input for t in res.needs_supplement]
    # a HumanTask was recorded on the state for the critical item
    assert any(claim_crit.claim in t.requested_input for t in rs.human_tasks.values())
    # dropped + cited claims create NO HumanTask
    assert all("minor aside" not in t.requested_input for t in rs.human_tasks.values())


def test_memo_still_emits_with_unverified_critical_surfaced_not_faked():
    rs = _critical_state()
    claim_crit, src_crit = _unverified_claim("decision-critical unverified claim X", 5, "S-crit")
    rs.evidence.append(EvidenceBundle(
        query="q", issue_id="I-1", claims=[claim_crit], sources=[src_crit]))

    memo = assemble_memo(rs, MockSynthesizer())
    gated = check_emission(rs, memo, explicit=False)

    # the memo EMITS (no hard citation block on the unverified-critical item)
    assert gated.emitted is True, f"refused: {gated.refused_reason}"
    # the unverified-critical claim is surfaced (flagged), NOT presented as fact
    assert claim_crit.claim in memo.needs_supplement
    rendered = render_memo(memo)
    assert claim_crit.claim in rendered


def test_unverified_noncritical_dropped_not_in_memo_no_task():
    rs = _critical_state()
    # low-impact owning issue + low confidence -> not critical -> DROP
    rs.issue_map["I-low"] = IssueNode(
        id="I-low", title="minor", description="d", issue_type=IssueType.technical,
        status=IssueStatus.open, impact=1, confidence=2)
    claim_minor, src_minor = _unverified_claim("a non-critical aside", 1, "S-min")
    rs.evidence.append(EvidenceBundle(
        query="q", issue_id="I-low", claims=[claim_minor], sources=[src_minor]))

    res = route_citations(rs)
    assert claim_minor.claim in [c.claim for c in res.dropped]
    assert claim_minor.claim not in [t.requested_input for t in res.needs_supplement]
    memo = assemble_memo(rs, MockSynthesizer())
    assert claim_minor.claim not in memo.needs_supplement


def test_verified_claim_is_cited():
    rs = _critical_state()
    claim_v, src_v = _verified_claim()
    rs.evidence.append(EvidenceBundle(
        query="q", issue_id="I-1", claims=[claim_v], sources=[src_v]))
    res = route_citations(rs)
    assert claim_v.claim in [c.claim for c in res.cited]
    assert claim_v.claim not in [t.requested_input for t in res.needs_supplement]
