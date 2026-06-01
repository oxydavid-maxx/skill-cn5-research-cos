# Phase 1 — Deterministic Spine: State, Artifacts & Persistence

> Project: **skill-cn5-research-cos** (CN5 Chief-of-Staff Research Agent / BU Research Cockpit)
> Package: `cn5_research_cos`  ·  CLI: `cos`
> Spec date: 2026-06-01
> Source spec: user-provided "Chief-of-Staff Research Agent / BU Research Cockpit" (Sections 0–30)
> LLM backend (later phases): **Claude Agent SDK** (Python)

---

## 0. Where this sits in the overall program

The full product is decomposed into **6 independently-verifiable big plans**. Only Phase 1 is detailed here; later phases get boundaries only and will each get their own spec → plan → execute → verify cycle.

| # | Big Plan | DoD (verification) | Source milestones |
|---|----------|--------------------|-------------------|
| **P1 (this doc)** | Deterministic Spine: State + Artifacts + Persistence | `pytest` green; create/save/load/render a run with **zero LLM** | M1, M2 |
| P2 | Iterative Loop Engine + deterministic decision logic (stub agents) | Acceptance Test 1 (premature-stop prevention), Test 4 (endless-research prevention) | M3, §10, §11, §19 |
| P3 | Albert Thought Agent + real LLM via Claude Agent SDK | Acceptance Test 3 (Albert challenge generation) | M4, §20 |
| P4 | Human Pull/Push + Auto Mode (interrupt/resume HITL) | Acceptance Test 2 (human blocker task), Test 5 (auto mode) | M5, M6, §8, §9 |
| P5 | Research Worker Adapters (stub → GPT Researcher/ODR) | adapter hot-swap, stable interface | M7, §16 |
| P6 | Synthesis + Final Memo (Chinese) | memo only at readiness target; format per §22 | M8, §22 |

**Rationale for the cut:** P1 is a pure deterministic foundation (no LLM, 100% testable). P2 assembles the loop on that foundation but with stub agents (still no API cost, stop-logic fully testable). P3 is the first phase that calls a real LLM. Each layer's failures are isolated, honoring the §14 deterministic-vs-LLM split and the global "Resume, Don't Rerun" discipline.

---

## 1. Phase 1 Goal

A fully test-covered, **zero-LLM** deterministic core. After Phase 1 you can:

- Create a research run from a question.
- Hold and mutate the three living artifacts (Issue Map, Albert Challenge Map, Readiness Board).
- Hold a Human Task queue and Evidence list.
- Manually set/read readiness scores.
- Save, load, and resume run state from disk (`run_id`-keyed checkpoint).
- Render any artifact to Markdown for inspection via the CLI.

Everything in later phases plugs into this spine. No orchestration, no decision logic, no LLM yet.

---

## 2. Design decisions (improvements over the raw spec)

These three deviations from the raw spec are deliberate and carried into Phase 1:

1. **Enums instead of bare `str` for state fields.** `IssueNode.status`, `IssueNode.issue_type`, `AlbertChallenge.status`, decision values, etc. become Pydantic v2 `Enum`s. Free validation; prevents typo-status silent-staleness bugs (wiki: Silent Staleness Pattern, validation principle). The raw spec used `str`.

2. **Persistence / `run_id` / checkpoint in Phase 1**, not deferred. The raw spec defers persistence, but the global "Resume, Don't Rerun" rule mandates `--resume` for all LangGraph FSM skills. Building the checkpoint store first means Phase 2's loop is resumable by construction.

3. **Readiness Board is *derived*, not independently stored.** Board columns are computed from the `status` of Issue Map nodes + Albert Challenge entries. Single source of truth; the board cannot drift out of sync with the artifacts it summarizes. The raw spec modeled the board as a separate `dict[str, list[str]]`; we keep that as a *rendered/derived view*, not stored authoritative state.

---

## 3. Data models (`models.py`, Pydantic v2)

### 3.1 Enums

```python
class IssueType(str, Enum):
    root_question, intent, technical_feasibility, roi, cost, competitor,
    risk, internal_data, human_judgment, decision_criterion,
    source_conflict, unknown_unknown

class IssueStatus(str, Enum):
    open, researching, partially_answered, answered,
    blocked_by_human, blocked_by_internal_data, blocked_by_permission,
    blocked_by_decision, low_confidence, ready_for_synthesis

class ChallengeStatus(str, Enum):
    answered, partially_answered, needs_external_research,
    needs_internal_data, needs_bu_judgment, needs_albert_decision,
    needs_source_validation, blocked

class HumanTaskStatus(str, Enum):
    open, in_progress, resolved, cancelled

class BoardColumn(str, Enum):
    answered, partially_answered, needs_external_research,
    needs_internal_data, needs_bu_judgment, needs_albert_decision,
    needs_source_validation, blocked, ready_for_memo

class SourceType(str, Enum):
    primary, secondary, marketing, blog, paper, internal

class SourceQuality(str, Enum):
    high, medium, low
```

(Enum member spelling is illustrative; implementation will use valid Python identifiers with `str, Enum` mixin so values serialize as their string name.)

### 3.2 Core models

