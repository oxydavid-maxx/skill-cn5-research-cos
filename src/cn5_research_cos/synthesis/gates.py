"""The four §22 emission gates (P5, deterministic, no LLM).

The gates split into two classes (P5b decision — spec "Component 2"):

  * CORRECTNESS gates make the memo itself UNTRUSTWORTHY if violated, so they
    ALWAYS apply — an ``explicit`` emit command can NEVER bypass them:
      1. Degraded-audit gate (spec decision #8): the Albert audit must have
         GENUINELY run — ``state.last_audit`` exists and is not ``degraded`` (a
         degraded/mock audit is not a real adversarial pass).
      3. Citation gate: no UNVERIFIED KEY claim (``memo.unverified_key_claims``
         from the wired-in P4b pipeline) — no fabrication.

  * COMPLETENESS gates mean the research is not yet finished, but the §22 memo is
    a status briefing that DOCUMENTS the open items (in its Albert Challenge Map /
    Blocking / Required-Human-Decisions sections), so emitting on an EXPLICIT
    command with open items is HONEST, not a lie. These are SKIPPED when
    ``explicit=True``:
      2. Convergence gate: REUSE ``convergence.has_unresolved_high_impact`` — no
         unresolved HIGH-impact Albert challenge (an escalated-to-human one is OK;
         the human owns it).
      4. Readiness gate: the readiness TARGET is met (``exhaustion.targets_met``).

Check order is preserved (1 → 2 → 3 → 4); the first failing applicable gate wins
and names itself in ``refused_reason``. A memo emits ONLY when every APPLICABLE
gate passes.

H6 final-review (the human confirm/revise interrupt) is already wired in
``graph.node_human_review`` (P3); the synthesize node builds + gates the memo, then
routes through that EXISTING H6 seam before END (no duplicate gate).
"""
from __future__ import annotations

from ..decision import convergence, exhaustion
from ..models import Memo, ResearchState


def check_emission(state: ResearchState, memo: Memo, *,
                   explicit: bool = False) -> Memo:
    """Apply the four gates in order; set ``memo.emitted`` / ``memo.refused_reason``.

    Returns the SAME ``Memo`` (mutated) for convenience. The first failing gate
    wins; if all pass, ``emitted = True`` and ``refused_reason = None``.
    """
    # Gate 1: degraded / missing audit.
    audit = state.last_audit
    if audit is None:
        memo.emitted = False
        memo.refused_reason = "degraded-audit gate: no Albert audit has run"
        return memo
    if getattr(audit, "degraded", False):
        memo.emitted = False
        memo.refused_reason = "degraded-audit gate: the Albert audit ran degraded/mock"
        return memo

    # Gate 2 (COMPLETENESS): convergence — unresolved high-impact Albert challenge.
    # SKIPPED on an explicit emit command (the §22 memo documents the open
    # challenge in its Albert Challenge Map / Blocking sections, so emitting is
    # honest); ALWAYS applies on the normal path.
    if not explicit and convergence.has_unresolved_high_impact(state):
        memo.emitted = False
        memo.refused_reason = ("convergence gate: a high-impact Albert challenge is "
                               "still unresolved")
        return memo

    # Gate 3 (CORRECTNESS): citation — no UNVERIFIED KEY claim. ALWAYS applies;
    # explicit never bypasses it (an unverified KEY claim makes the memo a lie).
    if memo.unverified_key_claims:
        memo.emitted = False
        memo.refused_reason = (
            "citation gate: unverified KEY claim(s): "
            + "; ".join(memo.unverified_key_claims)
        )
        return memo

    # Gate 4 (COMPLETENESS): readiness target met OR an explicit emit command.
    if not exhaustion.targets_met(state) and not explicit:
        memo.emitted = False
        memo.refused_reason = ("readiness gate: readiness target not met and no "
                               "explicit emit command")
        return memo

    memo.emitted = True
    memo.refused_reason = None
    return memo
