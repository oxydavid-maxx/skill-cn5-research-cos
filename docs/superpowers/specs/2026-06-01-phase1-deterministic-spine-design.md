# Phase 1 — Deterministic Spine + LangGraph Loop (P1 Design Spec)

> Project: **skill-cn5-research-cos** · Package `cn5_research_cos` · CLI `cos`
> Spec date: 2026-06-01 · Supersedes the pre-discussion draft of the same filename.
> Authoritative parents: `docs/spec/PRODUCT-SPEC.md` (§0–30), `docs/spec/flow-diagram.md` (canonical H0–H6 flow), `docs/superpowers/plans/2026-06-01-master-backbone.md` (6-phase backbone).
> O-1 RESOLVED (user 2026-06-01): **LangGraph FSM**.

---

## 1. Goal & scope

**Goal:** the entire research convergence loop runs end-to-end, fully test-covered, **zero LLM, zero cost**. Every "brain" is a deterministic stub behind a stable interface. After P1 you can `cos run` a question and watch the loop iterate → audit → update artifacts → score readiness → decide → **stop for the right reason**, and resume a crashed run.

**In scope (P1):**
1. Repo bootstrap (pyproject, deps, src layout) — git already initialized & pushed.
2. Pydantic v2 data models + Enums.
3. Persistence: LangGraph checkpoint (resume) + human-readable `runs/<run_id>/state.json` snapshot.
4. Three artifacts: Issue Map, Albert Challenge Map, Readiness Board (derived).
5. LangGraph loop wiring all nodes in **flow-diagram order**.
6. Brain interfaces (Protocols) + deterministic stub implementations + injection hook (`--llm mock`).
7. The two borrowed guardrails as deterministic logic: **exhaustion stop model** + **emission/decision gate**.
8. CLI: `cos init / run / show / validate`; Chinese per-iteration summary.
9. Tests incl. **Acceptance Test 1** (premature-stop prevention) and **Test 4** (endless-research prevention).

**Out of scope (P1 → later phases):** real LLM / Claude Agent SDK; real external Albert (`skill-cn5-i-am-albert`); real research engines; interactive human waiting + auto mode (H0–H6 *interactive*) → P3; final memo / synthesis output → P5. In P1 the decision node may *emit* "pull_human / push_human" decisions and produce the HumanTask/message objects deterministically, but it does **not** block-and-wait for a human.

---

## 2. Tech stack & cross-cutting decisions (all from backbone)

- **Python 3.11+**, `pydantic>=2`, `langgraph`, `langgraph-checkpoint-sqlite` (SqliteSaver), `typer`, `rich`; dev: `pytest`.
- **Enums, not bare str** for all status/type/decision fields.
- **LLM mocking + injection hook:** every brain is a `Protocol`; P1 ships only the deterministic `*Stub` implementation; a factory (`build_brains(llm="mock"|"real")`) selects implementations. P1 only wires `"mock"`. Real brains (P2) bind at the same factory without touching the graph.
- **Readiness Board is derived** from issue/challenge status (pure function), never stored authoritative.
- **Persistence:** LangGraph `SqliteSaver` at `runs/<run_id>/checkpoint.db` keyed by `thread_id=run_id` for resume; PLUS a `save_snapshot(state)` writing `runs/<run_id>/state.json` (pretty) for `cos show`/inspection.
- **Deterministic core / no wall-clock in logic:** timestamps + run_id supplied by the CLI edge, never `datetime.now()` inside nodes/models (keeps tests reproducible).

---

## 3. Package layout after P1

