"""LangGraph StateGraph: full §18 node set, concurrent researcher fan-out, staged router.

Canonical order (P8 flow-diagram):
  intake -> scope -> clarify -> write_brief
    -> orchestrator_plan -> plan_audit -> plan_approval -> supervisor
    -> research_fanout (asyncio.gather over top-K issues, each
        research -> source_critic -> compress; bounded by MAX_CONCURRENT) -> collect
    -> skeptic -> albert_audit -> artifact_update -> readiness_scoring
    -> anti_premature -> cos_decision -> router (loop head = orchestrator_plan)

P2 acceleration increment 2: the per-issue researchers run CONCURRENTLY
(``run_research_fanout`` → ``asyncio.gather``) in one event loop, bounded by the
``CN5_COS_MAX_CONCURRENT`` semaphore (= the hard ceiling on parallel `claude`
spawns); results fold into ``state.evidence`` in stable issue-id order so the
loop stays deterministic. Replaces the earlier serial ``Send`` → worker fan-out.

Determinism / no wall-clock: ``now`` flows through GraphState from the caller.
Router functions are read-only (no state mutation) per LangGraph best practice;
all mutation happens in nodes.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import sqlite3
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .artifacts import issue_map
from .brains import build_brains
from .llm import sdk_client
from .decision import (anti_premature, branch_budget, cell_exhaustion,
                       cell_synthesis, convergence, exhaustion, gate, risk, run_cap)
from .decision import clarify as _clarify
from .models import (CellStatus, ChallengeStatus, Decision, EvidenceBundle,
                     HumanTask, HumanTaskStatus, IssueStatus, IssueType,
                     ResearchState)
from .notify import notify_supplement_needed
from .observability import reporter as _obs
from .state import GraphState
from .store import save_snapshot

logger = logging.getLogger("cn5_research_cos.graph")

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

    # P4b convergence: issues that ANSWER an open Albert challenge get priority —
    # the COS directs next-round research at the open challenges first.
    from .decision import convergence
    issues_with_open_challenge = {
        c.issue_id for c in convergence.unresolved_challenges(state)
        if c.issue_id is not None
    }

    candidates: list[tuple[int, int, str]] = []
    for iid in raw_ids:
        node = state.issue_map.get(iid)
        if node is None:
            continue
        if node.status in _ANSWERED_OR_BLOCKED:
            continue
        query = node.title
        if query in seen:
            continue
        has_challenge = 1 if iid in issues_with_open_challenge else 0
        candidates.append((has_challenge, node.impact, iid))

    # Stable sort: open-challenge-linked issues first, then impact descending
    # (Python sort is stable, so ties keep the supervisor's original order).
    candidates.sort(key=lambda t: (t[0], t[1]), reverse=True)
    selected = [iid for _hc, _impact, iid in candidates[:cap]]

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

    A test may inject a ready-made ``Brains`` bundle via GraphState['brains'] (e.g.
    a counting-fake deep_auditor for the audit-gating test). This is only honored
    on the non-checkpointed ``compile_graph()`` path (a Brains dataclass is not
    JSON-serializable for the SqliteSaver); the production CLI never sets it.
    """
    if isinstance(state, dict):
        injected = state.get("brains")
        if injected is not None:
            return injected
    llm = (state or {}).get("llm", "mock") if isinstance(state, dict) else "mock"
    research_source = (state or {}).get("research_source", "web") \
        if isinstance(state, dict) else "web"
    albert = (state or {}).get("albert", "sim") if isinstance(state, dict) else "sim"
    return build_brains(llm or "mock", research_source=research_source or "web",
                        albert=albert or "sim")


# P5b: the checkpointed graph (run_auto / cos run) cannot carry a StageReporter
# inside GraphState — a reporter is not JSON/msgpack-serializable, so it would
# break SqliteSaver. The checkpointed path therefore publishes the reporter on
# this contextvar (set for the duration of the invoke); _report reads the
# GraphState slot first (non-checkpointed run_loop path), then the contextvar
# (checkpointed path). Default None → nodes emit nothing → existing tests green.
_REPORTER_CV: "contextvars.ContextVar[object | None]" = contextvars.ContextVar(
    "cn5_cos_reporter", default=None,
)


def _active_reporter(state: GraphState):
    if isinstance(state, dict):
        r = state.get("reporter")
        if r is not None:
            return r
    return _REPORTER_CV.get()


def _report(state: GraphState, stage_name: str, render_fn, *args) -> None:
    """Stream a per-stage debate block IF a StageReporter is active (threaded into
    GraphState on the non-checkpointed path, or published on ``_REPORTER_CV`` on
    the checkpointed path). No-op when none is present — the default in every
    existing loop test, so they stay green. Rendering is deterministic; a render
    error must never break the loop (the reporter is observability, not control),
    so it is swallowed."""
    reporter = _active_reporter(state)
    if reporter is None:
        return
    try:
        body = render_fn(*args)
        reporter.stage(stage_name, body)
    except Exception:  # noqa: BLE001 - observability must never crash the loop
        pass


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
    _report(state, "scope", _obs.render_scope, rs)
    return {"research_state": rs}


def node_write_brief(state: GraphState) -> GraphState:
    rs = state["research_state"]
    if not rs.research_brief:
        _brains(state).brief_writer.write(rs)
    return {"research_state": rs}


def node_clarify(state: GraphState) -> GraphState:
    """H0 — multi-round Socratic clarification. Blocks until the 4 criteria are
    pinned. The cockpit ASKS (clarifier brain); the human ANSWERS (interrupt).
    AFK / auto default = pause here UNLESS the brief already converged or
    `assume_brief` is set in state."""
    rs = state["research_state"]
    ok, missing = _clarify.clarify_converged(rs)
    if ok:
        rs.clarify_converged = True
        _report(state, "clarify", _obs.render_clarify, rs)
        return {"research_state": rs}
    if state.get("assume_brief"):
        rs.steering_events.append({"kind": "clarify-assumed", "missing": list(missing)})
        rs.clarify_converged = True
        _report(state, "clarify", _obs.render_clarify, rs)
        return {"research_state": rs}
    brains = _brains(state)
    questions = brains.clarifier.ask(rs, missing) if getattr(brains, "clarifier", None) else [f"請補充：{m}" for m in missing]
    # Record the questions on a steering event so render_clarify can surface them,
    # then stream the clarify block BEFORE interrupt() suspends the run (the human
    # must SEE the questions before the pause).
    rs.steering_events.append({"kind": "clarify-ask", "questions": questions, "missing": list(missing)})
    _report(state, "clarify", _obs.render_clarify, rs)
    answer = interrupt({"kind": "clarify", "questions": questions, "missing": missing})
    rs.steering_events.append({"kind": "clarify-answer", "answer": answer, "for_missing": list(missing)})
    return {"research_state": rs}


