"""Tier-pluggable, model-configurable auditor seam (spec §"Audit tiering").

P3 ships a 2-tier model:

  * **sentinel** — the cheap LLM (P2b simulator) / deterministic stub, run EVERY
    iteration by ``node_albert_audit``.
  * **deep** — run ONLY at a deterministic GATE (before synthesize/terminal or
    before a high-risk human pull). In P3 the "deep" auditor is STILL the same
    simulator/stub (real Albert FSM = P6); this phase builds the GATE PLACEMENT,
    not a third model tier.

``build_auditor(tier, model, base)`` is the seam: it returns a thin ``TieredAuditor``
that records its ``tier`` + ``model`` and delegates ``.audit`` to a base auditor.
Later phases swap Sonnet/Opus/real-Albert in BY CONFIG (pass ``model=...`` and a
different ``base``), not by rewriting the graph.

The wrapper is intentionally minimal (no model dispatch logic yet) so the cheap
deterministic path stays import-light: a real ``base`` is only constructed when
the caller asks for it (``base=None`` + a real llm is resolved lazily by the
factory in :mod:`cn5_research_cos.brains`).
"""
from __future__ import annotations

from ..models import AuditResult, ResearchState

VALID_TIERS = ("sentinel", "deep")


class TieredAuditor:
    """Auditor adapter carrying tier + model metadata, delegating to ``base``."""

    def __init__(self, base, *, tier: str, model: str | None = None):
        self.base = base
        self.tier = tier
        self.model = model

    def audit(self, state: ResearchState) -> AuditResult:
        return self.base.audit(state)


def build_auditor(tier: str = "sentinel", *, model: str | None = None, base=None) -> TieredAuditor:
    """Construct a tier-tagged auditor.

    * ``tier`` must be one of :data:`VALID_TIERS`.
    * ``model`` is recorded for later model-cascade swaps (unused logic in P3).
    * ``base`` is the underlying auditor; if ``None`` a deterministic
      :class:`~cn5_research_cos.brains.stubs.AuditorStub` is used (the P3 "deep"
      tier is still the simulator/stub — real Albert is P6).
    """
    if tier not in VALID_TIERS:
        raise ValueError(f"unknown auditor tier {tier!r}; expected one of {VALID_TIERS}")
    if base is None:
        from .stubs import AuditorStub
        base = AuditorStub()
    return TieredAuditor(base, tier=tier, model=model)
