"""Task 6 (P5): the P4b citation modules are WIRED into memo assembly.

This closes the documented P4b caveat ("citation built but not in loop"): at memo
assembly every claim is routed through ``citation.verify`` (web -> difflib >= 0.85
against ``Source.excerpt``; internal -> carried), ``citation.policy`` (classify the
unverified KEY claims), and ``citation.flatten_to_primary`` (drop digest refs /
reject a digest-only citation).
"""
from cn5_research_cos.synthesis.memo import assemble_memo, citation_pass
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


# --------------------------------------------------------------------------- #
# P5c: citation_pass end-to-end, deterministic (no LLM). Reproduces the live §22
# failure shape — a SHORT verbatim quote embedded in a LONG source excerpt — and
# proves the verify fix: a genuinely-present quote now passes (citation_pass
# empty => memo can emit), while a fabricated quote still hard-blocks.
# --------------------------------------------------------------------------- #
_LONG_EXCERPT = (
    "According to the MIPI Alliance specification and multiple independent "
    "vendor implementations, the I3C controller assigns each device a dynamic "
    "address during the dynamic address assignment (DAA) procedure before any "
    "data transfer can begin on the bus, which is the behavior the working group "
    "ratified and that downstream silicon teams have shipped in production parts."
)


def test_citation_pass_empty_for_verifiable_web_claim():
    """A KEY web claim whose notes quote IS a verbatim substring of a LONG source
    excerpt verifies -> citation_pass returns EMPTY -> the memo can emit. This is
    the exact case the old full-string-ratio metric wrongly rejected."""
    src = Source(id="S-1", title="MIPI I3C spec", url="http://x", origin="web",
                 excerpt=_LONG_EXCERPT)
    # quote is a short verbatim span inside the long excerpt; claim is a paraphrase.
    claim = Claim(
        claim="I3C performs dynamic address assignment", source_refs=["S-1"],
        confidence=5,
        notes="the I3C controller assigns each device a dynamic address during the dynamic address assignment (DAA) procedure",
    )
    rs = _state_with_bundle(EvidenceBundle(query="q", claims=[claim], sources=[src]))
    assert citation_pass(rs) == []


def test_citation_pass_blocks_fabricated_web_claim():
    """A KEY web claim whose quote is NOT present in the source excerpt stays
    unverified -> citation_pass returns the claim text -> the gate hard-blocks
    emission (correct: over-claims must not ship)."""
    src = Source(id="S-1", title="MIPI I3C spec", url="http://x", origin="web",
                 excerpt=_LONG_EXCERPT)
    claim = Claim(
        claim="I3C doubles the bus clock automatically", source_refs=["S-1"],
        confidence=5,
        notes="the controller automatically doubles the bus clock frequency without any configuration",
    )
    rs = _state_with_bundle(EvidenceBundle(query="q", claims=[claim], sources=[src]))
    assert citation_pass(rs) == ["I3C doubles the bus clock automatically"]


def test_citation_pass_through_real_research_path_verifies():
    """The live-failure reproduction END-TO-END: build the bundle via the REAL
    researcher path (_build_bundle), where the per-claim verbatim `quote` (P5c
    bug #2 fix) lands in notes and the substring verify (bug #1 fix) confirms it
    against a LONG source excerpt. citation_pass must be EMPTY so the memo emits.

    Without the per-claim quote, _quote_of would fall back to the paraphrased
    claim text ("I3C performs dynamic address assignment") which is NOT a verbatim
    substring of the excerpt -> the live run wrongly blocked here."""
    from cn5_research_cos.brains.real import RealResearcher
    raw = {
        "sources": [{
            "title": "MIPI I3C spec", "url": "http://x",
            "source_type": "secondary", "quality": "high", "excerpt": _LONG_EXCERPT,
        }],
        "claims": [{
            "claim": "I3C performs dynamic address assignment",  # paraphrase
            "source_indices": [0], "confidence": 5,
            "quote": "the I3C controller assigns each device a dynamic address during the dynamic address assignment (DAA) procedure",
        }],
    }
    bundle = RealResearcher._build_bundle(raw, "DAA", "I-1")
    rs = _state_with_bundle(bundle)
    assert citation_pass(rs) == []
