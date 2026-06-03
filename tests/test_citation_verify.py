"""Component 3 — citation verify, SPLIT by source origin (deterministic, no LLM).

* origin == "web": OUR verbatim verify — the claim's quote must appear in the
  cited web source text via stdlib difflib ratio >= 0.85. Net-new (neither GPTR
  nor ODR does claim->source verification; both are prompt-only).
* origin == "internal": DO NOT re-run difflib — the verbatim quote + [[ref-id,§N]]
  came from the P4a paperwork path and is paperwork-verified by construction. We
  carry it through (asserted via a spy: NO difflib call for internal claims).
"""
from __future__ import annotations

from cn5_research_cos.citation import verify
from cn5_research_cos.models import Claim, Source


# --------------------------------------------------------------------------- #
# difflib 0.85 boundary (web)
# --------------------------------------------------------------------------- #
def test_quote_exact_match_verifies():
    text = "The I2C bus supports clock stretching for slow peripherals."
    assert verify.quote_matches("The I2C bus supports clock stretching", text)


def test_quote_paraphrase_below_threshold_fails():
    text = "The I2C bus supports clock stretching for slow peripherals."
    # a paraphrase that shares few contiguous chars -> below 0.85
    assert not verify.quote_matches("Clocks can be slowed by devices on the wire", text)


def test_quote_near_match_at_threshold():
    text = "Backward compatibility is preserved across all I2C speed grades here."
    # near-identical (one trailing word differs) -> >= 0.85
    assert verify.quote_matches(
        "Backward compatibility is preserved across all I2C speed grades",
        text,
    )


def test_quote_empty_does_not_match():
    assert not verify.quote_matches("", "some source text")
    assert not verify.quote_matches("a quote", "")


# --------------------------------------------------------------------------- #
# substring / partial-match metric (P5c fix): verify = "is the quote (near-)
# PRESENT in the source text", measured as quote-COVERAGE of the longest
# contiguous match — NOT the full-string difflib ratio (which penalizes a short
# verbatim quote embedded in a much longer source).
# --------------------------------------------------------------------------- #
def test_short_quote_inside_long_source_verifies():
    """A short verbatim quote that IS a contiguous substring of a much longer
    source text must verify. This FAILS under a full-string ratio (the length
    mismatch drags the ratio far below 0.85) and under autojunk-on longest-match
    on long text (common chars get junked)."""
    quote = "reduces total cost of ownership by roughly thirty percent over three years"
    text = (
        "According to the vendor whitepaper and several independent case studies, "
        "the platform reduces total cost of ownership by roughly thirty percent "
        "over three years when compared with the legacy on-premise stack that most "
        "enterprises currently operate today, which is a substantial saving."
    )
    assert verify.quote_matches(quote, text)


def test_quote_with_one_char_typo_still_verifies():
    """A quote with a single-character typo still covers >= 85% of itself as a
    contiguous run, so it verifies (robust to minor transcription noise)."""
    text = (
        "Industry surveys consistently report that container adoption is the most "
        "widely deployed approach in production environments today, far ahead of "
        "every documented alternative across the surveyed organizations."
    )
    quote = "container adoption is the most widly deployed approach in production environments"
    assert verify.quote_matches(quote, text)


def test_fabricated_quote_not_in_source_fails():
    """A fabricated quote that is NOT present in the source must still fail —
    the substring metric must not over-accept."""
    text = (
        "According to the vendor whitepaper and several independent case studies, "
        "the platform reduces total cost of ownership by roughly thirty percent "
        "over three years when compared with the legacy on-premise stack."
    )
    fabricated = "the system automatically triples revenue within the first fiscal quarter"
    assert not verify.quote_matches(fabricated, text)


# --------------------------------------------------------------------------- #
# origin routing
# --------------------------------------------------------------------------- #
def _web_claim():
    return Claim(claim="I2C supports clock stretching",
                 source_refs=["S-web"], notes="The I2C bus supports clock stretching")


def _internal_claim():
    return Claim(claim="Reg 0x40 is the config register",
                 source_refs=["S-int"], notes="Reg 0x40 is the config register [[D1,§4]]")


def test_web_claim_verified_by_difflib():
    sources = {
        "S-web": Source(id="S-web", title="t",
                        url="https://x", origin="web"),
    }
    source_texts = {"S-web": "The I2C bus supports clock stretching for slow peripherals."}
    res = verify.verify_claim(_web_claim(), sources, source_texts)
    assert res.verified is True
    assert res.origin == "web"
    assert res.method == "difflib"


def test_web_claim_unverified_when_quote_absent():
    sources = {"S-web": Source(id="S-web", title="t", origin="web")}
    source_texts = {"S-web": "Totally unrelated content about cooking recipes."}
    res = verify.verify_claim(_web_claim(), sources, source_texts)
    assert res.verified is False
    assert res.origin == "web"


def test_internal_claim_carried_without_difflib(monkeypatch):
    """An internal claim is paperwork-verified: it is carried as verified WITHOUT
    running difflib. Spy on the difflib entrypoint to prove it is NOT called."""
    calls = {"n": 0}
    real = verify.quote_matches

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(verify, "quote_matches", spy)

    sources = {"S-int": Source(id="S-int", title="t", origin="internal")}
    res = verify.verify_claim(_internal_claim(), sources, source_texts={})
    assert res.verified is True
    assert res.origin == "internal"
    assert res.method == "paperwork"
    # the carried quote + [[ref]] are preserved
    assert "[[D1,§4]]" in res.quote
    assert calls["n"] == 0, "difflib must NOT run for internal-origin claims"


def test_web_claim_with_no_source_text_is_unverified():
    sources = {"S-web": Source(id="S-web", title="t", origin="web")}
    res = verify.verify_claim(_web_claim(), sources, source_texts={})
    assert res.verified is False


def test_verify_bundle_routes_each_claim(monkeypatch):
    """A mixed bundle: web claim difflib-verified, internal claim carried."""
    sources = {
        "S-web": Source(id="S-web", title="t", origin="web"),
        "S-int": Source(id="S-int", title="t", origin="internal"),
    }
    source_texts = {"S-web": "The I2C bus supports clock stretching for slow peripherals."}
    results = verify.verify_claims([_web_claim(), _internal_claim()],
                                   sources, source_texts)
    assert results[0].origin == "web" and results[0].method == "difflib"
    assert results[1].origin == "internal" and results[1].method == "paperwork"
