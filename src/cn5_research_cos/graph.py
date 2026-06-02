"""LangGraph StateGraph: full §18 node set, supervisor Send-fan-out, staged router.

Canonical order (flow-diagram R2):
  intake -> scope -> write_brief -> issue_expansion -> supervisor
    -> [Send -> worker (research -> source_critic -> compress)] -> collect
    -> skeptic -> albert_audit -> artifact_update -> readiness_scoring
    -> anti_premature -> cos_decision -> router

Determinism / no wall-clock: ``now`` flows through GraphState from the caller.
Router functions are read-only (no state mutation) per LangGraph best practice;
all mutation happens in nodes.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from .artifacts import issue_map
from .brains import build_brains
from .llm import sdk_client
from .decision import anti_premature, branch_budget, exhaustion, gate
from .models import (Decision, EvidenceBundle, IssueStatus, IssueType,
                     ResearchState)
from .state import GraphState
from .store import save_snapshot

# Two-level caps + branch budget seed.
DEFAULT_BREADTH = 4
DEFAULT_DEPTH = 2

# P2 acceleration: cap how many issues fan out to the (expensive) researcher per
# iteration. Each researched issue is one WebSearch-bearing LLM call, so an
# unbounded fan-out re-spawns N `claude` processes per round. Top-K-by-impact
# keeps the highest-leverage work and lets the loop converge in fewer total
# searches. Overridable via env for live tuning.
DEFAULT_MAX_RESEARCH_PER_ITER = 3

_ANSWERED_OR_BLOCKED = (
    IssueStatus.answered,
    IssueStatus.blocked_by_human,
    IssueStatus.blocked_by_internal_data,
    IssueStatus.blocked_by_permission,
    IssueStatus.blocked_by_decision,
)


def _max_research_per_iter() -> int:
    raw = os.environ.get("CN5_COS_MAX_RESEARCH_PER_ITER")
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return DEFAULT_MAX_RESEARCH_PER_ITER


def select_research_issues(state: ResearchState, brains, k: int | None = None) -> list[str]:
    """Choose which issue ids to fan out to the researcher THIS iteration.

    Wraps the brain bundle's raw `supervisor.select`, then enforces the P2
    acceleration budget (pure / deterministic):

    * skip ``answered`` and any ``blocked_*`` issue (never re-research a closed
      or human-gated issue);
    * dedup identical research queries within the run (the issue title is the
      query key) against ``state.researched_queries`` — a query is researched at
      most once per run;
    * order the survivors by ``impact`` descending (stable) and take the top-K
      (``k`` or env ``CN5_COS_MAX_RESEARCH_PER_ITER`` or the default 3).

    Side effect: records the selected queries into ``state.researched_queries``
    so a later iteration's identical issue is skipped.
    """
    cap = k if k is not None else _max_research_per_iter()
    raw_ids = list(brains.supervisor.select(state))
    seen = set(state.researched_queries)

    candidates: list[tuple[int, str]] = []
    for iid in raw_ids:
        node = state.issue_map.get(iid)
        if node is None:
            continue
        if node.status in _ANSWERED_OR_BLOCKED:
            continue
        query = node.title
        if query in seen:
            continue
        candidates.append((node.impact, iid))

    # Stable sort by impact descending (Python sort is stable, so ties keep the
    # supervisor's original order).
    candidates.sort(key=lambda t: t[0], reverse=True)
    selected = [iid for _impact, iid in candidates[:cap]]

    for iid in selected:
        q = state.issue_map[iid].title
        if q not in state.researched_queries:
            state.researched_queries.append(q)
    return selected


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def _brains(state: GraphState | None = None):
    """Resolve the brain bundle for this run.

    The bundle is selected by GraphState['llm'] ('mock' default keeps the P1
    deterministic loop unchanged; 'real' injects the P2b cheap-LLM brains). The
    graph topology + all loop/COS control are IDENTICAL for both.
    """
    llm = (state or {}).get("llm", "mock") if isinstance(state, dict) else "mock"
    return build_brains(llm or "mock")


def node_intake(state: GraphState) -> GraphState:
    rs: ResearchState = state["research_state"]
    return {
        "research_state": rs,
        "branch_budget": {"breadth": DEFAULT_BREADTH, "depth": DEFAULT_DEPTH},
        "prereqs": {k: False for k in anti_premature.PREREQS},
        "worker_results": [],
    }


def node_scope(state: GraphState) -> GraphState:
    rs = state["research_state"]
    _brains(state).clarify_gate.check(rs)  # P1: always clarified
    return {"research_state": rs}


def node_write_brief(state: GraphState) -> GraphState:
    rs = state["research_state"]
    if not rs.research_brief:
        _brains(state).brief_writer.write(rs)
    return {"research_state": rs}


def node_issue_expansion(state: GraphState) -> GraphState:
    rs = state["research_state"]
    now = state.get("now", "t")
    _brains(state).issue_expander.expand(rs, now=now)
    prereqs = dict(state.get("prereqs", {}))
    prereqs["broad_expansion"] = True
    return {"research_state": rs, "prereqs": prereqs}


def node_supervisor(state: GraphState) -> GraphState:
    # No mutation here beyond clearing the per-round worker buffer; the actual
    # CONCURRENT fan-out happens in `node_research_fanout` (the next edge).
    return {"worker_results": []}


def _build_worker_proxy(rs: ResearchState, issue_id: str) -> ResearchState:
    """A throwaway, context-isolated ResearchState carrying just the one issue the
    researcher needs (title + iteration count) — per the ODR supervisor pattern,
    a worker sees ONLY its issue, not the whole run state."""
    from .models import IssueNode
    node = rs.issue_map.get(issue_id)
    title = node.title if node else issue_id
    desc = (node.description if node and node.description else title)
    proxy = ResearchState(run_id="_worker", original_question=rs.original_question)
    proxy.iteration_count = rs.iteration_count
    proxy.issue_map[issue_id] = IssueNode(
        id=issue_id, title=title, description=desc,
        issue_type=(node.issue_type if node else IssueType.technical),
        status=IssueStatus.researching, impact=3, confidence=2,
    )
    return proxy


async def _research_one_async(brains, rs: ResearchState, issue_id: str, *, pool):
    """Research ONE issue concurrently, then run the (fast, sync) source_critic +
    compressor on its bundle. Returns the EvidenceBundle.

    Concurrency model: if the researcher exposes an async ``research_async`` it is
    awaited directly (it uses the bounded ``AsyncSessionPool`` for its WebSearch
    call, so the cap = MAX_CONCURRENT bounds parallel `claude` spawns). Otherwise
    (deterministic stub / sync brain) the sync ``research`` runs in a worker thread
    via ``asyncio.to_thread`` so independent issues still overlap. The cheap
    critic/compress brains stay sequential per the spec.
    """
    proxy = _build_worker_proxy(rs, issue_id)
    researcher = brains.researcher
    if hasattr(researcher, "research_async"):
        bundle = await researcher.research_async(proxy, issue_id, pool=pool)
    else:
        bundle = await asyncio.to_thread(researcher.research, proxy, issue_id)
    bundle = brains.source_critic.review(bundle)
    bundle = brains.compressor.compress(bundle)
    return bundle


def run_research_fanout(rs: ResearchState, selected: list[str], brains, *,
                        now: str = "t", llm: str = "mock") -> list:
    """Run the K selected issues' researchers CONCURRENTLY (one event loop, bounded
    by the MAX_CONCURRENT semaphore) and return their EvidenceBundles in STABLE
    issue-id order (the selection order) regardless of finish order.

    A researcher that raises is skipped (its issue produces no bundle) but does NOT
    break the others and does NOT leak a pool permit — the gather collects
    exceptions per-task via ``return_exceptions=True``.
    """
    if not selected:
        return []

    cap = sdk_client._max_concurrent()

    async def _run():
        pool = None
        if llm == "real":
            pool = sdk_client.AsyncSessionPool(max_concurrent=cap)
        # A fan-out-level semaphore is the HARD ceiling on concurrent researchers
        # for BOTH paths: the real path's pool also caps per-key spawns at the
        # same MAX_CONCURRENT (they compose), and the mock path (local sleeps, no
        # pool) is bounded here too. Task 3: MAX_CONCURRENT bounds parallel spawns.
        sem = asyncio.Semaphore(cap)

        async def _guarded(iid):
            async with sem:
                return await _research_one_async(brains, rs, iid, pool=pool)

        try:
            tasks = [_guarded(iid) for iid in selected]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if pool is not None:
                await pool.aclose()
        # Stable order = selection order; drop the ones that raised.
        bundles = []
        for iid, res in zip(selected, results):
            if isinstance(res, Exception):
                continue
            bundles.append(res)
        return bundles

    return asyncio.run(_run())


def node_research_fanout(state: GraphState) -> GraphState:
    """Concurrent researcher fan-out node (replaces the serial Send -> worker
    fan-out). Selects the top-K issues, researches them concurrently, and writes
    the bundles into ``worker_results`` (consumed by ``node_collect``) in stable
    issue-id order so the loop stays deterministic."""
    rs = state["research_state"]
    now = state.get("now", "t")
    llm = state.get("llm", "mock")
    brains = _brains(state)
    selected = select_research_issues(rs, brains)
    bundles = run_research_fanout(rs, selected, brains, now=now, llm=llm)
    return {"worker_results": [b.model_dump() for b in bundles]}


def node_collect(state: GraphState) -> GraphState:
    """Fold worker_results into research_state.evidence and advance issue status."""
    rs = state["research_state"]
    now = state.get("now", "t")
    prereqs = dict(state.get("prereqs", {}))
    for raw in state.get("worker_results", []):
        bundle = EvidenceBundle.model_validate(raw)
        rs.evidence.append(bundle)
        iid = bundle.issue_id
        if iid and iid in rs.issue_map:
            node = rs.issue_map[iid]
            # Progress addressable issues: open -> partially_answered -> answered.
            if node.status in (IssueStatus.open, IssueStatus.researching):
                issue_map.set_status(rs, iid, IssueStatus.partially_answered, now=now)
            elif node.status == IssueStatus.partially_answered:
                issue_map.set_status(rs, iid, IssueStatus.answered, now=now)
                node.confidence = 4
            node.evidence_refs.append(bundle.query)
    prereqs["source_confidence_checked"] = True
    return {"research_state": rs, "prereqs": prereqs, "worker_results": []}


def node_skeptic(state: GraphState) -> GraphState:
    rs = state["research_state"]
    prereqs = dict(state.get("prereqs", {}))
    last = rs.evidence[-1] if rs.evidence else EvidenceBundle(query="")
    counters = _brains(state).skeptic.counter(rs, last)
    for n in rs.issue_map.values():
        if n.status != IssueStatus.answered:
            for c in counters:
                if c not in n.counterarguments:
                    n.counterarguments.append(c)
    prereqs["counterargument_pass"] = True
    return {"research_state": rs, "prereqs": prereqs}


def node_albert_audit(state: GraphState) -> GraphState:
    rs = state["research_state"]
    prereqs = dict(state.get("prereqs", {}))
    now = state.get("now", "t")
    audit = _brains(state).auditor.audit(rs)
    rs.last_audit = audit
    # Record challenges into the challenge map.
    from .artifacts import challenge_map
    for ch in audit.challenges:
        challenge_map.add(
            rs, challenge=ch.challenge,
            why_albert_would_ask=ch.why_albert_would_ask,
            status=ch.status, classification=ch.classification,
        )
    for n in rs.issue_map.values():
        n.last_audited = now
    prereqs["albert_audit_ran"] = True
    if audit.questions_albert_would_ask_next:
        prereqs["pending_questions_extracted"] = True
    else:
        # No further questions means the auditor extracted/closed them.
        prereqs["pending_questions_extracted"] = True
    return {"research_state": rs, "prereqs": prereqs}


def node_artifact_update(state: GraphState) -> GraphState:
    """Consume compressed output, classify residual blockers, snapshot."""
    rs = state["research_state"]
    prereqs = dict(state.get("prereqs", {}))
    base_dir = state.get("base_dir", "runs")
    # Classify blockers: any blocked_by_* issue is a recorded residual blocker.
    for n in rs.issue_map.values():
        if n.status in (
            IssueStatus.blocked_by_human, IssueStatus.blocked_by_internal_data,
            IssueStatus.blocked_by_permission, IssueStatus.blocked_by_decision,
        ) and not n.human_blockers:
            n.human_blockers.append("recorded residual blocker (stub)")
    prereqs["blockers_classified"] = True
    save_snapshot(rs, base_dir=base_dir)
    return {"research_state": rs, "prereqs": prereqs}


def node_readiness_scoring(state: GraphState) -> GraphState:
    rs = state["research_state"]
    score = _brains(state).scorer.score(rs)
    rs.readiness_score = score
    s = (score.albert_challenge_readiness + score.decision_readiness
         + score.research_exhaustion_readiness + score.human_bottleneck_clarity)
    rs.readiness_history.append({"sum": s, "iteration": rs.iteration_count})
    rs.iteration_count += 1
    return {"research_state": rs}


def node_anti_premature(state: GraphState) -> GraphState:
    rs = state["research_state"]
    prereqs = dict(state.get("prereqs", {}))
    # explicit_continue_explanation is recorded once an audit rationale exists.
    if rs.last_audit is not None and rs.last_audit.rationale:
        prereqs["explicit_continue_explanation"] = True
    return {"research_state": rs, "prereqs": prereqs}


def _materialize_competitor(rs: ResearchState, now: str, budget: dict) -> dict:
    """Create the auditor-requested competitor issue, bounded by branch budget."""
    b = branch_budget.Budget(breadth=budget["breadth"], depth=budget["depth"])
    if branch_budget.can_branch(b) and not issue_map.has_type(rs, IssueType.competitor):
        issue_map.add(
            rs, title="競品是否已有此能力?", description="Albert 會挑戰的競品角度",
            issue_type=IssueType.competitor, status=IssueStatus.open, now=now,
            impact=4, confidence=1,
        )
        b = branch_budget.spend(b)
    return {"breadth": b.breadth, "depth": b.depth}


def node_cos_decision(state: GraphState) -> GraphState:
    """Staged binary gates → a single Decision. Pure decision helpers do the logic;
    this node records the result and materializes the auditor-requested branch."""
    rs = state["research_state"]
    prereqs = state.get("prereqs", {})
    budget = dict(state.get("branch_budget", {"breadth": DEFAULT_BREADTH, "depth": DEFAULT_DEPTH}))
    now = state.get("now", "t")
    audit = rs.last_audit

    # Stage 1: audit clean? A REWORK verdict forces a branch toward the gap.
    if audit is not None and audit.verdict.value == "rework":
        budget = _materialize_competitor(rs, now, budget)
        decision = Decision.branch
        return {"research_state": rs, "last_decision": decision, "branch_budget": budget}

    # Stage 2: anti-premature 7 prerequisites all satisfied?
    if not anti_premature.all_done(prereqs):
        decision = Decision.continue_research
        return {"research_state": rs, "last_decision": decision, "branch_budget": budget}

    # Stage 3: exhaustion / terminal eligibility (ANDed with prereqs).
    if exhaustion.terminal_eligible(rs, flags=prereqs):
        decision = gate.assert_audit_ran(rs, Decision.terminal_stop)
        return {"research_state": rs, "last_decision": decision, "branch_budget": budget}

    # Stage 4: auditor recommends synthesize (addressable saturated, residual remains)
    # OR plateau detected → synthesize (gated by emission gate).
    if (audit is not None and audit.recommended_next_action == Decision.synthesize) \
            or exhaustion.plateau(rs, window=2):
        decision = gate.assert_audit_ran(rs, Decision.synthesize)
        return {"research_state": rs, "last_decision": decision, "branch_budget": budget}

    # Stage 5: residual-only with explicit blockers but targets unmet → push_human,
    # then continue other branches (non-blocking in P1).
    if not exhaustion.has_addressable(rs):
        decision = Decision.push_human
        return {"research_state": rs, "last_decision": decision, "branch_budget": budget}

    decision = Decision.continue_research
    return {"research_state": rs, "last_decision": decision, "branch_budget": budget}


# --------------------------------------------------------------------------- #
# Router (read-only)
# --------------------------------------------------------------------------- #
def _route(state: GraphState) -> str:
    rs = state["research_state"]
    decision = state.get("last_decision", Decision.continue_research)
    max_it = state.get("max_iterations", 8)
    if decision in (Decision.terminal_stop, Decision.synthesize):
        return "END"
    if rs.iteration_count >= max_it:
        return "END"
    if decision in (Decision.branch, Decision.rerank):
        return "issue_expansion"
    # pull_human / push_human / pause / continue_research → keep researching
    return "supervisor"


# --------------------------------------------------------------------------- #
# Graph assembly
# --------------------------------------------------------------------------- #
def build_graph() -> StateGraph:
    g = StateGraph(GraphState)
    g.add_node("intake", node_intake)
    g.add_node("scope", node_scope)
    g.add_node("write_brief", node_write_brief)
    g.add_node("issue_expansion", node_issue_expansion)
    g.add_node("supervisor", node_supervisor)
    g.add_node("research_fanout", node_research_fanout)
    g.add_node("collect", node_collect)
    g.add_node("skeptic", node_skeptic)
    g.add_node("albert_audit", node_albert_audit)
    g.add_node("artifact_update", node_artifact_update)
    g.add_node("readiness_scoring", node_readiness_scoring)
    g.add_node("anti_premature", node_anti_premature)
    g.add_node("cos_decision", node_cos_decision)

    g.add_edge(START, "intake")
    g.add_edge("intake", "scope")
    g.add_edge("scope", "write_brief")
    g.add_edge("write_brief", "issue_expansion")
    g.add_edge("issue_expansion", "supervisor")
    # supervisor -> CONCURRENT researcher fan-out (asyncio.gather over the top-K
    # selected issues, bounded by the MAX_CONCURRENT pool semaphore) -> collect.
    g.add_edge("supervisor", "research_fanout")
    g.add_edge("research_fanout", "collect")
    g.add_edge("collect", "skeptic")
    g.add_edge("skeptic", "albert_audit")
    g.add_edge("albert_audit", "artifact_update")
    g.add_edge("artifact_update", "readiness_scoring")
    g.add_edge("readiness_scoring", "anti_premature")
    g.add_edge("anti_premature", "cos_decision")
    g.add_conditional_edges(
        "cos_decision", _route,
        {"END": END, "issue_expansion": "issue_expansion", "supervisor": "supervisor"},
    )
    return g


def compile_graph():
    return build_graph().compile()


def compile_with_checkpoint(run_dir):
    """Compile with a persistent SqliteSaver for resume.

    langgraph-checkpoint-sqlite 3.x: ``from_conn_string`` is a context manager, so
    for a long-lived saver we construct SqliteSaver directly over a sqlite3 conn.
    Returns (compiled_app, saver, conn) — caller keeps conn alive for the run.
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite import SqliteSaver

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(run_dir / "checkpoint.db"), check_same_thread=False)
    # Allowlist our own model modules so msgpack (de)serialization of the
    # Pydantic-backed enums/state is explicit and future-proof (silences the
    # "unregistered type" deprecation warning).
    serde = JsonPlusSerializer(allowed_msgpack_modules=True)
    saver = SqliteSaver(conn, serde=serde)
    app = build_graph().compile(checkpointer=saver)
    return app, saver, conn


