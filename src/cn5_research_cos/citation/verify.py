"""Citation verify — SPLIT by source origin (P4b Component 3, deterministic, no LLM).

WEB claims (origin == "web"): OUR net-new verbatim verify — the claim's verbatim
quote (carried in ``Claim.notes``) must be (near-)PRESENT in the cited web source
text, measured as quote-COVERAGE: the longest contiguous ``difflib`` match must
cover >= ``MATCH_THRESHOLD`` (0.85) of the QUOTE (substring/partial match, NOT a
full-string ratio — a short verbatim quote inside a long source must still pass).
Neither GPTR nor ODR does claim->source verification (both are prompt-only).

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

# quote-coverage at/above which a web quote is considered present in the source
# (fraction of the QUOTE matched as a contiguous run in the source text).
MATCH_THRESHOLD = 0.85


def _quote_coverage(quote: str, text: str) -> float:
    """How much of ``quote`` is (near-)PRESENT in ``text`` — a partial-ratio
    over the best-aligning window of ``text``, NOT a full-string similarity.

    A short verbatim quote embedded in a much longer source must score high. A
    full-string ``difflib.ratio()`` answers "are the two strings similar in their
    entirety" and wrongly penalizes a short quote inside a long source
    (ratio = 2*M/(len(quote)+len(text)) → small when text >> quote). Instead we
    anchor on each contiguous match of the quote in the text, carve out the
    ``len(quote)``-sized window of the source that the quote would align to, and
    take the best full ``ratio()`` over those windows (the classic "partial
    ratio"). This tolerates minor transcription noise (e.g. a 1-char typo splits
    the run but the windowed ratio stays high) while a fabricated quote — which
    only shares scattered short tokens — scores low.

    ``autojunk=False`` is REQUIRED: difflib's autojunk heuristic treats characters
    that recur in >1% of a long (>200 char) sequence as junk and excludes them
    from matches, which silently collapses the match of a genuine substring to
    near zero on paragraph-length sources.
    """
    q = quote.strip().lower()
    t = (text or "").strip().lower()
    if not q or not t:
        return 0.0
    # partial ratio is computed with the SHORTER string as the probe.
    shorter, longer = (q, t) if len(q) <= len(t) else (t, q)
    sm = difflib.SequenceMatcher(None, shorter, longer, autojunk=False)
    best = 0.0
    for block in sm.get_matching_blocks():
        start = max(0, block.b - block.a)
        window = longer[start: start + len(shorter)]
        r = difflib.SequenceMatcher(None, shorter, window, autojunk=False).ratio()
        if r > best:
            best = r
            if best >= 0.999:
                break
    return best


def quote_matches(quote: str, source_text: str) -> bool:
    """True iff ``quote`` is (near-)PRESENT in ``source_text`` — the partial
    ratio over the best-aligning source window covers >= ``MATCH_THRESHOLD``
    (0.85) of the QUOTE. A verbatim or near-verbatim (<=~15% transcription noise)
    quote verifies; a fabricated quote not present in the source does not."""
    if not quote or not source_text:
        return False
    return _quote_coverage(quote, source_text) >= MATCH_THRESHOLD


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

    # web: our verbatim verify — quote-COVERAGE (substring presence) against the
    # cited source text(s), NOT full-string ratio. best = highest fraction of the
    # quote found as a contiguous run in any cited source.
    best = 0.0
    for ref in claim.source_refs:
        text = source_texts.get(ref, "")
        if text:
            r = _quote_coverage(quote, text)
            if r > best:
                best = r
    verified = best >= MATCH_THRESHOLD
    return VerifyResult(
        claim=claim.claim, origin="web", verified=verified, method="difflib",
        quote=quote, source_refs=list(claim.source_refs), ratio=round(best, 3),
        status=CitationStatus.verified if verified else CitationStatus.unverified,
        reason=("web: quote present in source (coverage >= 0.85)" if verified
                else "web: quote NOT present in cited source (coverage < 0.85)"),
    )


def verify_claims(claims: list[Claim], sources: dict[str, Source],
                  source_texts: dict[str, str]) -> list[VerifyResult]:
    return [verify_claim(c, sources, source_texts) for c in claims]
