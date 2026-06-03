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