def _route_after_clarify(state: GraphState) -> str:
    return "write_brief" if state["research_state"].clarify_converged else "clarify"


_H7_MAJOR_DELTA = 2   # >= 2 new cells since last approval == "major re-decomposition"

def node_plan_approval(state: GraphState) -> GraphState:
    """P8 §5 H7 — human approves the task grid before expensive research. Prompts on
    the FIRST cycle, and again only on a MAJOR re-decomposition (>= _H7_MAJOR_DELTA new
    cells). Small re-ranks do NOT re-prompt. assume_brief short-circuits (no prompt)."""
    rs = state["research_state"]
    grid = getattr(rs, "task_grid", None)
    n_cells = len(grid.cells) if grid else 0
    last_n = state.get("_h7_approved_n")
    if state.get("assume_brief"):
        state["_h7_approved_n"] = n_cells
        rs.steering_events.append({"kind": "plan-assumed", "first_cycle": last_n is None,
                                   "cells": [c.id for c in grid.cells.values()] if grid else []})
        _report(state, "plan_approval", _obs.render_plan_approval, rs)
        return {"research_state": rs, "_h7_approved_n": n_cells}
    first = last_n is None
    major = (last_n is not None) and (n_cells - last_n >= _H7_MAJOR_DELTA)
    if not (first or major):
        _report(state, "plan_approval", _obs.render_plan_approval, rs)
        return {"research_state": rs}
    # Stream the plan BEFORE interrupt() suspends the run (the human must SEE the
    # cells being presented for approval before the pause).
    rs.steering_events.append({"kind": "plan-approval", "first_cycle": first,
                               "cells": [c.id for c in grid.cells.values()] if grid else []})
    _report(state, "plan_approval", _obs.render_plan_approval, rs)
    answer = interrupt({"kind": "plan_approval",
                        "cells": [c.id for c in grid.cells.values()] if grid else [],
                        "first_cycle": first})
    rs.steering_events.append({"kind": "plan-approval", "answer": answer})
    state["_h7_approved_n"] = n_cells
    return {"research_state": rs, "_h7_approved_n": n_cells}


def node_orchestrator_plan(state: GraphState) -> GraphState:
    """P8 §3 ① — loop head. (Re)build the section-aware task grid from the brief +
    prior results + Albert challenges + coverage gaps."""
    rs = state["research_state"]
    _consume_steer_events(rs)
    brains = _brains(state)
    # P8: the loop head replaces the write_brief->issue_expansion edge as the entry
    # to a research cycle. The research fan-out still selects from issue_map (an
    # existing, preserved node contract — spec §"P1-P6 keep their contracts"), so the
    # loop head must seed the issue_map on the FIRST cycle (empty map). The expander
    # is idempotent (it no-ops once issue_map is populated); branch/rerank re-expand
    # via the issue_expansion node reached through _route.
    expander = getattr(brains, "issue_expander", None)
    if expander is not None and not rs.issue_map:
        expander.expand(rs, now=state.get("now", "t"))
    if brains.orchestrator is not None:
        rs.task_grid = brains.orchestrator.plan(rs)
    _report(state, "orchestrator", _obs.render_orchestrator, rs)
    return {"research_state": rs}


def node_issue_expansion(state: GraphState) -> GraphState:
    rs = state["research_state"]
    now = state.get("now", "t")
    _brains(state).issue_expander.expand(rs, now=now)
    prereqs = dict(state.get("prereqs", {}))
    prereqs["broad_expansion"] = True
    _report(state, "expand", _obs.render_expand, rs)
    return {"research_state": rs, "prereqs": prereqs}


def _consume_steer_events(rs: ResearchState) -> None:
    """Apply any unconsumed H4 ``steer`` events: re-rank by bumping the impact of
    issues whose title matches the steer text (substring), so the next selection
    re-prioritises toward the steered direction. Each steer is consumed once."""
    for e in rs.steering_events:
        if e.get("kind") != "steer" or e.get("consumed"):
            continue
        text = e.get("text", "")
        bumped = False
        for n in rs.issue_map.values():
            if n.title and (n.title in text or text in n.title):
                n.impact = min(5, n.impact + 1)
                bumped = True
        e["consumed"] = True
        e["reranked"] = bumped


def node_supervisor(state: GraphState) -> GraphState:
    # Consume any pending H4 steer events (re-rank) BEFORE selection so the steered
    # direction takes effect this iteration; then clear the per-round worker buffer.
    # The actual CONCURRENT fan-out happens in `node_research_fanout` (next edge).
    rs = state["research_state"]
    _consume_steer_events(rs)
    return {"research_state": rs, "worker_results": []}


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
    """Research ONE issue concurrently and return its RAW EvidenceBundle.

    This runs INSIDE the fan-out event loop (``asyncio.gather`` / ``asyncio.run``),
    so it MUST stay purely async: only the WebSearch researcher runs here. The
    (sync) ``source_critic`` / ``compressor`` brains are intentionally NOT called
    here — they route through ``sdk_client``'s sync ``call_structured`` ->
    ``ClaudeSession`` path which drives its OWN event loop via
    ``run_until_complete`` / ``asyncio.run``. Invoking a sync run-its-own-loop
    call from inside this already-running loop is illegal (the nested connect
    coroutine is never awaited -> no structured output -> every researcher fails ->
    0 evidence). Critique therefore happens on the normal sync call stack AFTER
    ``asyncio.gather`` returns (see ``run_research_fanout``).

    Concurrency model: if the researcher exposes an async ``research_async`` it is
    awaited directly (it uses the bounded ``AsyncSessionPool`` for its WebSearch
    call, so the cap = MAX_CONCURRENT bounds parallel `claude` spawns). Otherwise
    (deterministic stub / sync brain) the sync ``research`` runs in a worker thread
    via ``asyncio.to_thread`` so independent issues still overlap.
    """
    proxy = _build_worker_proxy(rs, issue_id)
    researcher = brains.researcher
    if hasattr(researcher, "research_async"):
        bundle = await researcher.research_async(proxy, issue_id, pool=pool)
    else:
        bundle = await asyncio.to_thread(researcher.research, proxy, issue_id)
    return bundle


