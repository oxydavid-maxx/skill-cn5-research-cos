"""Component 3 — tiered citation policy + flatten-to-primary (deterministic, no LLM).

Tiered escalation for an UNVERIFIED web claim:
  1. mark unverified (never emitted as fact);
  2. AUTO re-verify (loop re-researches that issue);
  3. still-unverified AND decision-critical -> escalate to HUMAN (P3 gate);
  4. still-unverified AND non-critical -> flag + lower confidence + coverage_gap;
     the emission gate refuses a memo whose KEY claims are unverified.

Flatten-to-primary: a claim's citation must resolve to a PRIMARY Source, never a
sibling worker's digest/compress output — reject/re-point a claim citing a digest.
"""
from __future__ import annotations

from cn5_research_cos.citation import policy, verify
from cn5_research_cos.models import (CitationStatus, Claim, Decision, Source,
                                     VerifyResult)


def _unverified(critical=False, conf=3):
    return VerifyResult(claim="c", origin="web", verified=False, method="difflib",
                        quote="q", source_refs=["S-1"], status=CitationStatus.unverified)


# --------------------------------------------------------------------------- #
# tier 1 + 2: unverified -> reverify
# --------------------------------------------------------------------------- #
def test_unverified_noncritical_first_pass_requests_reverify():
    res = _unverified()
    action = policy.classify(res, critical=False, reverify_attempted=False)
    assert action.kind == "reverify"
    assert action.status == CitationStatus.unverified


def test_unverified_critical_after_reverify_escalates_to_human():
    res = _unverified()
    action = policy.classify(res, critical=True, reverify_attempted=True)
    assert action.kind == "escalate_human"
    assert action.status == CitationStatus.escalated


def test_unverified_noncritical_after_reverify_flags_and_lowers_confidence():
    res = _unverified()
    action = policy.classify(res, critical=False, reverify_attempted=True)
    assert action.kind == "flag"
    assert action.status == CitationStatus.flagged
    assert action.lower_confidence is True
    assert action.coverage_gap                       # a gap is recorded


def test_verified_claim_needs_no_action():
    res = VerifyResult(claim="c", origin="web", verified=True, method="difflib",
                       status=CitationStatus.verified)
    action = policy.classify(res, critical=True, reverify_attempted=True)
    assert action.kind == "ok"


def test_internal_claim_needs_no_action():
    res = VerifyResult(claim="c", origin="internal", verified=True,
                       method="paperwork", status=CitationStatus.verified)
    action = policy.classify(res, critical=True, reverify_attempted=True)
    assert action.kind == "ok"


# --------------------------------------------------------------------------- #
# escalation routes to a P3 human gate decision
# --------------------------------------------------------------------------- #
def test_escalation_maps_to_human_pull_decision():
    res = _unverified()
    action = policy.classify(res, critical=True, reverify_attempted=True)
    assert policy.to_decision(action) == Decision.pull_human


def test_flag_does_not_force_a_human_decision():
    res = _unverified()
    action = policy.classify(res, critical=False, reverify_attempted=True)
    assert policy.to_decision(action) is None


# --------------------------------------------------------------------------- #
# emission gate: refuse a memo with unverified KEY claims
# --------------------------------------------------------------------------- #
def test_emission_refused_when_key_claim_unverified():
    results = [
        VerifyResult(claim="key", origin="web", verified=False, method="difflib",
                     status=CitationStatus.unverified),
    ]
    # the one unverified claim is KEY (critical) -> refuse synthesize/terminal
    assert policy.emission_blocked(results, key_claims={"key"})
    assert policy.gate_emission(results, Decision.synthesize, key_claims={"key"}) \
        == Decision.continue_research


def test_emission_allowed_when_unverified_claim_is_not_key():
    results = [
        VerifyResult(claim="minor", origin="web", verified=False, method="difflib",
                     status=CitationStatus.unverified),
    ]
    assert not policy.emission_blocked(results, key_claims={"other"})
    assert policy.gate_emission(results, Decision.synthesize, key_claims={"other"}) \
        == Decision.synthesize


def test_emission_passthrough_for_non_emission_decision():
    results = [VerifyResult(claim="k", origin="web", verified=False, method="difflib")]
    assert policy.gate_emission(results, Decision.continue_research,
                                key_claims={"k"}) == Decision.continue_research


# --------------------------------------------------------------------------- #
# flatten-to-primary
# --------------------------------------------------------------------------- #
def _primary():
    return Source(id="S-1", title="primary", origin="web")


def _digest():
    # a digest/compress output masquerading as a source (marked via title/id
    # convention: a compress bundle id or a "digest" role).
    return Source(id="DIGEST-1", title="worker digest", origin="web")


def test_is_digest_detects_digest_source():
    assert policy.is_digest(_digest())
    assert not policy.is_digest(_primary())


def test_flatten_rejects_claim_citing_a_digest():
    sources = {"S-1": _primary(), "DIGEST-1": _digest()}
    claim = Claim(claim="c", source_refs=["DIGEST-1"])
    ok, repointed = policy.flatten_to_primary(claim, sources)
    assert ok is False                      # cites a digest -> rejected
    assert "DIGEST-1" not in repointed      # the digest ref is stripped


def test_flatten_accepts_claim_citing_primary():
    sources = {"S-1": _primary()}
    claim = Claim(claim="c", source_refs=["S-1"])
    ok, repointed = policy.flatten_to_primary(claim, sources)
    assert ok is True
    assert repointed == ["S-1"]


def test_flatten_mixed_keeps_only_primary_refs():
    sources = {"S-1": _primary(), "DIGEST-1": _digest()}
    claim = Claim(claim="c", source_refs=["S-1", "DIGEST-1"])
    ok, repointed = policy.flatten_to_primary(claim, sources)
    # at least one primary remains -> acceptable, but the digest ref is removed
    assert ok is True
    assert repointed == ["S-1"]
