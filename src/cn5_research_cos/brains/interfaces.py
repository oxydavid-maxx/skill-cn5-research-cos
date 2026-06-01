"""Brain interfaces (Protocols). Each brain is a pure-ish function of state → typed result.

P1 ships only the deterministic stub implementations (stubs.py). P2 binds real brains
at the same ``build_brains`` factory without touching the graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..models import (AuditResult, EvidenceBundle, IssueNode, ReadinessScore,
                      ResearchState)


@runtime_checkable
class ClarifyGate(Protocol):
    def check(self, state: ResearchState) -> bool: ...  # scope / H0


@runtime_checkable
class BriefWriter(Protocol):
    def write(self, state: ResearchState) -> None: ...


@runtime_checkable
class IssueExpander(Protocol):
    def expand(self, state: ResearchState, now: str) -> list[IssueNode]: ...


@runtime_checkable
class Supervisor(Protocol):
    def select(self, state: ResearchState) -> list[str]: ...  # issue ids to fan out


@runtime_checkable
class Researcher(Protocol):
    def research(self, state: ResearchState, issue_id: str) -> EvidenceBundle: ...


@runtime_checkable
class SourceCritic(Protocol):
    def review(self, bundle: EvidenceBundle) -> EvidenceBundle: ...


@runtime_checkable
class Compressor(Protocol):
    def compress(self, bundle: EvidenceBundle) -> EvidenceBundle: ...


@runtime_checkable
class Skeptic(Protocol):
    def counter(self, state: ResearchState, bundle: EvidenceBundle) -> list[str]: ...


@runtime_checkable
class Auditor(Protocol):
    def audit(self, state: ResearchState) -> AuditResult: ...


@runtime_checkable
class Scorer(Protocol):
    def score(self, state: ResearchState) -> ReadinessScore: ...


@dataclass
class Brains:
    clarify_gate: ClarifyGate
    brief_writer: BriefWriter
    issue_expander: IssueExpander
    supervisor: Supervisor
    researcher: Researcher
    source_critic: SourceCritic
    compressor: Compressor
    skeptic: Skeptic
    auditor: Auditor
    scorer: Scorer
