"""LangGraph StateGraph: full §18 node set, concurrent researcher fan-out, staged router.

Canonical order (flow-diagram R2):
  intake -> scope -> write_brief -> issue_expansion -> supervisor
    -> research_fanout (asyncio.gather over top-K issues, each
        research -> source_critic -> compress; bounded by MAX_CONCURRENT) -> collect
    -> skeptic -> albert_audit -> artifact_update -> readiness_scoring
    -> anti_premature -> cos_decision -> router

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
import os
import sqlite3
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .artifacts import issue_map
from .brains import build_brains
from .llm import sdk_client
from .decision import anti_premature, branch_budget, exhaustion, gate, risk
from .models import (Decision, EvidenceBundle, HumanTask, HumanTaskStatus,
                     IssueStatus, IssueType, ResearchState)
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


def node_human_review(state: GraphState) -> GraphState:
    """H6 final-review seam: ``interrupt`` before synthesize/terminal.

    The memo body is P5; here H6 is the wired interrupt point (confirm/revise).
    AUTO mode does NOT pause here unless a high-risk audit demands it — an
    overnight auto run is allowed to reach a terminal stop and report; the human
    reviews the produced state afterwards. INTERACTIVE pauses for a confirm.
    """
    rs = state["research_state"]
    mode = state.get("mode", rs.mode or "interactive")
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
    this node records the result and materializes the auditor-requested branch."""
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
    """Route from cos_decision to the next node.

    Terminal/synthesize go through the H6 ``human_review`` seam first (the
    interrupt point before the final memo). A pull routes to ``human_pull`` (H1/
    H2/H5); a push routes to ``human_push`` (H3, non-blocking). branch/rerank
    re-expand; everything else keeps researching.
    """
    rs = state["research_state"]
    decision = state.get("last_decision", Decision.continue_research)
    max_it = state.get("max_iterations", 8)
    # Terminal / synthesize / iteration-ceiling → run the Tier-2 deep audit, then
    # the H6 review seam, then END.
    if decision in (Decision.terminal_stop, Decision.synthesize) or rs.iteration_count >= max_it:
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
    # pause / continue_research → keep researching
    return "supervisor"


def _route_after_pull(state: GraphState) -> str:
    """After a human_pull (resumed or auto-defaulted): keep researching, unless
    the iteration ceiling is hit → go to the H6 review seam to wrap up."""
    rs = state["research_state"]
    max_it = state.get("max_iterations", 8)
    if rs.iteration_count >= max_it:
        return "human_review"
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
    # P3 Human Steering Layer gate nodes.
    g.add_node("human_pull", node_human_pull)
    g.add_node("human_push", node_human_push)
    g.add_node("deep_audit", node_deep_audit)
    g.add_node("human_review", node_human_review)

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
        {
            "issue_expansion": "issue_expansion",
            "supervisor": "supervisor",
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
        {"supervisor": "supervisor", "human_review": "human_review"},
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
