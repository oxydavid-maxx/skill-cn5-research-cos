"""Citation policy — tiered escalation + flatten-to-primary (P4b Component 3).

Deterministic (no LLM). Consumes ``VerifyResult``s from ``citation.verify`` and
decides what happens to an UNVERIFIED web claim, per the user's escalation rule:

  1. unverified -> mark unverified (the verify step already did); never a fact.
  2. AUTO re-verify -> the loop re-researches that issue / seeks a corroborating
     PRIMARY source. (kind == "reverify" on the FIRST pass.)
  3. still unverified AND decision-critical -> escalate to a HUMAN (P3 H1/H5
     human_pull). (kind == "escalate_human".)
  4. still unverified AND non-critical -> flag + lower confidence + coverage_gap;
     the emission gate refuses a memo whose KEY claims are unverified.
     (kind == "flag".)

Flatten-to-primary: a claim's citation must resolve to a PRIMARY ``Source``, never
a sibling worker's digest/compress output. A digest ref is stripped; a claim left
with no primary ref is rejected.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import (CitationStatus, Claim, Decision, Source, VerifyResult)

_GATED = {Decision.terminal_stop, Decision.synthesize}

# id prefixes / role tokens that mark a "source" as actually a digest/compress
# output (not a primary source). The compressor writes summaries into
# suggested_followups, not Source objects, but a digest can still leak in via a
# mis-built bundle — flatten-to-primary is the assembly-time guard.
_DIGEST_ID_PREFIXES = ("DIGEST", "COMPRESS", "SUMMARY")
_DIGEST_TITLE_TOKENS = ("digest", "compressed summary", "worker summary")


@dataclass
class PolicyAction:
    """What to do with one verified-or-not claim."""
    kind: str                                  # ok | reverify | escalate_human | flag
    status: CitationStatus
    lower_confidence: bool = False
    coverage_gap: str = ""
    reason: str = ""


def classify(result: VerifyResult, *, critical: bool,
             reverify_attempted: bool) -> PolicyAction:
    """Map a VerifyResult + criticality + whether re-verify already ran -> action.

    A verified claim (web or internal) needs no action. An unverified web claim
    walks the tiered ladder: first pass -> reverify; after reverify -> escalate
    (critical) or flag (non-critical)."""
    if result.verified:
        return PolicyAction(kind="ok", status=CitationStatus.verified,
                            reason="claim verified")

    if not reverify_attempted:
        # tier 2: auto re-verify (re-research this issue for a primary corroborator)
        return PolicyAction(
            kind="reverify", status=CitationStatus.unverified,
            reason="unverified -> auto re-verify (seek a corroborating primary source)",
        )

    if critical:
        # tier 3: decision-critical + still unverified -> human gate
        return PolicyAction(
            kind="escalate_human", status=CitationStatus.escalated,
            reason="critical claim still unverified -> escalate to human (verify/judge)",
        )

    # tier 4: non-critical + still unverified -> flag + lower confidence + gap
    return PolicyAction(
        kind="flag", status=CitationStatus.flagged, lower_confidence=True,
        coverage_gap=f"unverified non-critical claim flagged: {result.claim}",
        reason="non-critical claim unverified -> flag + lower confidence + coverage_gap",
    )


def to_decision(action: PolicyAction) -> Decision | None:
    """Route a policy action to a P3 gate Decision: an escalation -> human pull;
    everything else stays in the loop (None = no forced human decision)."""
    if action.kind == "escalate_human":
        return Decision.pull_human
    return None


# --------------------------------------------------------------------------- #
# emission gate
# --------------------------------------------------------------------------- #
def emission_blocked(results: list[VerifyResult], *, key_claims: set[str]) -> bool:
    """True iff any UNVERIFIED claim is a KEY claim (the memo can't emit a key
    claim that is not citation-verified)."""
    for r in results:
        if not r.verified and r.claim in key_claims:
            return True
    return False


def gate_emission(results: list[VerifyResult], decision: Decision, *,
                  key_claims: set[str]) -> Decision:
    """Refuse a synthesize/terminal emission while a KEY claim is unverified —
    force back to ``continue_research``. Non-emission decisions pass through."""
    if decision not in _GATED:
        return decision
    if emission_blocked(results, key_claims=key_claims):
        return Decision.continue_research
    return decision


# --------------------------------------------------------------------------- #
# flatten-to-primary
# --------------------------------------------------------------------------- #
def is_digest(source: Source) -> bool:
    """True iff this 'source' is actually a digest/compress output, not a primary
    source (detected by id prefix or title token)."""
    sid = (source.id or "").upper()
    if any(sid.startswith(p) for p in _DIGEST_ID_PREFIXES):
        return True
    title = (source.title or "").lower()
    return any(tok in title for tok in _DIGEST_TITLE_TOKENS)


def flatten_to_primary(claim: Claim,
                       sources: dict[str, Source]) -> tuple[bool, list[str]]:
    """Strip any digest refs from a claim's citations; return (ok, repointed_refs).

    ``ok`` is False iff, after stripping digests, the claim has NO primary source
    ref left (it cited ONLY a digest) — such a claim must be rejected/re-researched
    rather than emitted citing a digest. A claim with at least one surviving
    primary ref is accepted with the digest refs removed (flattened to primary).
    """
    repointed: list[str] = []
    for ref in claim.source_refs:
        src = sources.get(ref)
        if src is not None and is_digest(src):
            continue                      # drop the digest ref
        repointed.append(ref)
    ok = len(repointed) > 0
    return ok, repointed