def run_research_fanout(rs: ResearchState, selected: list[str], brains, *,
                        now: str = "t", llm: str = "mock") -> list:
    """Run the K selected issues' researchers CONCURRENTLY (one event loop, bounded
    by the MAX_CONCURRENT semaphore) and return their EvidenceBundles in STABLE
    issue-id order (the selection order) regardless of finish order.

    Two-phase by design (concurrency bug fix): the ASYNC phase (WebSearch fan-out)
    runs purely inside one ``asyncio.run`` loop; the SYNC critique phase
    (``source_critic.review`` + ``compressor.compress``) runs SEQUENTIALLY AFTER
    that loop has fully returned, on the normal sync call stack. This guarantees no
    sync run-its-own-loop LLM call (``ClaudeSession.run_until_complete`` /
    ``call_structured``'s ``asyncio.run``) ever executes inside the running fan-out
    loop — which would otherwise never await the nested connect coroutine and
    yield 0 evidence. The critique brains are fast/cheap, so sequential is fine.

    A researcher that raises is skipped (its issue produces no bundle) but does NOT
    break the others and does NOT leak a pool permit — the gather collects
    exceptions per-task via ``return_exceptions=True``. A critique brain that raises
    on one bundle likewise drops only that bundle.
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
        # Stable order = selection order; drop the researchers that raised.
        raw_bundles = []
        for iid, res in zip(selected, results):
            if isinstance(res, Exception):
                continue
            raw_bundles.append(res)
        return raw_bundles

    # Phase 1 (async): WebSearch fan-out, one event loop, fully drained here.
    raw_bundles = asyncio.run(_run())

    # Phase 2 (sync): critique each surviving bundle on the normal sync call stack
    # — OUTSIDE any running event loop — so the sync run-its-own-loop brains are
    # legal. A brain that raises on one bundle drops only that bundle.
    bundles = []
    for bundle in raw_bundles:
        try:
            bundle = brains.source_critic.review(bundle)
            # P4b Component 2: two-altitude source ranking AFTER research/critique,
            # BEFORE compress — heuristic dedup/junk/top-k (+ opt-in LLM curator),
            # re-pruning claim refs to surviving sources.
            from .ranking import pipeline as _ranking
            bundle = _ranking.apply(bundle)
            bundle = brains.compressor.compress(bundle)
        except Exception:  # noqa: BLE001 - one bad critique never kills the batch
            continue
        bundles.append(bundle)
    return bundles


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


def _persist_ai_sources(rs: ResearchState, bundle: EvidenceBundle, base_dir) -> None:
    """Component B: save each source in ``bundle`` as a durable note in the
    per-topic reference store, and pre-mark its dedup key processed so the same-run
    scan does not re-ingest it (it is already web evidence this run). Best-effort:
    a write failure must never break the loop."""
    try:
        from .brains.reference_store import save_source_note
        from .brains.internal_doc import _dedup_key
        for src in bundle.sources:
            note_path = save_source_note(rs, src, base_dir=str(base_dir))
            key = _dedup_key(note_path)
            if key not in rs.processed_references:
                rs.processed_references.append(key)
    except Exception:  # noqa: BLE001 - reference-store write must never crash the loop
        logger.warning("AI-source reference-store write failed; loop continues",
                       exc_info=True)


# P9 §C — deterministic cell classification after exhaustion. The LLM only
# EXTRACTED claims; here code decides covered / partial / na(public-exhausted) /
# blocked(needs_internal) per cell, NEVER a lazy LLM N/A.
_GATED_MARKERS = ("login", "log in", "sign in", "sign-in", "register", "myicp",
                  "request access", "restricted", "nda", "401", "403")


def _norm_text(s: str) -> str:
    """Lowercase, fold underscores to spaces, squeeze whitespace — so a
    success-criterion field name like ``packet_buffer`` matches ``packet buffer``."""
    return " ".join(str(s).lower().replace("_", " ").split())


def _gated_signal(src) -> bool:
    """True iff a source looks login/registration/NDA-gated (code-detected), which
    is the ONLY thing that justifies classifying a cell needs_internal."""
    blob = _norm_text(f"{src.url or ''} {src.excerpt or ''}")
    return any(m in blob for m in _GATED_MARKERS)


def classify_grid_cells(rs: ResearchState) -> None:
    """P10a/P10b — deterministic per-cell status from observations, plus delta
    bookkeeping (last_status/last_filled/stalled_cycles) and a per-cycle
    `grid_moved` list for the dashboard. Cells with no evidence are left untouched."""
    grid = rs.task_grid
    if grid is None:
        return
    moved: list[str] = []
    for cell in grid.cells.values():
        bundles = [b for b in rs.evidence if b.issue_id == cell.id]
        if not bundles:
            continue
        syn = cell_synthesis.synthesize_cell(cell, bundles)
        gated = any(_gated_signal(s) for b in bundles for s in b.sources)
        exhausted = any(b.public_exhausted for b in bundles)
        new_status = cell_exhaustion.classify_cell(
            cell, filled=syn.filled, gated_detected=gated, public_exhausted=exhausted)
        new_filled = len(syn.filled)
        changed = (new_status != cell.last_status) or (new_filled != cell.last_filled)
        cell.status = new_status
        cell.stalled_cycles = 0 if changed else cell.stalled_cycles + 1
        cell.last_status = new_status
        cell.last_filled = new_filled
        if changed:
            moved.append(cell.id)
    rs.obs_prev["grid_moved"] = moved


def node_collect(state: GraphState) -> GraphState:
    """Fold worker_results into research_state.evidence and advance issue status."""
    rs = state["research_state"]
    now = state.get("now", "t")
    prereqs = dict(state.get("prereqs", {}))
    base_dir = state.get("base_dir", "runs")
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
        # Component B: persist each AI-collected source as a durable note in the
        # per-topic reference store (reference/sources/<sid>.md). The source is
        # ALREADY web evidence this run, so pre-mark its note's dedup key processed
        # so the same-run scan does not re-ingest it as internal evidence; a future
        # RE-RUN (fresh processed_references) accumulates it from the store.
        _persist_ai_sources(rs, bundle, base_dir)
    # P5c: scan the per-run reference drop folder for NEW human-supplied documents
    # (PDF/Word/PPT/Excel/HTML/Markdown), convert + fold them into evidence as
    # internal-origin bundles. Dedup by name+mtime so each file is processed once.
    # Best-effort: a scan failure must never break the loop (observability/intake).
    try:
        from .brains.internal_doc import scan_reference_folder
        for ref_bundle in scan_reference_folder(rs, base_dir=str(base_dir)):
            rs.evidence.append(ref_bundle)
    except Exception:  # noqa: BLE001 - reference intake must never crash the loop
        logger.warning("reference-folder scan failed; loop continues", exc_info=True)
    prereqs["source_confidence_checked"] = True
    # P9 §C: classify each researched cell deterministically from its evidence
    # (covered/partial/na/blocked) — code decides, never a lazy LLM N/A.
    classify_grid_cells(rs)
    _report(state, "research", _obs.render_research, rs)
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
    _report(state, "critique", _obs.render_critique, rs)
    return {"research_state": rs, "prereqs": prereqs}


def node_albert_audit(state: GraphState) -> GraphState:
    rs = state["research_state"]
    prereqs = dict(state.get("prereqs", {}))
    now = state.get("now", "t")
    audit = _brains(state).auditor.audit(rs)
    rs.last_audit = audit
    # Record challenges into the challenge map via UPSERT (P4b convergence): a
    # re-raised challenge MERGES onto its prior id (status/current_answer/evidence/
    # rounds_seen) instead of minting a duplicate, so the adversarial dialogue
    # carries forward and can converge.
    from .artifacts import challenge_map
    from .decision import convergence
    for ch in audit.challenges:
        merged = challenge_map.upsert(
            rs, challenge=ch.challenge,
            why_albert_would_ask=ch.why_albert_would_ask or None,
            current_answer=ch.current_answer or None,
            status=ch.status, classification=ch.classification,
            confidence=ch.confidence or None,
            evidence_refs=list(ch.evidence_refs) or None,
            issue_id=ch.issue_id,
        )
        # An answered challenge backed by evidence is CONVERGED -> resolved (the
        # loop's deterministic promotion; the auditor only marks 'answered').
        if (merged.status == ChallengeStatus.answered and merged.evidence_refs):
            merged.status = ChallengeStatus.resolved
    convergence.record_signal(rs)
    for n in rs.issue_map.values():
        n.last_audited = now
    prereqs["albert_audit_ran"] = True
    if audit.questions_albert_would_ask_next:
        prereqs["pending_questions_extracted"] = True
    else:
        # No further questions means the auditor extracted/closed them.
        prereqs["pending_questions_extracted"] = True
    # P5b: stream Albert's FULL output (the debate core) + the convergence tally.
    _report(state, "albert_audit", _obs.render_albert, audit)
    _report(state, "convergence", _obs.render_convergence, rs)
    return {"research_state": rs, "prereqs": prereqs}


def _grid_signature(rs) -> str:
    grid = getattr(rs, "task_grid", None)
    if grid is None:
        return ""
    return "|".join(f"{c.id}:{c.status}" for c in sorted(grid.cells.values(), key=lambda x: x.id))


def node_plan_audit(state: GraphState) -> GraphState:
    """P8 §3 ②(b) — Albert audits the PLAN (flash). Skipped when the grid is
    unchanged from the last audited signature."""
    rs = state["research_state"]
    sig = _grid_signature(rs)
    last = state.get("_last_plan_sig")
    if sig and sig == last:
        _report(state, "plan_audit", _obs.render_plan_audit, rs)
        return {"research_state": rs}
    brains = _brains(state)
    auditor = getattr(brains, "auditor", None)
    if auditor is not None:
        audit = auditor.audit(rs)
        if audit is not None:
            rs.last_audit = audit
    # Record the signature back onto the input state so a same-dict re-call
    # (the synchronous run_loop / test path) sees it and skips; ALSO return it
    # as a channel update for the checkpointed LangGraph path.
    state["_last_plan_sig"] = sig
    _report(state, "plan_audit", _obs.render_plan_audit, rs)
    return {"research_state": rs, "_last_plan_sig": sig}


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
    # P4b: override the advisory albert_challenge_readiness with the DETERMINISTIC
    # resolved-vs-open ratio from the challenge map (the loop's stop control reads
    # this axis), so readiness honestly reflects convergence.
    if rs.albert_challenge_map:
        score.albert_challenge_readiness = convergence.albert_challenge_readiness(rs)
    rs.readiness_score = score
    s = (score.albert_challenge_readiness + score.decision_readiness
         + score.research_exhaustion_readiness + score.human_bottleneck_clarity)
    rs.readiness_history.append({"sum": s, "iteration": rs.iteration_count})
    rs.iteration_count += 1
    _report(state, "readiness", _obs.render_readiness, score)
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


# --------------------------------------------------------------------------- #
# P3 Human Steering Layer (H1/H2/H3/H5/H6) — gate nodes
# --------------------------------------------------------------------------- #
def _pending_pull(rs: ResearchState) -> dict | None:
    """Return the oldest unconsumed ``request_pull`` steering event, or None."""
    for e in rs.steering_events:
        if e.get("kind") == "request_pull" and not e.get("consumed"):
            return e
    return None


def _build_pull_payload(rs: ResearchState, decision: Decision) -> dict:
    """Compose the §9.1 human-pull ask payload from a pending request_pull event,
    falling back to a generic decision ask when none is queued."""
    ev = _pending_pull(rs)
    if ev is not None:
        return {
            "context": ev.get("context", ""),
            "why": ev.get("why", ""),
            "options": list(ev.get("options", ["A", "B", "C"])),
            "ai_recommendation": ev.get("ai_recommendation", ""),
            "impact_per_option": dict(ev.get("impact_per_option", {})),
            "default_if_no_response": ev.get("default_if_no_response", ""),
        }
    # Generic fallback (audit-driven pull): minimal but complete shape.
    return {
        "context": f"研究方向需人類定奪（{rs.original_question}）",
        "why": "決策準則不明或多條高影響路徑互斥",
        "options": ["A: 採用 AI 建議", "B: 改變方向", "C: 暫停等更多資訊"],
        "ai_recommendation": "A",
        "impact_per_option": {},
        "default_if_no_response": rs.fallback_behavior_if_human_unavailable or "A",
    }


def _record_pull_answer(rs: ResearchState, payload: dict, answer) -> None:
    """Record a resumed human answer + consume the request_pull event."""
    if isinstance(answer, dict):
        choice = answer.get("choice")
        text = answer.get("answer", "")
    else:
        choice = answer
        text = str(answer) if answer is not None else ""
    rs.steering_events.append({
        "kind": "pull_answer",
        "choice": choice,
        "answer": text,
        "for_context": payload.get("context", ""),
    })
    ev = _pending_pull(rs)
    if ev is not None:
        ev["consumed"] = True


def node_human_pull(state: GraphState) -> GraphState:
    """H1/H2/H5 pull gate.

    INTERACTIVE: always ``interrupt(payload)`` — pause the run; the CLI prints the
    ask and exits; ``cos resume`` resumes via ``Command(resume=...)``.

    AUTO: classify the pull. ``low`` → apply ``default_if_no_response`` and record
    a ``steering_event(auto-default)`` (no interrupt, the loop continues). ``high``
    → still ``interrupt`` (hard-stop — never burn overnight on a wrong high-impact
    direction).

    The value returned by ``interrupt`` (the human's answer, supplied via
    ``Command(resume=...)``) is recorded as a ``pull_answer`` steering event and
    flows into the next iteration's decision.
    """
    rs = state["research_state"]
    mode = state.get("mode", rs.mode or "interactive")
    payload = _build_pull_payload(rs, Decision.pull_human)

    if mode == "auto" and risk.classify_pull(rs, Decision.pull_human) == "low":
        default = payload.get("default_if_no_response", "")
        rs.steering_events.append({
            "kind": "auto-default",
            "choice": default,
            "answer": default,
            "for_context": payload.get("context", ""),
        })
        ev = _pending_pull(rs)
        if ev is not None:
            ev["consumed"] = True
        return {"research_state": rs}

    # interactive, or auto+high → pause for a real human answer.
    answer = interrupt(payload)
    _record_pull_answer(rs, payload, answer)
    return {"research_state": rs}


def node_human_push(state: GraphState) -> GraphState:
    """H3 push-human gate (NON-blocking, **Test 2**).

    Create a §9.2 ``HumanTask`` for the residual blocker, mark the blocking issue
    ``blocked_by_internal_data`` (so the supervisor skips it), and CONTINUE — the
    loop researches an adjacent non-blocked branch. No interrupt.
    """
    rs = state["research_state"]
    now = state.get("now", "t")
    # Pick the highest-impact still-addressable issue that needs internal data as
    # the one to hand off. ``coverage_gaps`` mentioning 內部資料 is the P2b signal;
    # fall back to the highest-impact open issue.
    target = None
    for n in sorted(rs.issue_map.values(), key=lambda x: x.impact, reverse=True):
        if n.status in (IssueStatus.open, IssueStatus.researching,
                        IssueStatus.partially_answered, IssueStatus.low_confidence):
            target = n
            break
    if target is not None:
        tid = "HT-%03d" % (len(rs.human_tasks) + 1)
        rs.human_tasks[tid] = HumanTask(
            id=tid,
            task_title=f"提供內部資料：{target.title}",
            owner=None,
            requested_input="內部資料 / 受限文件",
            why_needed=f"問題「{target.title}」需要外部研究無法取得的內部資料",
            blocking_question=target.title,
            priority=target.impact,
            can_continue_without_it=True,
            fallback_plan="先研究相鄰未受阻的問題，待人類回填內部資料後再續",
            status=HumanTaskStatus.open,
        )
        issue_map.set_status(rs, target.id, IssueStatus.blocked_by_internal_data, now=now)
        if "已建立 HumanTask（內部資料）" not in target.human_blockers:
            target.human_blockers.append("已建立 HumanTask（內部資料）")
    return {"research_state": rs}


def node_deep_audit(state: GraphState) -> GraphState:
    """Tier 2 deep audit — runs ONLY at this deterministic gate (before
    synthesize/terminal via human_review, or before a HIGH-risk human_pull).

    In P3 the deep auditor is still the simulator/stub (real Albert FSM = P6); the
    point of this node is the GATE PLACEMENT — the expensive audit runs only where
    the cost matters, never on a mid-loop ``continue``. The mid-loop sentinel
    (``node_albert_audit``) is unchanged and still runs every iteration.
    """
    rs = state["research_state"]
    brains = _brains(state)
    deep = getattr(brains, "deep_auditor", None)
    if deep is None:
        return {"research_state": rs}
    audit = deep.audit(rs)
    rs.last_audit = audit
    rs.deep_audit_count = (getattr(rs, "deep_audit_count", 0) or 0) + 1
    return {"research_state": rs}


def _route_after_deep_audit(state: GraphState) -> str:
    """Deep audit feeds either the high-risk pull gate or the H6 review seam,
    depending on what decision triggered it."""
    decision = state.get("last_decision", Decision.continue_research)
    if decision == Decision.pull_human:
        return "human_pull"
    return "human_review"


def _build_and_gate_memo(state: GraphState, rs: ResearchState) -> None:
    """P5: assemble the §22 decision-memo (LLM synthesis prose + deterministic
    structure + wired-in P4b citation), run the four emission gates, and store the
    rendered memo onto ``rs.final_memo``. A refused memo is stored too (with its
    refusal banner) so the human sees WHY it did not emit. No-op if no synthesizer
    is wired (older brain bundles)."""
    from .synthesis.gates import check_emission
    from .synthesis.memo import assemble_memo, render_memo
    brains = _brains(state)
    synth = getattr(brains, "synthesizer", None)
    if synth is None:
        return
    memo = assemble_memo(rs, synth)
    # Component C: a HARD-cap stop emits the current findings (degraded-but-honest)
    # even if the readiness/completeness target is not met — treat the cap stop as
    # an explicit emit so the deliverable is still produced (the CORRECTNESS gates,
    # degraded-audit + citation, still apply; explicit only skips COMPLETENESS).
    explicit = bool(state.get("explicit_emit", False)) or bool(rs.stop_reason)
    check_emission(rs, memo, explicit=explicit)
    rs.final_memo = render_memo(memo)
    # P5c Task 3: if the confidence policy routed any unverified-CRITICAL claim to
    # needs_supplement (HumanTask created in assemble_memo), NOTIFY the user (email)
    # and CONTINUE — never block/pause. Idempotent: an item already notified this
    # run is not re-emailed (a notify-supplement steering event records the keys).
    _notify_needs_supplement(state, rs, memo)


# A supplement-notify marker in steering_events means this run has ALREADY emailed
# the user once. We email AT MOST ONCE PER RUN — never per-iteration: a hard topic
# full of unverifiable specs produces new unverified-critical items every iteration,
# which would otherwise flood the inbox (observed 2026-06-03 on the switch-PK dogfood).
_NOTIFY_EVENT_KIND = "notify-supplement"


def _supplement_email_sent(rs: ResearchState) -> bool:
    return any(e.get("kind") == _NOTIFY_EVENT_KIND for e in rs.steering_events)


def is_internal_data_task(t) -> bool:
    """True iff ``t`` is an H3 ``node_human_push`` internal-data ask. The robust
    signal is textual: ``node_human_push`` builds the task with
    ``requested_input='內部資料 / 受限文件'``, ``task_title='提供內部資料：…'`` and a
    ``why_needed`` mentioning 內部資料 — i.e. the substring ``內部`` appears across its
    user-facing fields. (HumanTask has no issue link, so 內部 is the reliable marker.)
    Only OPEN tasks are still outstanding; done/cancelled ones are not re-emailed."""
    if t.status != HumanTaskStatus.open:
        return False
    blob = f"{t.requested_input}\n{t.why_needed}\n{t.task_title}"
    return "內部" in blob


def _mint_blocked_cell_tasks(rs: ResearchState) -> None:
    """For each task-grid cell the exhaustion gate marked ``blocked`` (= needs_internal),
    ensure a deterministic HumanTask exists ("提供內部資料：<vendor> <spec_group>").
    Idempotent by id so re-running across iterations never mints duplicates."""
    grid = rs.task_grid
    if grid is None:
        return
    for cell in grid.cells.values():
        if cell.status != CellStatus.blocked:
            continue
        tid = f"HT-CELL-{cell.id}"
        if tid in rs.human_tasks:
            continue
        rs.human_tasks[tid] = HumanTask(
            id=tid,
            task_title=f"提供內部資料：{cell.vendor} {cell.spec_group}",
            owner=None,
            requested_input="內部資料 / 受限文件",
            why_needed=(f"{cell.vendor} {cell.spec_group} 的公開資料已窮盡（程式判定），"
                        "需內部 / 受限文件才能補齊此格規格。"),
            blocking_question=cell.objective,
            priority=5,
            can_continue_without_it=True,
            fallback_plan="先繼續其他 cell；此格僅列於『需內部資料』，不以推測填補。",
            status=HumanTaskStatus.open,
        )


def _notify_needs_supplement(state: GraphState, rs: ResearchState, memo) -> None:
    """Email the user AT MOST ONCE PER RUN with a CONSOLIDATED supplement heads-up
    (P8 §5) covering BOTH kinds in a single email:

      * B-4 needs-supplement: decision-critical claims the citation policy could not
        verify (``memo.needs_supplement``), and
      * H3 internal-data: open ``node_human_push`` HumanTasks that need internal /
        restricted data external research cannot reach.

    Deduped by HumanTask ``id``. NOT one email per iteration — the full, growing list
    lives in the HumanTasks (`cos show <run_id>`) and the §22 memo's
    Required-Human-Decisions / What-We-Cannot-Say sections. Fail-soft (the notifier
    never raises); the loop always continues."""
    items_text = list(getattr(memo, "needs_supplement", []) or [])
    # P9 §C: cells the exhaustion gate marked `blocked` (= needs_internal) drive a
    # supplement ask — public modalities are code-proven exhausted, only internal/
    # restricted data can fill them. Mint one HumanTask per blocked cell (deduped by
    # a deterministic id, idempotent across iterations). These carry 內部 in their
    # fields, so the H3 scan below folds them into the once-per-run email.
    _mint_blocked_cell_tasks(rs)
    # B-4: unverified-critical claims routed to needs_supplement map back to the
    # HumanTask(s) whose requested_input is one of those texts.
    b4_tasks = [t for t in rs.human_tasks.values() if t.requested_input in items_text]
    # H3: open internal-data HumanTasks created by node_human_push.
    h3_tasks = [t for t in rs.human_tasks.values() if is_internal_data_task(t)]
    # Consolidate, deduped by id (a task could match both signals).
    tasks: list = []
    seen: set[str] = set()
    for t in b4_tasks + h3_tasks:
        if t.id not in seen:
            seen.add(t.id)
            tasks.append(t)
    if not tasks:
        return
    if _supplement_email_sent(rs):
        return  # already emailed once this run — do NOT re-flood the inbox
    base_dir = state.get("base_dir", "runs") if isinstance(state, dict) else "runs"
    notify_supplement_needed(rs.run_id, tasks, base_dir=str(base_dir))
    rs.steering_events.append({"kind": _NOTIFY_EVENT_KIND, "items": items_text})


def node_human_review(state: GraphState) -> GraphState:
    """H6 final-review seam: ``interrupt`` before synthesize/terminal.

    P5: this is where the §22 decision-memo is assembled + gated (the four emission
    gates) before the human confirm/revise interrupt. AUTO mode does NOT pause here
    unless a high-risk audit demands it — an overnight auto run is allowed to reach
    a terminal stop and report; the human reviews the produced state afterwards.
    INTERACTIVE pauses for a confirm.
    """
    rs = state["research_state"]
    mode = state.get("mode", rs.mode or "interactive")
    # P5: build + gate the memo at the terminal seam (before the H6 interrupt).
    _build_and_gate_memo(state, rs)
    # H6 interrupt is opt-in (``enable_h6``): the P1 ``run_loop`` (no checkpointer)
    # must reach a terminal stop without pausing, so the default is pass-through.
    # The CLI ``cos run`` (interactive, checkpointed) opts in.
    enable_h6 = state.get("enable_h6", False)
    audit = rs.last_audit
    high_risk = audit is not None and (
        audit.premature_end_risk.value == "high"
        or audit.research_drift_risk.value == "high"
    )
    if not enable_h6:
        return {"research_state": rs}
    if mode == "auto" and not high_risk:
        rs.steering_events.append({"kind": "auto-review-pass",
                                   "answer": "auto 模式略過 H6 確認，直接產出"})
        return {"research_state": rs}
    decision = interrupt({
        "context": "研究已收斂，準備產出最終 memo（P5 stub）",
        "why": "H6：人類最終確認 / 修訂",
        "options": ["confirm: 同意產出", "revise: 退回繼續研究"],
        "ai_recommendation": "confirm",
        "default_if_no_response": "confirm",
    })
    rs.steering_events.append({"kind": "review_decision",
                               "answer": decision if isinstance(decision, str)
                               else (decision or {}).get("answer", "confirm")})
    return {"research_state": rs}


def node_cos_decision(state: GraphState) -> GraphState:
    """Staged binary gates → a single Decision. Pure decision helpers do the logic;
    this node records the result and materializes the auditor-requested branch.

    P5b: after the decision is computed (any of the staged exits), stream the
    `decision` stage block — the COS next action + a rationale — so the colleague
    sees how the debate resolved into an action this round."""
    out = _decide_cos(state)
    decision = out.get("last_decision")
    if decision is not None:
        from .render.markdown import _DECISION_REASON
        rationale = _DECISION_REASON.get(decision, "")
        _report(state, "decision", _obs.render_decision, decision, rationale)
    return out


def _decide_cos(state: GraphState) -> GraphState:
    rs = state["research_state"]
    prereqs = state.get("prereqs", {})
    budget = dict(state.get("branch_budget", {"breadth": DEFAULT_BREADTH, "depth": DEFAULT_DEPTH}))
    now = state.get("now", "t")
    audit = rs.last_audit

    # Stage 0: a pending H4 steering request_pull (or an audit recommending a
    # pull) routes to the human_pull gate (H1/H2/H5). This is checked first so a
    # human's explicit "ask me" outranks the automatic flow.
    if _pending_pull(rs) or (audit is not None
                             and audit.recommended_next_action == Decision.pull_human):
        return {"research_state": rs, "last_decision": Decision.pull_human, "branch_budget": budget}

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
        # P4b: also REFUSE if a high-impact Albert challenge is still unresolved
        # (the adversarial loop has not converged) — force back to research.
        decision = convergence.gate_emission(rs, decision)
        return {"research_state": rs, "last_decision": decision, "branch_budget": budget}

    # Stage 4: auditor recommends synthesize (addressable saturated, residual remains)
    # OR plateau detected → synthesize (gated by emission gate).
    if (audit is not None and audit.recommended_next_action == Decision.synthesize) \
            or exhaustion.plateau(rs, window=2):
        decision = gate.assert_audit_ran(rs, Decision.synthesize)
        decision = convergence.gate_emission(rs, decision)
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
    """Route from cos_decision to the next node.

    Terminal/synthesize go through the H6 ``human_review`` seam first (the
    interrupt point before the final memo). A pull routes to ``human_pull`` (H1/
    H2/H5); a push routes to ``human_push`` (H3, non-blocking). branch/rerank
    re-expand; everything else keeps researching.
    """
    rs = state["research_state"]
    decision = state.get("last_decision", Decision.continue_research)
    max_it = state.get("max_iterations", 8)
    # Component C: a HARD cost/wall cap hit ends the run AFTER the current node —
    # record the reason, then wrap up via the deep-audit -> review -> emit path
    # (the findings are still produced; degraded-but-honest). Checked before the
    # decision/ceiling routing so a runaway loop cannot start another iteration.
    if run_cap.cap_hit_now():
        rs.stop_reason = run_cap.cap_reason_now()
        return "deep_audit"
    # HARD iteration ceiling — always wraps up (prevents infinite loops; bounded
    # tests still terminate). Checked BEFORE the E1 override so it always wins.
    if rs.iteration_count >= max_it:
        return "deep_audit"
    # E1 (Task 15): a SOFT early stop (synthesize / terminal) must NOT wrap up while
    # there is still an open high-impact grid cell AND we are under all hard bounds
    # (cap already checked above, ceiling checked above) AND the grid is not
    # converged. "還有可研究的高影響格子就不早停" — keep researching instead.
    decision_is_soft_stop = decision in (Decision.terminal_stop, Decision.synthesize)
    if decision_is_soft_stop:
        researchable = bool(getattr(rs, "task_grid", None)) and bool(
            rs.task_grid.open_high_impact_cells(min_impact=4))
        if researchable and not convergence.grid_converged(rs):
            return "orchestrator_plan"
        return "deep_audit"
    if decision == Decision.pull_human:
        # A HIGH-risk pull runs the deep audit first; a low-risk pull skips it.
        if risk.classify_pull(rs, Decision.pull_human) == "high":
            return "deep_audit"
        return "human_pull"
    if decision == Decision.push_human:
        return "human_push"
    if decision in (Decision.branch, Decision.rerank):
        return "issue_expansion"
    # pause / continue_research → re-plan the grid each cycle (P8 loop head)
    return "orchestrator_plan"


def _route_after_pull(state: GraphState) -> str:
    """After a human_pull (resumed or auto-defaulted): keep researching, unless
    the iteration ceiling is hit → go to the H6 review seam to wrap up."""
    rs = state["research_state"]
    max_it = state.get("max_iterations", 8)
    if run_cap.cap_hit_now():
        rs.stop_reason = run_cap.cap_reason_now()
        return "human_review"
    if rs.iteration_count >= max_it:
        return "human_review"
    # P8: after a human pull, re-plan the grid (loop head) before researching again.
    return "orchestrator_plan"


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
    # P3 Human Steering Layer gate nodes.
    g.add_node("human_pull", node_human_pull)
    g.add_node("human_push", node_human_push)
    g.add_node("deep_audit", node_deep_audit)
    g.add_node("human_review", node_human_review)
    # P8: reusable orchestration head — (re)plan the task grid, plan-audit (flash),
    # then the H7 plan-approval gate, before each research cycle.
    g.add_node("orchestrator_plan", node_orchestrator_plan)
    g.add_node("plan_audit", node_plan_audit)
    g.add_node("plan_approval", node_plan_approval)

    g.add_edge(START, "intake")
    g.add_edge("intake", "scope")
    g.add_node("clarify", node_clarify)
    g.add_edge("scope", "clarify")
    g.add_conditional_edges("clarify", _route_after_clarify,
                            {"clarify": "clarify", "write_brief": "write_brief"})
    # P8: the brief flows into the orchestration head (loop head), not straight
    # into issue_expansion. issue_expansion is now reached ONLY via _route returning
    # "issue_expansion" (branch/rerank).
    g.add_edge("write_brief", "orchestrator_plan")
    g.add_edge("orchestrator_plan", "plan_audit")
    g.add_edge("plan_audit", "plan_approval")
    g.add_edge("plan_approval", "supervisor")
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
        {
            "issue_expansion": "issue_expansion",
            "supervisor": "supervisor",
            "orchestrator_plan": "orchestrator_plan",
            "human_pull": "human_pull",
            "human_push": "human_push",
            "deep_audit": "deep_audit",
        },
    )
    # Deep audit feeds either the high-risk pull gate or the H6 review seam.
    g.add_conditional_edges(
        "deep_audit", _route_after_deep_audit,
        {"human_pull": "human_pull", "human_review": "human_review"},
    )
    # After a pull (resumed / auto-defaulted): keep researching, or wrap up at H6.
    g.add_conditional_edges(
        "human_pull", _route_after_pull,
        {"orchestrator_plan": "orchestrator_plan", "human_review": "human_review"},
    )
    # H3 push-human is NON-blocking: continue an adjacent branch (supervisor).
    g.add_edge("human_push", "supervisor")
    # H6 review is the terminal seam → END (the P5 memo is gated here).
    g.add_edge("human_review", END)
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
    research_source: str = "web",
    albert: str = "sim",
    metrics=None,
    return_metrics: bool = False,
    reporter=None,
    max_cost_usd: float | None = None,
    max_wall_s: float | None = None,
    assume_brief: bool = True,
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
        "research_source": research_source,
        "albert": albert,
        # P8: non-checkpointed synchronous driver cannot pause at H0, so it runs
        # straight through on the given brief (default True).
        "assume_brief": assume_brief,
    }
    # P5b: thread the live-debate reporter (non-JSON-serializable, so only on the
    # non-checkpointed compile_graph() path). None → nodes emit nothing.
    if reporter is not None:
        init["reporter"] = reporter

    # Component C: publish the HARD cap (cost/wall) for the duration of the run so
    # the router can hard-stop AFTER the current node. Non-serializable metrics ride
    # the contextvar (like the reporter), never GraphState.
    cost_cap, wall_cap = run_cap.caps_from_args(max_cost_usd, max_wall_s)
    cap_token = run_cap.publish_cap(metrics, max_cost_usd=cost_cap, max_wall_s=wall_cap)

    # E1 (Task 15): with the soft-early-stop override active, a run keeps researching
    # while an open high-impact grid cell exists (cell coverage is not yet auto-wired,
    # so the grid rarely converges). ``max_iterations`` is the HARD backstop — but
    # LangGraph's own ``recursion_limit`` must sit ABOVE the worst-case node-step count
    # of that many iterations, or it (not the iteration ceiling) would pre-empt the
    # loop with a GraphRecursionError. The loop body is ~13 node-steps/iteration plus a
    # fixed preamble; 50 + 20*max_iterations leaves generous headroom for pull/branch
    # detours so the iteration ceiling always fires first.
    recursion_limit = 50 + 20 * max(1, int(max_iterations))

    def _invoke():
        return app.invoke(init, config={"recursion_limit": recursion_limit})

    try:
        if llm == "real":
            with sdk_client.use_session_pool(metrics=metrics):
                out = _invoke()
        else:
            out = _invoke()
    finally:
        run_cap.reset_cap(cap_token)

    final = out["research_state"]
    save_snapshot(final, base_dir=base_dir)
    if return_metrics:
        return final, metrics
    return final


# --------------------------------------------------------------------------- #
# P3 auto mode + H4 steering
# --------------------------------------------------------------------------- #
def apply_steer(rs: ResearchState, text: str, *, now: str = "t",
                base_dir: str | None = None) -> dict:
    """Append an H4 ``steer`` event to the (checkpointed) state. The next
    iteration's ``node_supervisor`` consumes it and re-ranks toward the steered
    direction. Returns the appended event.

    Component B: a steer answer is ALSO a human contribution to the per-topic
    reference store — when ``base_dir`` is supplied, the answer is written as a
    dated note (``reference/steer/<date>.md``) so ``scan_reference_folder`` picks
    it up as durable material, not just a transient steering_event. Best-effort:
    a write failure never blocks the steer."""
    ev = {"kind": "steer", "text": text, "at": now, "consumed": False}
    rs.steering_events.append(ev)
    rs.updated_at = now
    if base_dir is not None:
        try:
            from .brains.reference_store import save_steer_note
            save_steer_note(rs, text, base_dir=str(base_dir), now=now)
        except Exception:  # noqa: BLE001 - reference-store write must never block steer
            logger.warning("steer reference-store write failed; steer applied",
                           exc_info=True)
    return ev


def _stop_reason(final: ResearchState, decision, *, paused: bool, max_iterations: int):
    """Compose the §8.3/§9.4 stop reason for an auto run."""
    # Component C: a HARD-cap stop is reported first (the run ended on the cap, not
    # on convergence/ceiling). The reason was recorded on the state by the router.
    if getattr(final, "stop_reason", None):
        return ("hard_cap", final.stop_reason)
    if paused:
        return ("hard_stop_high_risk",
                "高風險人類介入點：auto 模式硬停，等待人類回答（可 resume）")
    if decision == Decision.terminal_stop:
        return ("terminal_stop", "研究已窮盡且四項 readiness 達標，正常終止")
    if decision == Decision.synthesize:
        return ("synthesize", "可定址問題已飽和，剩餘為人類/內部資料瓶頸，進入綜整")
    if final.iteration_count >= max_iterations:
        return ("iteration_ceiling",
                f"達到 max_iterations={max_iterations} 上限，停止")
    return ("stopped", "迴圈結束")


def run_auto(
    initial: ResearchState,
    *,
    base_dir,
    max_iterations: int = 8,
    now: str = "t",
    llm: str = "mock",
    research_source: str = "web",
    albert: str = "sim",
    default_priority: str | None = None,
    run_id: str | None = None,
    metrics=None,
    reporter=None,
    max_cost_usd: float | None = None,
    max_wall_s: float | None = None,
    assume_brief: bool = False,
):
    """Overnight AUTO mode (spec §"auto mode" + Test 5).

    Runs the loop WITHOUT pausing on low-risk gates (``human_pull`` applies
    ``default_if_no_response`` + records a ``steering_event(auto-default)``); §8.4
    soft blockers lower confidence and continue, medium blockers spawn a HumanTask
    and continue an adjacent branch (``human_push``), and HARD blockers / high-risk
    pulls hard-stop via ``interrupt`` (resumable even in auto). Uses the
    checkpointed graph so a hard-stop is resumable by ``run_id``.

    Returns a dict::

        {state, paused, ask, decision, reason_kind, stop_reason, run_id}

    ``paused`` True ⇒ a high-risk hard-stop (``ask`` = the pending interrupt
    payload, resumable via ``cos resume <run_id>``); False ⇒ the run reached a
    terminal/synthesize/ceiling stop (``stop_reason`` explains why).
    """
    from .llm import sdk_client
    from .llm.metrics import RunMetrics

    rid = run_id or initial.run_id
    if default_priority and not initial.default_research_priority:
        initial.default_research_priority = default_priority
    initial.mode = "auto"
    if metrics is None:
        metrics = RunMetrics()

    app, _saver, conn = compile_with_checkpoint(os.path.join(str(base_dir), rid))
    cfg = {"configurable": {"thread_id": rid}, "recursion_limit": 200}
    init: GraphState = {
        "research_state": initial,
        "base_dir": str(base_dir),
        "now": now,
        "max_iterations": max_iterations,
        "llm": llm,
        "research_source": research_source,
        "albert": albert,
        "mode": "auto",
        "enable_h6": False,
        # P8: production AFK pauses at the H0 clarify gate unless the caller
        # asserts the brief is already given (default False).
        "assume_brief": assume_brief,
    }

    def _invoke_auto():
        return app.invoke(init, config=cfg)

    # P5b: publish the reporter on the contextvar (the checkpointed path cannot
    # carry it in GraphState). Reset on exit so it never leaks into another run.
    _tok = _REPORTER_CV.set(reporter) if reporter is not None else None
    # Component C: publish the HARD cap (cost/wall) for the duration of the run so
    # the router can hard-stop AFTER the current node (mirrors run_loop).
    cost_cap, wall_cap = run_cap.caps_from_args(max_cost_usd, max_wall_s)
    cap_token = run_cap.publish_cap(metrics, max_cost_usd=cost_cap, max_wall_s=wall_cap)
    try:
        if llm == "real":
            with sdk_client.use_session_pool(metrics=metrics):
                out = _invoke_auto()
        else:
            out = _invoke_auto()
        snap = app.get_state(cfg)
        final = snap.values["research_state"]
        interrupts = out.get("__interrupt__") if isinstance(out, dict) else None
        paused = bool(interrupts) or bool(snap.next)
        ask = interrupts[0].value if interrupts else None
        decision = out.get("last_decision") if isinstance(out, dict) else None
        reason_kind, stop_reason = _stop_reason(
            final, decision, paused=paused, max_iterations=max_iterations)
        save_snapshot(final, base_dir=base_dir)
    finally:
        conn.close()
        run_cap.reset_cap(cap_token)
        if _tok is not None:
            _REPORTER_CV.reset(_tok)

    return {
        "state": final,
        "paused": paused,
        "ask": ask,
        "decision": decision,
        "reason_kind": reason_kind,
        "stop_reason": stop_reason,
        "run_id": rid,
        # P5 soft budget warning: cumulative cost/iter/calls (informational only).
        "metrics": metrics,
    }