```text
src/cn5_research_cos/
├── __init__.py
├── models.py            # Enums + Pydantic models
├── store.py             # new_run / save_snapshot / load_snapshot
├── graph.py             # LangGraph StateGraph: build_graph(), nodes, edges, router
├── state.py             # GraphState TypedDict + reducers
├── brains/
│   ├── __init__.py      # Protocols + build_brains() factory (injection hook)
│   ├── interfaces.py    # Researcher, SourceCritic, Skeptic, Auditor, Scorer, DecisionMaker, IssueExpander
│   └── stubs.py         # deterministic *Stub implementations (P1)
├── artifacts/
│   ├── __init__.py
│   ├── issue_map.py
│   ├── challenge_map.py
│   └── readiness_board.py   # derive_board(state) -> dict[BoardColumn, list[str]]
├── decision/
│   ├── exhaustion.py    # classify ADDRESSABLE vs RESIDUAL; terminal-stop eligibility
│   └── gate.py          # emission/decision gate: block terminal/synthesize on degraded audit
├── cli.py               # typer app: init / run / show / validate
└── render/
    └── markdown.py      # render issue map / challenge map / board / readiness / iteration summary (Chinese headers)
tests/
├── test_models.py
├── test_artifacts.py
├── test_board_derivation.py
├── test_persistence.py
├── test_exhaustion_and_gate.py
├── test_stop_conditions.py   # Acceptance Test 1 + Test 4
└── test_loop.py
```

(`agents/`, real `workers/`, `prompts/` arrive P2/P4.)

---

## 4. Data models (`models.py`, Pydantic v2)

**Enums (all `str, Enum`):** `IssueType`, `IssueStatus`, `ChallengeStatus`, `HumanTaskStatus`, `BoardColumn`, `SourceType`, `SourceQuality`, `Decision`(continue_research/branch/rerank/pull_human/push_human/synthesize/pause/terminal_stop), `Classification`(addressable/residual), `AuditVerdict`(continue/exhausted/rework).

