"""Citation verify — SPLIT by source origin (P4b Component 3, deterministic, no LLM).

WEB claims (origin == "web"): OUR net-new verbatim verify — the claim's verbatim
quote (carried in ``Claim.notes``) must appear in the cited web source text via
stdlib ``difflib`` ratio >= ``MATCH_THRESHOLD`` (0.85). Neither GPTR nor ODR does
claim->source verification (both are prompt-only), so this is our design.

INTERNAL claims (origin == "internal"): DO NOT re-run difflib. The verbatim quote
+ resolvable ``[[ref-id, §N]]`` citation already came from the P4a paperwork path
(``collect_section_evidence`` quotes, gated by paperwork's quality-gate) and are
paperwork-verified by construction. We CARRY the quote + ref through unchanged.

Routing is by the cited Source's ``origin`` field. A claim whose cited sources are
mixed/unknown is treated as web (the conservative default: it gets difflib-checked).
"""
from __future__ import annotations

import difflib

from ..models import (Claim, CitationStatus, Source, VerifyResult)

# difflib ratio at/above which a web quote is considered present in the source.
MATCH_THRESHOLD = 0.85


def _best_ratio(quote: str, text: str) -> float:
    """Highest difflib ratio of ``quote`` against any contiguous window of
    ``text`` the length of the quote (so a short quote inside a long source still
    scores high). Falls back to the whole-text ratio for short text."""
    q = quote.strip().lower()
    t = (text or "").lower()
    if not q or not t:
        return 0.0
    if len(t) <= len(q):
        return difflib.SequenceMatcher(None, q, t).ratio()
    # slide a window of the quote's length across the text (step keeps it cheap)
    # so a short quote embedded in a long source still scores high.
    best = 0.0
    step = max(1, len(q) // 4)
    for i in range(0, len(t) - len(q) + 1, step):
        window = t[i: i + len(q)]
        r = difflib.SequenceMatcher(None, q, window).ratio()
        if r > best:
            best = r
            if best >= 0.999:
                break
    return best


def quote_matches(quote: str, source_text: str) -> bool:
    """True iff ``quote`` appears in ``source_text`` at difflib ratio >= 0.85."""
    if not quote or not source_text:
        return False
    return _best_ratio(quote, source_text) >= MATCH_THRESHOLD


def _origin_of(claim: Claim, sources: dict[str, Source]) -> str:
    """The origin governing this claim: 'internal' iff EVERY cited source is
    internal (and at least one ref resolves); otherwise 'web' (the conservative
    default — any web/unknown ref means we run our own verify)."""
    refs = [sources.get(r) for r in claim.source_refs]
    resolved = [s for s in refs if s is not None]
    if resolved and all(s.origin == "internal" for s in resolved):
        return "internal"
    return "web"


def _quote_of(claim: Claim) -> str:
    """The verbatim quote to verify = the claim's notes (paperwork + researcher
    both stash the verbatim quote there); fall back to the claim text."""
    return (claim.notes or claim.claim or "").strip()


def verify_claim(claim: Claim, sources: dict[str, Source],
                 source_texts: dict[str, str]) -> VerifyResult:
    """Route a claim by its cited-source origin and return a VerifyResult."""
    origin = _origin_of(claim, sources)
    quote = _quote_of(claim)

    if origin == "internal":
        # Paperwork-verified by construction — carry, NEVER re-run difflib.
        return VerifyResult(
            claim=claim.claim, origin="internal", verified=True,
            method="paperwork", quote=quote, source_refs=list(claim.source_refs),
            ratio=1.0, status=CitationStatus.verified,
            reason="internal: paperwork-verified verbatim quote + [[ref]] carried",
        )

    # web: our difflib verbatim verify against the cited source text(s).
    best = 0.0
    for ref in claim.source_refs:
        text = source_texts.get(ref, "")
        if text:
            r = _best_ratio(quote, text)
            if r > best:
                best = r
    verified = best >= MATCH_THRESHOLD
    return VerifyResult(
        claim=claim.claim, origin="web", verified=verified, method="difflib",
        quote=quote, source_refs=list(claim.source_refs), ratio=round(best, 3),
        status=CitationStatus.verified if verified else CitationStatus.unverified,
        reason=("web: quote found in source (difflib >= 0.85)" if verified
                else "web: quote NOT found in cited source (difflib < 0.85)"),
    )


def verify_claims(claims: list[Claim], sources: dict[str, Source],
                  source_texts: dict[str, str]) -> list[VerifyResult]:
    return [verify_claim(c, sources, source_texts) for c in claims]
