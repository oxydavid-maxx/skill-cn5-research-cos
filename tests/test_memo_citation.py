"""Task 6 (P5): the P4b citation modules are WIRED into memo assembly.

This closes the documented P4b caveat ("citation built but not in loop"): at memo
assembly every claim is routed through ``citation.verify`` (web -> difflib >= 0.85
against ``Source.excerpt``; internal -> carried), ``citation.policy`` (classify the
unverified KEY claims), and ``citation.flatten_to_primary`` (drop digest refs /
reject a digest-only citation).
"""
from cn5_research_cos.synthesis.memo import assemble_memo
from cn5_research_cos.brains.synthesis import MockSynthesizer
from cn5_research_cos.models import (
    Claim, EvidenceBundle, ResearchState, Source,
)


def _state_with_bundle(bundle: EvidenceBundle) -> ResearchState:
    rs = ResearchState(run_id="r", original_question="q")
    rs.evidence.append(bundle)
    return rs


def test_web_unverified_key_claim_flagged_in_memo():
    # A KEY (high-confidence) web claim whose excerpt does NOT contain its quote.
    src = Source(id="S-1", title="t", url="http://x", origin="web",
                 excerpt="Totally unrelated content about cooking recipes.")
    claim = Claim(claim="DAA assigns dynamic addresses", source_refs=["S-1"],
                  confidence=5, notes="the controller assigns a dynamic address")
    rs = _state_with_bundle(EvidenceBundle(query="q", claims=[claim], sources=[src]))

    memo = assemble_memo(rs, MockSynthesizer())
    assert "DAA assigns dynamic addresses" in memo.unverified_key_claims


def test_web_verified_key_claim_not_flagged():
    src = Source(id="S-1", title="t", url="http://x", origin="web",
                 excerpt="The controller assigns a dynamic address during DAA.")
    claim = Claim(claim="DAA assigns dynamic addresses", source_refs=["S-1"],
                  confidence=5, notes="the controller assigns a dynamic address")
    rs = _state_with_bundle(EvidenceBundle(query="q", claims=[claim], sources=[src]))

    memo = assemble_memo(rs, MockSynthesizer())
    assert memo.unverified_key_claims == []


def test_non_key_unverified_claim_not_blocking():
    # A LOW-confidence unverified web claim is flagged by policy but is NOT a KEY
    # claim, so it does not enter unverified_key_claims (won't block emission).
    src = Source(id="S-1", title="t", url="http://x", origin="web",
                 excerpt="Totally unrelated content.")
    claim = Claim(claim="minor aside", source_refs=["S-1"], confidence=1,
                  notes="some quote not present")
    rs = _state_with_bundle(EvidenceBundle(query="q", claims=[claim], sources=[src]))

    memo = assemble_memo(rs, MockSynthesizer())
    assert memo.unverified_key_claims == []


def test_internal_key_claim_carried_no_difflib():
    src = Source(id="S-int", title="doc", origin="internal")
    claim = Claim(claim="Reg 0x40 is the config register", source_refs=["S-int"],
                  confidence=5, notes="Reg 0x40 is the config register [[D1,§4]]")
    rs = _state_with_bundle(EvidenceBundle(query="q", claims=[claim], sources=[src]))

    memo = assemble_memo(rs, MockSynthesizer())
    # internal is paperwork-verified by construction -> never flagged unverified
    assert memo.unverified_key_claims == []


def test_memo_claim_citing_only_digest_is_flattened():
    # A claim citing ONLY a digest source -> flatten_to_primary rejects it; with no
    # surviving primary ref it cannot be verified, so a KEY such claim is flagged.
    digest = Source(id="DIGEST-1", title="worker summary", origin="web",
                    excerpt="the controller assigns a dynamic address")
    claim = Claim(claim="cites only a digest", source_refs=["DIGEST-1"],
                  confidence=5, notes="the controller assigns a dynamic address")
    rs = _state_with_bundle(EvidenceBundle(query="q", claims=[claim], sources=[digest]))

    memo = assemble_memo(rs, MockSynthesizer())
    # flattened away its only ref -> unverifiable KEY claim -> flagged
    assert "cites only a digest" in memo.unverified_key_claims


def test_claim_with_primary_and_digest_keeps_primary():
    primary = Source(id="S-1", title="MIPI spec", origin="web",
                     excerpt="The controller assigns a dynamic address during DAA.")
    digest = Source(id="DIGEST-1", title="worker summary", origin="web", excerpt="")
    claim = Claim(claim="has a primary too", source_refs=["DIGEST-1", "S-1"],
                  confidence=5, notes="the controller assigns a dynamic address")
    rs = _state_with_bundle(
        EvidenceBundle(query="q", claims=[claim], sources=[primary, digest]))

    memo = assemble_memo(rs, MockSynthesizer())
    # the surviving primary ref carries the verbatim quote -> verified -> not flagged
    assert memo.unverified_key_claims == []