- **`IssueNode`** — `id, parent_id, title, description, issue_type: IssueType, status: IssueStatus, impact: int (0–5), confidence: int (0–5), evidence_refs, unknowns, counterarguments, human_blockers, next_actions, last_updated, last_audited`.
- **`AlbertChallenge`** — `id, challenge, why_albert_would_ask, current_answer, status: ChallengeStatus, confidence: int (0–5), evidence_refs, missing_info, blocking_owner, next_action, meeting_ready_response`.
- **`HumanTask`** — `id, task_title, owner, requested_input, why_needed, blocking_question, priority, can_continue_without_it: bool, fallback_plan, status: HumanTaskStatus = open`.
- **`ReadinessScore`** — `albert_challenge_readiness, decision_readiness, research_exhaustion_readiness, human_bottleneck_clarity (each int 0–5), should_continue: bool, reason: str`.
- **`Source`** — `id, title, url, source_type: SourceType, quality: SourceQuality`.
- **`Claim`** — `claim, source_refs, confidence, notes`.
- **`EvidenceBundle`** — `query, claims: list[Claim], sources: list[Source], contradictions, missing_evidence, suggested_followups` (the §16 research-worker output schema, typed).
- **`ResearchState`** — top-level container per the spec §17, with fields: `run_id, original_question, meeting_context, target_audience, mode, issue_map: list[IssueNode], albert_challenge_map: list[AlbertChallenge], evidence: list[EvidenceBundle], human_tasks: list[HumanTask], branches, steering_events, readiness_score: ReadinessScore | None, iteration_count, final_memo, created_at, updated_at`.

`impact`/`confidence`/readiness ints use `Field(ge=0, le=5)` validation. Timestamps stored as ISO-8601 strings (deterministic; passed in, never `datetime.now()` inside model logic, to keep serialization reproducible in tests).

---

## 4. Artifact managers (`artifacts/`)

Each manager wraps a slice of `ResearchState` with typed CRUD; they never own state, they operate on the passed-in `ResearchState`.

- **`issue_map.py`** — add/get/update/list nodes; id generation (`I-001`…); parent/child traversal; mark status/audit timestamps.
- **`challenge_map.py`** — add/get/update/list challenges; id generation (`C-001`…).
- **`readiness_board.py`** — **derives** `dict[BoardColumn, list[str]]` from current issue + challenge statuses (pure function `derive_board(state) -> dict`). Maps each status → its board column. Items carry back-references to their Issue/Challenge ids (§5.3 requirement).

Status→column mapping is an explicit table in `readiness_board.py` (single place to audit the routing).

---

## 5. Persistence (`store.py` / `state.py`)

- Run dir: `runs/<run_id>/state.json` (configurable base dir).
- `save_state(state, base_dir)` → writes pretty JSON via `model_dump_json`.
- `load_state(run_id, base_dir)` → `ResearchState` via `model_validate_json`.
- `new_run(question, ...)` → fresh `ResearchState` with generated `run_id` (deterministic-friendly: `run_id` passed in or derived from a provided seed/timestamp, **not** `Math.random`/`datetime.now` inside core logic — CLI supplies it).
- Round-trip guarantee: `load(save(state)) == state` (tested).

---

## 6. CLI skeleton (`cli.py`, Typer + Rich)

Phase 1 commands only (no loop yet):

- `cos init --question "..." [--run-id ...] [--mode interactive|auto]` — create + persist a new run; print `run_id`.
- `cos show <run_id> [--artifact issue|challenge|board|all]` — render artifact(s) as Markdown to terminal (Rich).
- `cos validate <run_id>` — load + re-validate state, report OK / validation errors.

CLI supplies timestamps/run_id to core (keeps core deterministic).

---

## 7. Rendering (`render/markdown.py`)

Pure functions: `render_issue_map(state) -> str`, `render_challenge_map(state) -> str`, `render_board(state) -> str`, `render_readiness(state) -> str`. Markdown tables. Chinese labels for headers (per §21 default-Chinese), data values verbatim.

---

## 8. Repo layout after Phase 1

```text
skill-cn5-research-cos/
├── README.md
├── pyproject.toml
├── .gitignore
├── examples/
│   └── albert_ai_research_question.yaml
├── docs/superpowers/specs/2026-06-01-phase1-deterministic-spine-design.md
├── src/cn5_research_cos/
│   ├── __init__.py
│   ├── models.py
│   ├── store.py
│   ├── cli.py
│   ├── artifacts/
│   │   ├── __init__.py
│   │   ├── issue_map.py
│   │   ├── challenge_map.py
│   │   └── readiness_board.py
│   └── render/
│       ├── __init__.py
│       └── markdown.py
└── tests/
    ├── test_models.py
    ├── test_artifacts.py
    ├── test_board_derivation.py
    └── test_persistence.py
```

(Directories `agents/`, `workers/`, `loop.py`, `prompts/` are intentionally **absent** in Phase 1 — they arrive in P2/P3/P5.)

---

## 9. Tests (Phase 1)

- `test_models.py` — construct each model; serialize→deserialize round-trip equality; `Field(ge=0, le=5)` rejects out-of-range; invalid enum string rejected.
- `test_artifacts.py` — issue/challenge add/get/update/list; id generation monotonic; status update + audit timestamp set.
- `test_board_derivation.py` — given a state with mixed statuses, `derive_board` routes each item to the correct column; back-references present; empty state → all-empty columns.
- `test_persistence.py` — `save` then `load` round-trips to an equal `ResearchState`; missing run_id raises a clear error.

---

## 10. Phase 1 Definition of Done

1. `pytest` green (all of §9).
2. `cos init --question "AI 能否做隔夜研究"` creates `runs/<id>/state.json`.
3. `cos show <id>` renders the three artifacts (empty but well-formed) in Chinese-headed Markdown.
4. `cos validate <id>` reports OK.
5. Save→mutate→save→load round-trip equality demonstrated by a test.
6. Repo is its own git repo, connected to `github.com/oxydavid-maxx/skill-cn5-research-cos`, committed and pushed.

---

## 11. Explicitly out of scope for Phase 1

LLM calls of any kind, Claude Agent SDK wiring, the iterative loop / FSM, Chief-of-Staff decision logic, readiness *scoring* logic (only manual set/read), stop conditions, Albert Thought Agent, research workers, auto mode, human pull/push generation logic, synthesis, final memo. All deferred to P2–P6.
