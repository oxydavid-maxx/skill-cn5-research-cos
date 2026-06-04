"""Pydantic v2 data models + Enums for the deterministic research convergence loop.

All status/type/decision fields are Enums (str, Enum; value == name).
No wall-clock calls inside models — timestamps/run_id are supplied by callers.
The Readiness Board is *derived* (see artifacts/readiness_board.py), never stored here.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class IssueType(str, Enum):
    root_question = "root_question"
    intent = "intent"
    roi = "roi"
    risk = "risk"
    competitor = "competitor"
    internal_data = "internal_data"
    technical = "technical"
    market = "market"


class IssueStatus(str, Enum):
    open = "open"
    researching = "researching"
    partially_answered = "partially_answered"
    low_confidence = "low_confidence"
    answered = "answered"
    blocked_by_human = "blocked_by_human"
    blocked_by_internal_data = "blocked_by_internal_data"
    blocked_by_permission = "blocked_by_permission"
    blocked_by_decision = "blocked_by_decision"


class ChallengeStatus(str, Enum):
    open = "open"
    answered = "answered"
    resolved = "resolved"
    escalated_to_human = "escalated_to_human"
    needs_internal_data = "needs_internal_data"
    needs_albert_decision = "needs_albert_decision"
    needs_bu_judgment = "needs_bu_judgment"


class HumanTaskStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


class BoardColumn(str, Enum):
    answered = "answered"
    pending = "pending"
    blocked = "blocked"
    needs_human = "needs_human"


class SourceType(str, Enum):
    primary = "primary"
    secondary = "secondary"
    standard = "standard"
    marketing = "marketing"
    internal = "internal"


class SourceQuality(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


class Decision(str, Enum):
    continue_research = "continue_research"
    branch = "branch"
    rerank = "rerank"
    pull_human = "pull_human"
    push_human = "push_human"
    synthesize = "synthesize"
    pause = "pause"
    terminal_stop = "terminal_stop"


class Classification(str, Enum):
    addressable = "addressable"
    residual = "residual"


class AuditVerdict(str, Enum):
    continue_ = "continue"
    exhausted = "exhausted"
    rework = "rework"


class Risk(str, Enum):
    low = "low"
    med = "med"
    high = "high"


# --------------------------------------------------------------------------- #
# Core artifact models
# --------------------------------------------------------------------------- #
class IssueNode(BaseModel):
    id: str
    parent_id: str | None = None
    title: str
    description: str
    issue_type: IssueType
    status: IssueStatus
    impact: int = Field(ge=0, le=5)
    confidence: int = Field(ge=0, le=5)
    evidence_refs: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    human_blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    last_updated: str | None = None
    last_audited: str | None = None


class CellStatus(str, Enum):
    open = "open"
    partial = "partial"
    covered = "covered"
    blocked = "blocked"      # NDA / internal-only
    na = "na"                # no public data exists


class TaskCell(BaseModel):
    id: str
    vendor: str
    spec_group: str
    part_number: str | None = None
    objective: str
    output_format: str = ""
    tools: list[str] = Field(default_factory=lambda: ["web"])
    boundaries: str = ""
    status: CellStatus = CellStatus.open
    impact: int = 3
    evidence_refs: list[str] = Field(default_factory=list)
    notes: str = ""


class TaskGrid(BaseModel):
    axes: list[str] = Field(default_factory=lambda: ["vendor", "spec_group"])
    cells: dict[str, TaskCell] = Field(default_factory=dict)

    def open_high_impact_cells(self, *, min_impact: int = 4) -> list[TaskCell]:
        return [c for c in self.cells.values()
                if c.status in (CellStatus.open, CellStatus.partial) and c.impact >= min_impact]


class AlbertChallenge(BaseModel):
    id: str
    challenge: str
    # P4b convergence: the issue this challenge is tied to (the researcher/COS use
    # it to direct next-round research at the open challenge). Optional — an
    # untied challenge is a whole-answer challenge.
    issue_id: str | None = None
    why_albert_would_ask: str = ""
    current_answer: str = ""
    status: ChallengeStatus = ChallengeStatus.open
    confidence: int = Field(default=0, ge=0, le=5)
    evidence_refs: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    blocking_owner: str | None = None
    next_action: str | None = None
    meeting_ready_response: str | None = None
    classification: Classification | None = None
    # P4b convergence: how many audit rounds this challenge has been seen in
    # (incremented on each upsert merge). Drives convergence-signal trends.
    rounds_seen: int = 0


class HumanTask(BaseModel):
    id: str
    task_title: str
    owner: str | None = None
    requested_input: str = ""
    why_needed: str = ""
    blocking_question: str = ""
    priority: int = Field(default=3, ge=0, le=5)
    can_continue_without_it: bool = True
    fallback_plan: str = ""
    status: HumanTaskStatus = HumanTaskStatus.open


class Source(BaseModel):
    id: str
    title: str
    url: str | None = None
    source_type: SourceType = SourceType.secondary
    quality: SourceQuality = SourceQuality.unknown
    # P4b citation routing: where the source came from. "web" = a WebSearch hit
    # (Component 3 runs our difflib verbatim verify on its claims); "internal" =
    # a paperwork/internal-doc fragment (P4a set this; carried as paperwork-
    # verified, no difflib re-run). Default "web" since the web researcher is the
    # baseline path; the internal-doc path stamps "internal" explicitly.
    origin: str = "web"
    # P5 citation verify: the verbatim surrounding text the citation verifier
    # reads. web: the sentence(s) containing the quote (captured by the
    # researcher); internal: the paperwork fragment quote (carried from P4a).
    # Empty by default so existing P1-P4 Sources construct unchanged.
    excerpt: str = ""


class Claim(BaseModel):
    claim: str
    source_refs: list[str] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=5)
    notes: str = ""


class CitationStatus(str, Enum):
    verified = "verified"
    unverified = "unverified"
    escalated = "escalated"
    flagged = "flagged"


class VerifyResult(BaseModel):
    """Result of routing a claim through citation verification (P4b Component 3)."""
    claim: str
    origin: str                      # "web" | "internal"
    verified: bool
    method: str                      # "difflib" | "paperwork" | "none"
    quote: str = ""
    source_refs: list[str] = Field(default_factory=list)
    ratio: float = 0.0
    status: CitationStatus = CitationStatus.unverified
    reason: str = ""


class EvidenceBundle(BaseModel):
    query: str
    issue_id: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)


class ReadinessScore(BaseModel):
    albert_challenge_readiness: int = Field(ge=0, le=5)
    decision_readiness: int = Field(ge=0, le=5)
    research_exhaustion_readiness: int = Field(ge=0, le=5)
    human_bottleneck_clarity: int = Field(ge=0, le=5)
    should_continue: bool = True
    reason: str = ""


class AuditResult(BaseModel):
    verdict: AuditVerdict
    challenges: list[AlbertChallenge] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    premature_end_risk: Risk = Risk.low
    research_drift_risk: Risk = Risk.low
    recommended_next_action: Decision | None = None
    rationale: str = ""
    # R2 additions
    missing_business_context: list[str] = Field(default_factory=list)
    questions_albert_would_ask_next: list[str] = Field(default_factory=list)
    recommended_next_probe: str | None = None
    readiness_score_delta: int = 0
    degraded: bool = False


# --------------------------------------------------------------------------- #
# P5 — §22 decision-memo models
# --------------------------------------------------------------------------- #
class BlockerType(str, Enum):
    """The 6 kinds a §4 blocker is labeled as (deterministic labeling)."""
    research = "research"
    internal_data = "internal_data"
    permission = "permission"
    human_judgment = "human_judgment"
    bu_preference = "bu_preference"
    albert_decision = "albert_decision"


class Blocker(BaseModel):
    """One labeled §4 blocker: what is blocking + which of the 6 kinds it is."""
    blocker_type: BlockerType
    description: str = ""
    source_id: str = ""          # issue id or challenge id this blocker came from
    owner: str | None = None     # who must unblock it (human/BU/Albert), if known


class MemoSection(BaseModel):
    """One §22 memo section: a stable key + a display title + LLM-written body."""
    key: str
    title: str
    body: str = ""


class Memo(BaseModel):
    """The §22 decision-memo: the 9 sections + the emission-gate verdict."""
    sections: list[MemoSection] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    unverified_key_claims: list[str] = Field(default_factory=list)
    # P5c confidence policy: unverified-CRITICAL claims that could not be verified
    # and were routed to a HumanTask (needs human supplement). These are surfaced
    # in the "What We Cannot Say" / "Required Human Decisions" sections — clearly
    # flagged "needs human supplement", NEVER presented as verified fact. The memo
    # STILL emits with these present (the loop continues, never blocks).
    needs_supplement: list[str] = Field(default_factory=list)
    emitted: bool = False
    refused_reason: str | None = None

    def section_keys(self) -> list[str]:
        return [s.key for s in self.sections]


class ResearchState(BaseModel):
    run_id: str
    original_question: str
    meeting_context: str = ""
    target_audience: str = ""
    mode: str = "interactive"

    # R2 preflight (H0) + brief
    likely_albert_concern: str | None = None
    output_purpose: str | None = None
    known_constraints: list[str] = Field(default_factory=list)
    forbidden_directions: list[str] = Field(default_factory=list)
    available_sources: list[str] = Field(default_factory=list)
    internal_documents_available: bool | None = None
    default_research_priority: str | None = None
    fallback_behavior_if_human_unavailable: str | None = None
    research_brief: str | None = None

    # P8 (H0): decision criterion + success form + clarify convergence + task grid
    decision_criterion: str | None = None
    success_form: str | None = None
    clarify_converged: bool = False
    task_grid: TaskGrid | None = None

    # live artifacts
    issue_map: dict[str, IssueNode] = Field(default_factory=dict)
    albert_challenge_map: dict[str, AlbertChallenge] = Field(default_factory=dict)
    evidence: list[EvidenceBundle] = Field(default_factory=list)
    human_tasks: dict[str, HumanTask] = Field(default_factory=dict)
    branches: dict = Field(default_factory=dict)
    steering_events: list[dict] = Field(default_factory=list)

    # scoring / audit
    readiness_score: ReadinessScore | None = None
    readiness_history: list[dict] = Field(default_factory=list)
    # P4b convergence: per-round snapshot of the unresolved-challenge count, so the
    # loop can see the open-count trend toward 0 (a convergence signal).
    convergence_history: list[int] = Field(default_factory=list)
    iteration_count: int = 0
    last_audit: AuditResult | None = None
    # P3 audit tiering: how many times the Tier-2 deep audit ran (only at gates).
    deep_audit_count: int = 0

    # research dedup seen-set: research-query strings (issue titles) already
    # dispatched this run, so the supervisor never re-researches the same query
    # (P2 acceleration). A list (not set) for JSON round-trip; order-insensitive.
    researched_queries: list[str] = Field(default_factory=list)

    # P5c multi-format reference intake: per-run dedup keys ("<name>::<mtime_ns>")
    # for files already converted from runs/<run_id>/reference/, so each dropped
    # file is processed once even if the folder is re-scanned every iteration.
    processed_references: list[str] = Field(default_factory=list)

    # output
    final_memo: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    # Component C: the reason the run stopped when a HARD cap (cost/wall) fired
    # (e.g. "hard cost cap hit: $10.31 >= $10.00"). None on a normal stop. The loop
    # records this then emits the current findings (degraded-but-honest).
    stop_reason: str | None = None