def run_loop(
    initial: ResearchState,
    *,
    base_dir,
    max_iterations: int = 8,
    now: str = "t",
    llm: str = "mock",
    metrics=None,
    return_metrics: bool = False,
):
    """Run the convergence loop to completion.

    For ``llm == "real"`` a run-scoped persistent ``ClaudeSession`` pool is opened
    (P2 acceleration) so the real brains' repeated structured calls reuse one
    `claude` per (schema, tools) instead of re-spawning per call; cost/latency is
    accumulated into ``metrics`` (a fresh ``RunMetrics`` if none supplied).

    Returns the final ``ResearchState``; if ``return_metrics`` is True, returns
    ``(final_state, metrics)`` (back-compat: default returns the state alone).
    """
    from .llm import sdk_client
    from .llm.metrics import RunMetrics

    if metrics is None:
        metrics = RunMetrics()

    app = compile_graph()
    init: GraphState = {
        "research_state": initial,
        "base_dir": str(base_dir),
        "now": now,
        "max_iterations": max_iterations,
        "llm": llm,
    }

    def _invoke():
        return app.invoke(init, config={"recursion_limit": 100})

    if llm == "real":
        with sdk_client.use_session_pool(metrics=metrics):
            out = _invoke()
    else:
        out = _invoke()

    final = out["research_state"]
    save_snapshot(final, base_dir=base_dir)
    if return_metrics:
        return final, metrics
    return final