**Models** (fields per PRODUCT-SPEC §5/§9/§12/§17 + our additions):
- `IssueNode` — id, parent_id, title, description, issue_type:IssueType, status:IssueStatus, impact:int(0–5), confidence:int(0–5), evidence_refs, unknowns, counterarguments, human_blockers, next_actions, last_updated, last_audited.
- `AlbertChallenge` — id, challenge, why_albert_would_ask, current_answer, status:ChallengeStatus, confidence:int(0–5), evidence_refs, missing_info, blocking_owner, next_action, meeting_ready_response, **classification:Classification|None** (addressable/residual — borrowing #7).
- `HumanTask` — id, task_title, owner, requested_input, why_needed, blocking_question, priority, can_continue_without_it:bool, fallback_plan, status:HumanTaskStatus=open.
- `Source` (id,title,url,source_type,quality), `Claim` (claim,source_refs,confidence,notes), `EvidenceBundle` (query,claims,sources,contradictions,missing_evidence,suggested_followups).
- `ReadinessScore` — four 0–5 ints + should_continue:bool + reason:str.
- `AuditResult` — verdict:AuditVerdict, challenges:list[AlbertChallenge], weak_points, premature_end_risk(low/med/high), research_drift_risk, recommended_next_action:Decision|None, rationale, **degraded:bool=False** (True if the audit ran in fallback/error mode — borrowing #8 guard).
- `ResearchState` — run_id, original_question, meeting_context, target_audience, mode, issue_map, albert_challenge_map, evidence, human_tasks, branches, steering_events, readiness_score, iteration_count, last_audit:AuditResult|None, final_memo, created_at, updated_at. (Board is derived, not stored.)

Int bounds via `Field(ge=0, le=5)`. Round-trip `model_validate_json(model_dump_json(x)) == x`.

---

## 5. Brain interfaces + stubs + injection hook (`brains/`)

`interfaces.py` defines `Protocol`s, each a pure function of `ResearchState` → typed result:
- `IssueExpander.expand(state) -> list[IssueNode]`
- `Researcher.research(state, issue_id) -> EvidenceBundle`
- `SourceCritic.review(bundle) -> EvidenceBundle` (annotates source quality/confidence)
- `Skeptic.counter(state, bundle) -> list[str]` (counterarguments / weak points)
- `Auditor.audit(state) -> AuditResult` (the Albert role; in P1 a stub, in P2 the external-skill adapter)
- `Scorer.score(state) -> ReadinessScore`
- `DecisionMaker.decide(state) -> DecisionResult` (`{decision, reason, selected_issue_ids, recommended_next_queries, human_message, default_action_if_no_response}`)

`build_brains(llm: str = "mock") -> Brains` returns a dataclass bundle of the seven. P1 implements only `stubs.py`. **Stub determinism rules (these make Tests 1 & 4 pass):**
- `IssueExpanderStub`: from the question seed a fixed root set (root_question + intent + roi + risk). Never invents a `competitor` node automatically (so Test 1 can detect its absence).
- `ResearcherStub`: returns a canned `EvidenceBundle` per issue_id (deterministic claims/sources); after a configured round it returns the SAME bundle (repetitive — feeds Test 4 saturation).
- `AuditorStub` (the Albert stub): **rule** — if no IssueNode has `issue_type==competitor` → emit one `AlbertChallenge(challenge="競品是否已有此能力?", classification=ADDRESSABLE)` with `premature_end_risk=high`, verdict=REWORK; once a competitor node exists and N rounds pass with no new high-impact issue → verdict=EXHAUSTED, premature_end_risk=low.
- `ScorerStub`: deterministic from counts (answered/total etc.).
- `DecisionMakerStub`: implemented via `decision/exhaustion.py` + `decision/gate.py` (see §7), NOT ad-hoc.

---

## 6. LangGraph loop (`graph.py`, `state.py`)

**GraphState** (TypedDict, total=False): `research_state: ResearchState`, `iteration: int`, `rework_attempts: int`, `last_decision: Decision`. Reducers: `_take_last` for scalars; the ResearchState is replaced whole each node (single linear writer per super-step → no parallel write conflict in P1).

**Nodes (functions `(GraphState) -> GraphState`), in canonical flow-diagram order:**
`intake → issue_expansion → select_branch → research_plan → research_worker → evidence_normalize → source_critic → skeptic → albert_audit → artifact_update → readiness_scoring → iteration_summary → cos_decision → [router]`.

**Router** (`add_conditional_edges` after `cos_decision`) maps `last_decision`:
- `continue_research` → `select_branch`
- `branch` / `rerank` → `issue_expansion`
- `pull_human` / `push_human` / `pause` → emit the message/HumanTask into state, then (P1, non-interactive) → `select_branch` (continues a non-blocked branch; records that a human gate WOULD fire — H1/H2/H3/H5 surfaced in the iteration summary)
- `synthesize` / `terminal_stop` → `END`

**Rework cap:** an `albert_audit`→`issue_expansion` REWORK edge is bounded by `rework_attempts <= MAX_REWORK` (env `CN5_COS_MAX_REWORK`, default 2) — borrowed from escape-mrc to prevent infinite Albert loops. `recursion_limit=100` on the run config as a backstop.

**Run/resume:** `cos run` compiles the graph with `SqliteSaver.from_conn_string("runs/<id>/checkpoint.db")`, `config={"configurable":{"thread_id": run_id}, "recursion_limit":100}`. `cos run --resume <id>` invokes with `None` input to replay from the last checkpoint. Each `artifact_update` node also calls `save_snapshot(state)`.

---

## 7. The two borrowed guardrails (deterministic — `decision/`)

**(7) Exhaustion stop model (`exhaustion.py`):**
- `classify(state) ->` tags every open IssueNode + AlbertChallenge as `ADDRESSABLE` (status still self-answerable: open/researching/partially_answered/low_confidence) or `RESIDUAL` (blocked_by_human/internal_data/permission/decision, or challenge needs_internal_data/needs_albert_decision/needs_bu_judgment).
- `terminal_eligible(state) -> bool`: True only when **no ADDRESSABLE item remains** AND readiness targets met (all four ≥ 4) — OR all remaining items are RESIDUAL with a recorded blocker owner. Never on a raw score threshold alone.
- `DecisionMakerStub.decide` uses this: if not `terminal_eligible` and high-value addressable work remains → `continue_research`/`branch`; if addressable exhausted but RESIDUAL blockers remain → `synthesize` (+ surface human tasks); only `terminal_stop` when `terminal_eligible`.

**(8) Emission/decision gate (`gate.py`):**
- `assert_audit_ran(state)`: a `synthesize`/`terminal_stop` decision is **refused** if `state.last_audit is None or state.last_audit.degraded` (audit skipped/errored/mock-degraded). On refusal the loop forces `continue_research` (re-audit) instead, and records the refusal reason. Bypass only via `CN5_COS_EMIT_DESPITE_DEGRADED_AUDIT=1` + reason env (recorded). In P1 the stub audit is never degraded, but the gate + its test exist so P2's real/external Albert cannot silently drive a premature stop.

---

## 8. CLI (`cli.py`, Typer + Rich) + iteration summary

- `cos init --question "..." [--run-id ID] [--mode interactive]` → `new_run`, `save_snapshot`, print run_id.
- `cos run --question "..." [--run-id ID] [--max-iterations N=8] [--resume] [--llm mock]` → build graph, invoke; stream a **Chinese per-iteration summary** after each loop: 本輪新增 / Albert 會挑戰 / 已答 / pending / 需要人 / 下一輪建議 (render/markdown). On stop, print the stop reason + the four readiness scores.
- `cos show <run_id> [--artifact issue|challenge|board|readiness|all]` → load snapshot, render Markdown (Rich).
- `cos validate <run_id>` → load + re-validate; report OK / errors.

CLI supplies `run_id` + ISO timestamps into the core.

---

## 9. Tests

- `test_models.py` — construct each model; JSON round-trip equality; `ge/le` rejection; bad-enum rejection.
- `test_artifacts.py` — issue/challenge add/get/update/list; monotonic ids (`I-001`/`C-001`); status+audit-timestamp update.
- `test_board_derivation.py` — mixed-status → correct columns; back-refs to issue/challenge ids; empty → all-empty.
- `test_persistence.py` — `save_snapshot`→`load_snapshot` equality; LangGraph resume replays from checkpoint (run 2 iterations, kill, resume, assert continues not restarts); missing run_id raises clear error.
- `test_exhaustion_and_gate.py` — `classify` tags ADDRESSABLE/RESIDUAL correctly; `terminal_eligible` false while addressable remains; `assert_audit_ran` refuses terminal/synthesize when `last_audit.degraded=True` and forces continue.
- `test_stop_conditions.py` — **Acceptance Test 1:** question with no competitor node + AuditorStub raises competitor challenge → loop does NOT `terminal_stop`; next decision is continue/branch toward competitor. **Acceptance Test 4:** 3 iterations, no new high-impact issue + repetitive ResearcherStub bundles + remaining items RESIDUAL → decision becomes `synthesize` (+ human task queue), not endless `continue_research`.
- `test_loop.py` — one full `cos run` over the stub graph terminates within `max_iterations`, produces a Chinese iteration summary each round, writes `state.json`, and ends with a populated readiness score + explicit stop reason.

---

## 10. Definition of Done (P1)

1. `pytest` all green (incl. Test 1 + Test 4 + resume test).
2. `cos init --question "AI 能否做隔夜研究"` writes `runs/<id>/state.json`.
3. `cos run --question "..."` visibly loops, prints Chinese per-iteration summaries, updates the three artifacts, scores readiness, and **stops for an explicit, correct reason** (not premature, not endless).
4. `cos run --resume <id>` continues from checkpoint (does not restart).
5. `cos show <id>` renders the three artifacts; `cos validate <id>` reports OK.
6. Committed + pushed to GitHub `main`.

---

## 11. Implementation notes / risks

- **LangGraph + Claude Agent SDK nested-session caveat (#573)** is a P2 concern (no SDK in P1) — note it now so the graph compile/run pattern is SDK-friendly later.
- Keep `ResearchState` JSON-serializable end-to-end (LangGraph checkpoint serde + our snapshot both need it) — no non-serializable objects in state.
- The stub brains' canned data lives in `brains/stubs.py` as small fixtures, not external files, so tests are hermetic.
- `decision/` is pure (no I/O), so the stop logic is unit-testable without running the graph.
