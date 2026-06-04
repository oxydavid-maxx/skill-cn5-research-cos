# Phase 8 — Socratic clarification + reusable orchestration loop + SOTA quality — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the cockpit do large research the SOTA way — a mandatory multi-round Socratic clarification up front, then a reusable orchestration loop whose head re-decomposes a section-aware task grid every cycle from prior results + Albert challenges + coverage gaps — within an 8h cap and a Sonnet-researcher / Opus-synthesis model tier.

**Architecture:** Insert four new LangGraph nodes (`clarify`, `orchestrator_plan`, `plan_audit`, `plan_approval`) and move the loop head from `supervisor` to `orchestrator_plan`; add `TaskCell`/`TaskGrid` models persisted in the per-topic reference store; add a `clarifier` and `orchestrator` brain; keep every existing node contract intact so P1–P7 stay green. Deterministic core (FSM, grid bookkeeping, gates, caps, email) stays LLM-free; only clarifier/orchestrator/researcher/synthesis are LLM.

**Tech Stack:** Python 3.11/3.12, Pydantic v2, LangGraph (SqliteSaver), Claude Agent SDK, Typer (`cos`), pytest. Windows: `py -3`, `PYTHONPATH=src`.

**Test invocation (every task):** `PYTHONPATH=src py -3 -m pytest -q` (full suite for regression); single test: `PYTHONPATH=src py -3 -m pytest tests/test_x.py::test_y -v`.

**Spec:** `docs/spec/2026-06-04-phase8-socratic-orchestration-quality-design.md`. Build order = riders (1–2) → models (3) → Socratic clarify (4–7) → orchestrator+grid (8–9) → plan-audit+H7 (10–11) → FSM rewire (12) → synthesis+email (13–14) → no-early-stop (15).

---

### Task 1: 8h wall-cap default

**Files:**
- Modify: `src/cn5_research_cos/decision/run_cap.py` (`caps_from_args`, ~line 53)
- Test: `tests/test_hard_run_cap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hard_run_cap.py  (add)
import importlib, os
from cn5_research_cos.decision import run_cap

def test_wall_cap_defaults_to_8h_when_unset(monkeypatch):
    monkeypatch.delenv("CN5_COS_MAX_WALL_S", raising=False)
    monkeypatch.delenv("CN5_COS_MAX_COST_USD", raising=False)
    cost, wall = run_cap.caps_from_args(None, None)
    assert wall == 28800.0          # 8h default
    assert cost is None             # cost stays opt-in

def test_explicit_wall_overrides_default():
    cost, wall = run_cap.caps_from_args(None, 60.0)
    assert wall == 60.0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_hard_run_cap.py::test_wall_cap_defaults_to_8h_when_unset -v`
Expected: FAIL (`wall` is `None`, not `28800.0`).

- [ ] **Step 3: Implement**

In `run_cap.py`, add the default constant and apply it in `caps_from_args` AFTER the env read:

```python
DEFAULT_MAX_WALL_S = 28800.0  # 8 hours — large research runs long (P8 E1)

def caps_from_args(max_cost_usd, max_wall_s):
    cost = max_cost_usd if max_cost_usd is not None else _env_float("CN5_COS_MAX_COST_USD")
    wall = max_wall_s if max_wall_s is not None else _env_float("CN5_COS_MAX_WALL_S")
    if wall is None:
        wall = DEFAULT_MAX_WALL_S
    return cost, wall
```

- [ ] **Step 4: Run to verify pass** — `PYTHONPATH=src py -3 -m pytest tests/test_hard_run_cap.py -v` → PASS.
- [ ] **Step 5: Full suite** — `PYTHONPATH=src py -3 -m pytest -q` → green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): default wall cap to 8h (E1)"`

---

### Task 2: Model tier — Sonnet researcher, Opus synthesis

**Files:**
- Modify: `src/cn5_research_cos/llm/sdk_client.py:79` (`DEFAULT_MODEL`)
- Modify: `src/cn5_research_cos/brains/synthesis.py:115` (`call_structured(..., model="haiku")`)
- Test: `tests/test_model_tier.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_model_tier.py  (create)
import cn5_research_cos.brains.synthesis as syn
from cn5_research_cos.llm import sdk_client

def test_default_model_is_sonnet():
    assert sdk_client.DEFAULT_MODEL == "claude-sonnet-4-6"

def test_synthesizer_uses_opus(monkeypatch):
    captured = {}
    def fake_call(system, user, schema, *, model=None, **kw):
        captured["model"] = model
        return {k: "" for k in syn.ALL_OUTPUT_KEYS}
    monkeypatch.setattr(syn, "call_structured", fake_call)
    from cn5_research_cos.models import ResearchState
    syn.RealSynthesizer().write_sections(ResearchState(run_id="r", original_question="q"))
    assert captured["model"] == "claude-opus-4-8"
```

- [ ] **Step 2: Verify fail** — `PYTHONPATH=src py -3 -m pytest tests/test_model_tier.py -v` → FAIL (still "haiku").
- [ ] **Step 3: Implement**

`sdk_client.py:79`:
```python
DEFAULT_MODEL = os.environ.get("CN5_COS_LLM_MODEL", "claude-sonnet-4-6")
```
`brains/synthesis.py:115`:
```python
        raw = call_structured(_SYSTEM, user, _SCHEMA, model="claude-opus-4-8")
```

- [ ] **Step 4: Verify pass** — `PYTHONPATH=src py -3 -m pytest tests/test_model_tier.py -v` → PASS.
- [ ] **Step 5: Regression — prompt-cache + any haiku assertions.** Run `PYTHONPATH=src py -3 -m pytest tests/test_prompt_caching.py tests/test_sdk_client.py tests/test_synthesizer.py -q`. If any test asserts the literal `"haiku"`, update it to the new tier ONLY where it asserts the default model (do not weaken behavioral assertions). Then full suite `PYTHONPATH=src py -3 -m pytest -q` → green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): model tier — Sonnet researcher / Opus synthesis (E2)"`

---

### Task 3: State fields + TaskCell / TaskGrid models

**Files:**
- Modify: `src/cn5_research_cos/models.py` (`ResearchState` ~line 305; add new classes near `IssueNode`)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py  (add)
from cn5_research_cos.models import ResearchState, TaskCell, TaskGrid, CellStatus

def test_research_state_has_p8_fields():
    rs = ResearchState(run_id="r", original_question="q")
    assert rs.decision_criterion is None
    assert rs.success_form is None
    assert rs.clarify_converged is False
    assert rs.task_grid is None

def test_task_grid_cells_and_coverage():
    grid = TaskGrid(axes=["vendor", "spec_group"])
    grid.cells["NXP|fabric"] = TaskCell(
        id="NXP|fabric", vendor="NXP", spec_group="fabric",
        objective="拉齊 NXP switch fabric 規格", status=CellStatus.open, impact=5)
    assert grid.open_high_impact_cells(min_impact=4)[0].id == "NXP|fabric"
    grid.cells["NXP|fabric"].status = CellStatus.covered
    assert grid.open_high_impact_cells(min_impact=4) == []
```

- [ ] **Step 2: Verify fail** — `PYTHONPATH=src py -3 -m pytest tests/test_models.py::test_task_grid_cells_and_coverage -v` → FAIL (ImportError).
- [ ] **Step 3: Implement** — in `models.py`:

```python
class CellStatus(str, Enum):
    open = "open"
    partial = "partial"
    covered = "covered"
    blocked = "blocked"      # NDA / internal-only
    na = "na"                # no public data exists

class TaskCell(BaseModel):
    id: str                                  # f"{vendor}|{spec_group}" (or |part| for 3-axis)
    vendor: str
    spec_group: str
    part_number: str | None = None
    objective: str
    output_format: str = ""                  # the report row/section shape
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
```

Add to `ResearchState` (after `research_brief`, ~line 307):
```python
    decision_criterion: str | None = None      # P8 H0: what decision this feeds
    success_form: str | None = None            # P8 H0: the deliverable shape
    clarify_converged: bool = False            # P8 H0: 4-criterion gate passed
    task_grid: TaskGrid | None = None          # P8 §4: section-aware grid
```

- [ ] **Step 4: Verify pass** — `PYTHONPATH=src py -3 -m pytest tests/test_models.py -v` → PASS.
- [ ] **Step 5: Persistence regression** — `PYTHONPATH=src py -3 -m pytest tests/test_persistence.py -q` (state.json round-trips the new fields). Full suite green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): TaskCell/TaskGrid + H0 state fields"`

---

### Task 4: Socratic 4-criterion convergence

**Files:**
- Create: `src/cn5_research_cos/decision/clarify.py`
- Test: `tests/test_clarify_convergence.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clarify_convergence.py  (create)
from cn5_research_cos.decision import clarify
from cn5_research_cos.models import ResearchState

def _rs(**kw):
    rs = ResearchState(run_id="r", original_question="q")
    for k, v in kw.items(): setattr(rs, k, v)
    return rs

def test_not_converged_when_any_criterion_missing():
    rs = _rs(decision_criterion="RFQ scoring", success_form="PK table")
    # scope + constraints still unset
    ok, missing = clarify.clarify_converged(rs)
    assert ok is False
    assert "scope" in missing and "constraints" in missing

def test_converged_when_all_four_pinned():
    rs = _rs(decision_criterion="RFQ scoring", success_form="PK table",
             research_brief="scope: silicon only; out: gateway apps",
             fallback_behavior_if_human_unavailable="public-only, NDA out")
    ok, missing = clarify.clarify_converged(rs)
    assert ok is True and missing == []
```

- [ ] **Step 2: Verify fail** — run the test → FAIL (ImportError).
- [ ] **Step 3: Implement** — `decision/clarify.py`:

```python
"""P8 H0 — the 4-criterion Socratic clarification convergence gate (deterministic)."""
from __future__ import annotations
from ..models import ResearchState

CRITERIA = ("purpose", "scope", "success", "constraints")

def _has_purpose(rs: ResearchState) -> bool:
    return bool(rs.decision_criterion)
def _has_scope(rs: ResearchState) -> bool:
    return bool(rs.research_brief)            # the brief carries scope in/out
def _has_success(rs: ResearchState) -> bool:
    return bool(rs.success_form)
def _has_constraints(rs: ResearchState) -> bool:
    return bool(rs.fallback_behavior_if_human_unavailable)

_CHECKS = {"purpose": _has_purpose, "scope": _has_scope,
           "success": _has_success, "constraints": _has_constraints}

def clarify_converged(rs: ResearchState) -> tuple[bool, list[str]]:
    """Return (converged, missing_criteria). Converged iff all 4 are pinned."""
    missing = [c for c in CRITERIA if not _CHECKS[c](rs)]
    return (not missing, missing)
```

- [ ] **Step 4: Verify pass** — run the test → PASS.
- [ ] **Step 5: Full suite** green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): H0 4-criterion clarify convergence"`

---

### Task 5: Clarifier brain (asks Socratic questions) + Brains field

**Files:**
- Create: `src/cn5_research_cos/brains/clarifier.py`
- Modify: `src/cn5_research_cos/brains/interfaces.py` (add `Clarifier` Protocol + `clarifier` field on `Brains`, ~line 73)
- Modify: `src/cn5_research_cos/brains/stubs.py` (`build_mock_brains` + real wiring ~265-300: wire a clarifier)
- Test: `tests/test_clarifier_brain.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clarifier_brain.py  (create)
from cn5_research_cos.brains import build_brains
from cn5_research_cos.models import ResearchState

def test_mock_clarifier_asks_for_missing_criteria():
    brains = build_brains("mock")
    rs = ResearchState(run_id="r", original_question="switch PK")
    qs = brains.clarifier.ask(rs, missing=["purpose", "success"])
    assert isinstance(qs, list) and qs            # at least one question
    joined = " ".join(qs)
    assert "用途" in joined or "決策" in joined    # purpose probed
```

- [ ] **Step 2: Verify fail** — FAIL (no `clarifier`).
- [ ] **Step 3: Implement**

`interfaces.py` (add near other Protocols + the dataclass):
```python
@runtime_checkable
class Clarifier(Protocol):
    def ask(self, state, missing: list[str]) -> list[str]: ...
```
Add to `Brains` dataclass: `clarifier: Clarifier | None = None`.

`brains/clarifier.py`:
```python
"""P8 H0 — generates Socratic clarification questions for the missing criteria.
The cockpit ASKS; the human ANSWERS. Cheap (haiku) — question-gen, no reasoning depth."""
from __future__ import annotations
from ..llm.sdk_client import call_structured
from ..models import ResearchState

_PROMPTS = {
    "purpose": "這份研究要拿來做什麼決定？(RFQ評分 / 選型 / 投資 / 定義參考…)",
    "scope":   "範圍邊界：哪些 in、哪些 out？(例：只比 silicon 規格，不含 gateway 應用分類)",
    "success": "你要的交付長怎樣？哪張表、哪些欄位最關鍵？",
    "constraints": "約束：NDA / 只能公開源 / 時間或深度上限？以及你手上有什麼可放進 reference 的素材？",
}

class MockClarifier:
    def ask(self, state: ResearchState, missing: list[str]) -> list[str]:
        return [_PROMPTS[m] for m in missing if m in _PROMPTS]

_SCHEMA = {"type": "object",
           "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
           "required": ["questions"], "additionalProperties": False}
_SYSTEM = ("You are a research chief-of-staff running a SOCRATIC clarification. "
           "Ask 1-3 targeted questions to pin ONLY the missing criteria. You ASK; "
           "the human ANSWERS — never answer for them. Traditional Chinese, terms untranslated. "
           "Return strict JSON {\"questions\": [...]}.")

class RealClarifier:
    def ask(self, state: ResearchState, missing: list[str]) -> list[str]:
        seed = "\n".join(f"- {m}: {_PROMPTS.get(m,'')}" for m in missing)
        user = (f"原始問題：{state.original_question}\n目前 brief：{state.research_brief or '(無)'}\n"
                f"還沒釘死的項目：\n{seed}\n針對這些缺項問出精準的蘇格拉底問題。")
        raw = call_structured(_SYSTEM, user, _SCHEMA, model="haiku")
        return [str(q) for q in raw.get("questions", []) if q]
```

Wire in `stubs.py`: in `build_mock_brains()` set `clarifier=MockClarifier()`; in the real-brains path (~291) set `clarifier=RealClarifier()`. Import at top of `stubs.py`.

- [ ] **Step 4: Verify pass** — run the test → PASS.
- [ ] **Step 5: Full suite** green (existing `Brains(...)` constructions still valid — new field defaults to None for any direct construction; check `test_*` that build `Brains` directly).
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): clarifier brain (Socratic question-gen)"`

---

### Task 6: `node_clarify` + FSM front wiring + AFK pause

**Files:**
- Modify: `src/cn5_research_cos/graph.py` (add `node_clarify` after `node_scope` ~205; rewire `scope → clarify → write_brief`; `build_graph` ~960)
- Test: `tests/test_clarify_node.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clarify_node.py  (create)
import cn5_research_cos.graph as g
from cn5_research_cos.models import ResearchState

class _Brains:  # minimal stub injected via state["brains"]
    class _Clar:
        def ask(self, rs, missing): return [f"Q:{m}" for m in missing]
    clarifier = _Clar()

def test_clarify_blocks_until_four_pinned(monkeypatch):
    asks = {}
    monkeypatch.setattr(g, "interrupt", lambda payload: asks.setdefault("p", payload) or {"answer": "x"})
    rs = ResearchState(run_id="r", original_question="q")  # nothing pinned
    state = {"research_state": rs, "brains": _Brains(), "mode": "interactive"}
    g.node_clarify(state)
    assert "p" in asks                       # it interrupted to ask the human
    assert rs.clarify_converged is False

def test_clarify_passes_when_converged():
    rs = ResearchState(run_id="r", original_question="q",
                       decision_criterion="RFQ", success_form="table",
                       research_brief="scope x", fallback_behavior_if_human_unavailable="public-only")
    state = {"research_state": rs, "brains": _Brains(), "mode": "auto"}
    out = g.node_clarify(state)
    assert out["research_state"].clarify_converged is True
```

- [ ] **Step 2: Verify fail** — FAIL (no `node_clarify`).
- [ ] **Step 3: Implement** — in `graph.py`:

```python
from .decision import clarify as _clarify   # top of file with other decision imports

def node_clarify(state: GraphState) -> GraphState:
    """H0 — multi-round Socratic clarification. Blocks until the 4 criteria are
    pinned. The cockpit ASKS (clarifier brain); the human ANSWERS (interrupt).
    AFK / auto default = pause here UNLESS the brief already converged or
    `assume_brief` is set in state."""
    rs = state["research_state"]
    ok, missing = _clarify.clarify_converged(rs)
    if ok:
        rs.clarify_converged = True
        return {"research_state": rs}
    if state.get("assume_brief"):
        # best-effort: record the gap as an explicit assumption, proceed
        rs.steering_events.append({"kind": "clarify-assumed", "missing": list(missing)})
        rs.clarify_converged = True
        return {"research_state": rs}
    brains = _brains(state)
    questions = brains.clarifier.ask(rs, missing) if brains.clarifier else [f"請補充：{m}" for m in missing]
    answer = interrupt({"kind": "clarify", "questions": questions, "missing": missing})
    # record the human's answer as a steering event; the brief-writer/criterion
    # extraction folds it in on the next pass (re-enter clarify until converged).
    rs.steering_events.append({"kind": "clarify-answer", "answer": answer, "for_missing": list(missing)})
    return {"research_state": rs}
```

Rewire `build_graph`: replace `g.add_edge("scope", "write_brief")` with:
```python
    g.add_node("clarify", node_clarify)
    g.add_edge("scope", "clarify")
    g.add_conditional_edges("clarify", _route_after_clarify,
                            {"clarify": "clarify", "write_brief": "write_brief"})
```
Add the router:
```python
def _route_after_clarify(state: GraphState) -> str:
    return "write_brief" if state["research_state"].clarify_converged else "clarify"
```

- [ ] **Step 4: Verify pass** — run the test → PASS.
- [ ] **Step 5: Regression** — `PYTHONPATH=src py -3 -m pytest tests/test_loop.py tests/test_smoke.py tests/test_hitl_interrupt.py -q`. The mock path: `ClarifyGateStub` + a converged brief means clarify passes immediately for existing loop tests that pre-set the brief; for tests that DON'T set criteria, set `assume_brief=True` in their state OR pre-pin the 4 fields. Update those tests minimally. Full suite green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): node_clarify H0 multi-round Socratic gate"`

---

### Task 7: `run-auto` honors clarify / `--assume-brief`

**Files:**
- Modify: `src/cn5_research_cos/cli.py` (`run_auto_cmd` ~332; add `--assume-brief` flag)
- Modify: `src/cn5_research_cos/graph.py` (`run_auto` ~1145: thread `assume_brief` into the initial GraphState)
- Test: `tests/test_cli_sot.py` or `tests/test_auto_mode.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auto_mode.py  (add)
import cn5_research_cos.graph as g
from cn5_research_cos.models import ResearchState

def test_run_auto_threads_assume_brief(monkeypatch):
    seen = {}
    def fake_invoke(initial, **kw):
        seen["assume"] = initial.get("assume_brief"); return initial
    # capture what the compiled app receives (mock the app.invoke path)
    monkeypatch.setattr(g, "_run_auto_invoke", fake_invoke, raising=False)
    # if _run_auto_invoke does not exist, assert the simpler contract instead:
    rs = ResearchState(run_id="r", original_question="q", mode="auto")
    # the GraphState built by run_auto must carry assume_brief when passed
```

(If `run_auto` builds the GraphState inline, assert via a thin seam: add `assume_brief` to the dict it constructs and test that the dict contains it. Keep the test to the contract: `assume_brief` flows from CLI → GraphState.)

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — `run_auto` signature gains `assume_brief: bool = False`; include `"assume_brief": assume_brief` in the initial GraphState dict it builds (alongside `mode`, `albert`, etc.). `cli.py run_auto_cmd` adds `assume_brief: bool = typer.Option(False, "--assume-brief", help="AFK: 帶既有假設跑，不停在 H0 釐清")` and passes it to `run_auto`. Crucially: `run_auto` must NOT pre-pin the 4 criteria — the loop now enters `clarify` first; without `--assume-brief` and without a converged brief it will pause at H0 (correct).
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Regression** — `PYTHONPATH=src py -3 -m pytest tests/test_cli_sot.py tests/test_auto_mode.py tests/test_cli_hitl.py -q`. Update any run-auto test that assumed clarify was skipped to either pass `assume_brief=True` or pre-pin the brief. Full suite green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): run-auto enters clarify; --assume-brief for AFK"`

---

### Task 8: Orchestrator brain — build/update the task grid

**Files:**
- Create: `src/cn5_research_cos/brains/orchestrator.py`
- Modify: `src/cn5_research_cos/brains/interfaces.py` (add `Orchestrator` Protocol + `orchestrator` field)
- Modify: `src/cn5_research_cos/brains/stubs.py` (wire mock + real orchestrator)
- Test: `tests/test_orchestrator_brain.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator_brain.py  (create)
from cn5_research_cos.brains import build_brains
from cn5_research_cos.models import ResearchState, TaskGrid, CellStatus, AlbertChallenge, ChallengeStatus

def test_orchestrator_seeds_grid_from_brief():
    brains = build_brains("mock")
    rs = ResearchState(run_id="r", original_question="switch PK",
                       success_form="vendor x spec_group table")
    grid = brains.orchestrator.plan(rs)
    assert isinstance(grid, TaskGrid) and grid.cells          # seeded some cells

def test_orchestrator_adds_cells_for_uncovered_gaps():
    brains = build_brains("mock")
    rs = ResearchState(run_id="r", original_question="q")
    rs.task_grid = TaskGrid(axes=["vendor", "spec_group"])
    rs.albert_challenge_map["c1"] = AlbertChallenge(
        id="c1", challenge="NXP TSN gate-list depth unknown",
        status=ChallengeStatus.open, issue_id=None)
    grid = brains.orchestrator.plan(rs)
    # the open challenge becomes (or maps to) a new open cell
    assert any(c.status == CellStatus.open for c in grid.cells.values())
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement**

`interfaces.py`:
```python
@runtime_checkable
class Orchestrator(Protocol):
    def plan(self, state) -> "TaskGrid": ...
```
Add `orchestrator: Orchestrator | None = None` to `Brains`.

`brains/orchestrator.py`:
```python
"""P8 §3 ① — the orchestrator: builds/updates the section-aware task grid each cycle
from the brief + prior results + Albert challenges + coverage gaps. Adaptive
re-decomposition (WebDART-style)."""
from __future__ import annotations
from ..llm.sdk_client import call_structured
from ..models import ResearchState, TaskGrid, TaskCell, CellStatus

def _gaps(rs: ResearchState) -> list[str]:
    g = []
    for ch in rs.albert_challenge_map.values():
        if getattr(ch.status, "value", ch.status) in ("open", "needs_internal_data", "needs_bu_judgment"):
            g.append(ch.challenge)
    for b in rs.evidence:
        g.extend(b.coverage_gaps)
    return g

class MockOrchestrator:
    """Deterministic: seed a small grid; turn each gap into an open cell."""
    def plan(self, rs: ResearchState) -> TaskGrid:
        grid = rs.task_grid or TaskGrid(axes=["vendor", "spec_group"])
        if not grid.cells:
            grid.cells["seed|core"] = TaskCell(
                id="seed|core", vendor="seed", spec_group="core",
                objective=rs.success_form or rs.original_question,
                status=CellStatus.open, impact=5)
        for i, gap in enumerate(_gaps(rs)):
            cid = f"gap|{i}"
            if cid not in grid.cells:
                grid.cells[cid] = TaskCell(id=cid, vendor="gap", spec_group=f"g{i}",
                                           objective=gap, status=CellStatus.open, impact=4)
        return grid

_SCHEMA = {"type": "object", "properties": {"cells": {"type": "array", "items": {
    "type": "object", "properties": {
        "vendor": {"type": "string"}, "spec_group": {"type": "string"},
        "objective": {"type": "string"}, "output_format": {"type": "string"},
        "boundaries": {"type": "string"}, "impact": {"type": "integer"}},
    "required": ["vendor", "spec_group", "objective"], "additionalProperties": False}}},
    "required": ["cells"], "additionalProperties": False}
_SYSTEM = ("You are the research ORCHESTRATOR. Decompose the question into a "
           "section-aware task grid: each cell = one (vendor x spec_group) research "
           "subtask that maps to ONE row/section of the final report. Update — do NOT "
           "duplicate covered cells; ADD cells for the gaps/challenges. Each cell needs "
           "objective + output_format + boundaries + impact(0-5). Strict JSON.")

class RealOrchestrator:
    def plan(self, rs: ResearchState) -> TaskGrid:
        grid = rs.task_grid or TaskGrid(axes=["vendor", "spec_group"])
        user = (f"問題：{rs.original_question}\nbrief：{rs.research_brief or ''}\n"
                f"成功形式：{rs.success_form or ''}\n已覆蓋 cell：{list(grid.cells)}\n"
                f"缺口/challenges：\n" + "\n".join(f"- {x}" for x in _gaps(rs)))
        raw = call_structured(_SYSTEM, user, _SCHEMA, model=None)  # DEFAULT_MODEL = Sonnet
        for c in raw.get("cells", []):
            cid = f"{c['vendor']}|{c['spec_group']}"
            if cid not in grid.cells:
                grid.cells[cid] = TaskCell(
                    id=cid, vendor=c["vendor"], spec_group=c["spec_group"],
                    objective=c["objective"], output_format=c.get("output_format", ""),
                    boundaries=c.get("boundaries", ""), impact=int(c.get("impact", 3)),
                    status=CellStatus.open)
        return grid
```

Wire mock/real in `stubs.py`.

- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Full suite** green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): orchestrator brain — adaptive task grid"`

---

### Task 9: `node_orchestrator_plan` + grid-based convergence

**Files:**
- Modify: `src/cn5_research_cos/graph.py` (add `node_orchestrator_plan`)
- Modify: `src/cn5_research_cos/decision/convergence.py` (add `grid_converged`)
- Test: `tests/test_orchestrator_node.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator_node.py  (create)
import cn5_research_cos.graph as g
from cn5_research_cos.decision import convergence
from cn5_research_cos.models import ResearchState, TaskGrid, TaskCell, CellStatus

class _B:
    class _O:
        def plan(self, rs):
            grid = rs.task_grid or TaskGrid()
            grid.cells.setdefault("v|s", TaskCell(id="v|s", vendor="v", spec_group="s",
                                  objective="o", status=CellStatus.open, impact=5))
            return grid
    orchestrator = _O()

def test_orchestrator_node_sets_grid():
    rs = ResearchState(run_id="r", original_question="q")
    out = g.node_orchestrator_plan({"research_state": rs, "brains": _B()})
    assert out["research_state"].task_grid.cells["v|s"].impact == 5

def test_grid_converged_only_when_no_open_high_impact():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["v|s"] = TaskCell(id="v|s", vendor="v", spec_group="s",
                                         objective="o", status=CellStatus.open, impact=5)
    assert convergence.grid_converged(rs) is False
    rs.task_grid.cells["v|s"].status = CellStatus.covered
    assert convergence.grid_converged(rs) is True
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement**

`convergence.py`:
```python
def grid_converged(state) -> bool:
    """P8 §4 — converged iff the grid exists and has no open high-impact cell."""
    grid = getattr(state, "task_grid", None)
    if grid is None:
        return False
    return not grid.open_high_impact_cells(min_impact=HIGH_IMPACT_CONF)
```

`graph.py`:
```python
def node_orchestrator_plan(state: GraphState) -> GraphState:
    """P8 §3 ① — loop head. (Re)build the section-aware task grid from the brief +
    prior results + Albert challenges + coverage gaps."""
    rs = state["research_state"]
    _consume_steer_events(rs)            # fold any H4 steer before re-planning
    brains = _brains(state)
    if brains.orchestrator is not None:
        rs.task_grid = brains.orchestrator.plan(rs)
    _report(state, "orchestrator", getattr(_obs, "render_orchestrator", lambda *a: None), rs)
    return {"research_state": rs}
```

- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Full suite** green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): node_orchestrator_plan + grid convergence"`

---

### Task 10: Plan-audit flash tier + `node_plan_audit`

**Files:**
- Modify: `src/cn5_research_cos/decision/audit_tier.py` (`audit_tier_for` accept stage `"plan"` → flash)
- Modify: `src/cn5_research_cos/graph.py` (add `node_plan_audit`; skip when grid unchanged)
- Test: `tests/test_plan_audit.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_audit.py  (create)
import cn5_research_cos.graph as g
from cn5_research_cos.decision import audit_tier
from cn5_research_cos.models import ResearchState, TaskGrid, TaskCell, CellStatus

def test_plan_stage_is_flash():
    rs = ResearchState(run_id="r", original_question="q")
    assert audit_tier.audit_tier_for("plan", rs) == "flash"

def test_plan_audit_skips_when_grid_unchanged():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["v|s"] = TaskCell(id="v|s", vendor="v", spec_group="s",
                                         objective="o", status=CellStatus.open)
    calls = {"n": 0}
    class _B:
        class _A:
            def audit(self, s): calls["n"] += 1; return None
        auditor = _A()
    st = {"research_state": rs, "brains": _B()}
    g.node_plan_audit(st); g.node_plan_audit(st)   # grid unchanged 2nd time
    assert calls["n"] == 1                          # audited once, skipped once
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement**

`audit_tier.py` — add `"plan": "flash"` to `_STAGE_BASE` (and keep the escalation rules; plan-audit stays flash).

`graph.py`:
```python
def _grid_signature(rs) -> str:
    grid = getattr(rs, "task_grid", None)
    if grid is None:
        return ""
    return "|".join(f"{c.id}:{c.status}" for c in sorted(grid.cells.values(), key=lambda x: x.id))

def node_plan_audit(state: GraphState) -> GraphState:
    """P8 §3 ②(b) — Albert audits the PLAN (flash). Skipped when the grid is
    unchanged from the last audited signature (avoids paying every cycle for a
    plan that did not move)."""
    rs = state["research_state"]
    sig = _grid_signature(rs)
    last = state.get("_last_plan_sig")
    if sig and sig == last:
        return {"research_state": rs}
    brains = _brains(state)
    auditor = getattr(brains, "auditor", None)
    if auditor is not None:
        audit = auditor.audit(rs)            # flash tier via audit_tier_for("plan", rs)
        if audit is not None:
            rs.last_audit = audit
    return {"research_state": rs, "_last_plan_sig": sig}
```
Add `_last_plan_sig: str` to `GraphState` (TypedDict in `state.py`).

- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Full suite** green (`test_audit_tier.py`, `test_audit_tier_speed.py`).
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): plan-audit flash tier + node_plan_audit (skip-if-unchanged)"`

---

### Task 11: H7 — `node_plan_approval`

**Files:**
- Modify: `src/cn5_research_cos/graph.py` (add `node_plan_approval`)
- Test: `tests/test_plan_approval.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_approval.py  (create)
import cn5_research_cos.graph as g
from cn5_research_cos.models import ResearchState, TaskGrid, TaskCell, CellStatus

def _grid(*ids):
    grid = TaskGrid()
    for i in ids:
        grid.cells[i] = TaskCell(id=i, vendor=i, spec_group="s", objective="o", status=CellStatus.open)
    return grid

def test_h7_prompts_on_first_cycle(monkeypatch):
    hit = {}
    monkeypatch.setattr(g, "interrupt", lambda p: hit.setdefault("p", p) or {"approve": True})
    rs = ResearchState(run_id="r", original_question="q", task_grid=_grid("a"))
    g.node_plan_approval({"research_state": rs, "mode": "interactive"})
    assert "p" in hit

def test_h7_skips_on_small_rerank(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(g, "interrupt", lambda p: calls.__setitem__("n", calls["n"] + 1) or {"approve": True})
    rs = ResearchState(run_id="r", original_question="q", task_grid=_grid("a"))
    st = {"research_state": rs, "mode": "interactive"}
    g.node_plan_approval(st)                     # first cycle → prompts
    g.node_plan_approval(st)                     # same grid → no new top-level branch → skip
    assert calls["n"] == 1

def test_h7_reprompts_on_major_redecomposition(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(g, "interrupt", lambda p: calls.__setitem__("n", calls["n"] + 1) or {"approve": True})
    rs = ResearchState(run_id="r", original_question="q", task_grid=_grid("a"))
    st = {"research_state": rs, "mode": "interactive"}
    g.node_plan_approval(st)
    rs.task_grid = _grid("a", "b", "c", "d")     # major: grid grew a lot
    g.node_plan_approval(st)
    assert calls["n"] == 2
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — `graph.py`:

```python
_H7_MAJOR_DELTA = 2   # >=2 new top-level cells since last approval == "major re-decomposition"

def node_plan_approval(state: GraphState) -> GraphState:
    """P8 §5 H7 — human approves the task grid before expensive research. Prompts on
    the FIRST cycle, and again only on a MAJOR re-decomposition (>= _H7_MAJOR_DELTA new
    cells). Small re-ranks do NOT re-prompt. In auto mode without a human, it pauses
    (interrupt) on the first cycle just like H1/H5 unless assume_brief is set."""
    rs = state["research_state"]
    grid = getattr(rs, "task_grid", None)
    n_cells = len(grid.cells) if grid else 0
    last_n = state.get("_h7_approved_n")
    if state.get("assume_brief"):
        return {"research_state": rs, "_h7_approved_n": n_cells}
    first = last_n is None
    major = (last_n is not None) and (n_cells - last_n >= _H7_MAJOR_DELTA)
    if not (first or major):
        return {"research_state": rs}
    answer = interrupt({"kind": "plan_approval",
                        "cells": [c.id for c in grid.cells.values()] if grid else [],
                        "first_cycle": first})
    rs.steering_events.append({"kind": "plan-approval", "answer": answer})
    return {"research_state": rs, "_h7_approved_n": n_cells}
```
Add `_h7_approved_n: int` to `GraphState`.

- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Full suite** green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): H7 plan-approval gate (first cycle + major re-plan)"`

---

### Task 12: FSM rewire — loop head = orchestrator

**Files:**
- Modify: `src/cn5_research_cos/graph.py` (`build_graph` 939-999; `_route` 888; `_route_after_pull` 923)
- Test: `tests/test_loop_head_rewire.py` (create) + regression

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loop_head_rewire.py  (create)
from cn5_research_cos.graph import build_graph

def test_orchestration_nodes_wired():
    g = build_graph()
    nodes = set(g.nodes)
    assert {"clarify", "orchestrator_plan", "plan_audit", "plan_approval"} <= nodes

def test_brief_flows_into_orchestrator_then_supervisor():
    # structural: write_brief -> orchestrator_plan -> plan_audit -> plan_approval -> supervisor
    g = build_graph()
    # edges are private; assert via compiled run on mock that a grid is produced
    from cn5_research_cos.graph import run_loop
    from cn5_research_cos.models import ResearchState
    rs = ResearchState(run_id="r", original_question="q",
                       decision_criterion="c", success_form="t",
                       research_brief="b", fallback_behavior_if_human_unavailable="f")
    out = run_loop(rs, base_dir="runs", max_iterations=1, llm="mock")
    assert out.task_grid is not None        # the orchestrator ran in the loop
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — in `build_graph`, register the new nodes and rewire:

```python
    g.add_node("clarify", node_clarify)
    g.add_node("orchestrator_plan", node_orchestrator_plan)
    g.add_node("plan_audit", node_plan_audit)
    g.add_node("plan_approval", node_plan_approval)
    # front: intake -> scope -> clarify(loop) -> write_brief
    g.add_edge("scope", "clarify")
    g.add_conditional_edges("clarify", _route_after_clarify,
                            {"clarify": "clarify", "write_brief": "write_brief"})
    # loop head: write_brief -> orchestrator_plan -> plan_audit -> plan_approval -> supervisor
    g.add_edge("write_brief", "orchestrator_plan")
    g.add_edge("orchestrator_plan", "plan_audit")
    g.add_edge("plan_audit", "plan_approval")
    g.add_edge("plan_approval", "supervisor")
```
Remove the old `g.add_edge("write_brief", "issue_expansion")` and `g.add_edge("issue_expansion", "supervisor")` direct chain; keep `issue_expansion` node reachable (branch/rerank still route to it via `_route`), and add an edge `issue_expansion -> supervisor` (unchanged) so branch/rerank still works.

In `_route` (888): change the default loop-back from `"supervisor"` to `"orchestrator_plan"` so a normal `continue_research` re-plans:
```python
    # ... existing terminal/pull/push/branch handling unchanged ...
    return "orchestrator_plan"   # was "supervisor"
```
And add `"orchestrator_plan": "orchestrator_plan"` to the `_route` conditional-edges mapping in `build_graph`.

In `_route_after_pull` (923): change its `"supervisor"` continue target to `"orchestrator_plan"` too (after a human pull, re-plan with the new direction). Update its mapping dict.

- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Regression — THE BIG ONE.** `PYTHONPATH=src py -3 -m pytest -q`. Expect breaks in `test_loop.py`, `test_convergence_loop.py`, `test_stop_conditions.py`, `test_decision.py` because the loop-back target changed (supervisor → orchestrator_plan) and the front gained clarify. Fix each by: (a) pre-pinning the 4 clarify criteria (or `assume_brief=True`) in the test's initial state; (b) updating any assertion that hard-codes the node sequence `supervisor` as loop head. Do NOT weaken behavioral assertions — only update the structural path. Green before commit.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): rewire loop head supervisor->orchestrator_plan (reusable orchestration loop)"`

---

### Task 13: Section-aware synthesis (cell → report row)

**Files:**
- Modify: `src/cn5_research_cos/brains/synthesis.py` (`_render_state` includes the grid; `_SYSTEM` instructs cell→row)
- Test: `tests/test_findings_first_deliverable.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_findings_first_deliverable.py  (add)
import cn5_research_cos.brains.synthesis as syn
from cn5_research_cos.models import ResearchState, TaskGrid, TaskCell, CellStatus

def test_render_state_includes_task_grid():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|fabric"] = TaskCell(
        id="NXP|fabric", vendor="NXP", spec_group="fabric", objective="o",
        status=CellStatus.covered, impact=5)
    text = syn._render_state(rs)
    assert "NXP" in text and "fabric" in text     # the grid is fed to synthesis
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — in `_render_state`, append a TASK GRID section listing each cell `(vendor, spec_group, status, objective)`; in `_SYSTEM`/the `write_sections` user prompt add: "The `findings` table has ONE ROW PER COVERED/PARTIAL cell of the TASK GRID (section-aware merge-and-edit); N/A for `na`/`blocked` cells; never invent rows." Keep the findings-first ordering + citation rules unchanged.
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Regression** — `PYTHONPATH=src py -3 -m pytest tests/test_findings_first_deliverable.py tests/test_memo_assembly.py tests/test_synthesizer.py -q`. Green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): section-aware synthesis (task-grid cell -> report row)"`

---

### Task 14: Consolidated supplement email (H3 + B-4, once/run)

**Files:**
- Modify: `src/cn5_research_cos/notify/email.py` (`build_supplement_email` includes internal-data tasks)
- Modify: `src/cn5_research_cos/graph.py` (`_notify_needs_supplement` ~758: gather H3 `blocked_by_internal_data` HumanTasks too)
- Test: `tests/test_citation_notify_wiring.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_citation_notify_wiring.py  (add)
import cn5_research_cos.graph as graph
from cn5_research_cos.models import (ResearchState, HumanTask, HumanTaskStatus,
    AuditResult, AuditVerdict, Risk, ReadinessScore)

def test_consolidated_email_includes_internal_data_tasks(monkeypatch):
    calls = []
    monkeypatch.setattr(graph, "notify_supplement_needed",
                        lambda run_id, items, **kw: calls.append(list(items)) or True)
    rs = ResearchState(run_id="r", original_question="q")
    rs.last_audit = AuditResult(verdict=AuditVerdict.exhausted, degraded=False,
                                premature_end_risk=Risk.low, research_drift_risk=Risk.low)
    rs.readiness_score = ReadinessScore(albert_challenge_readiness=5, decision_readiness=5,
        research_exhaustion_readiness=5, human_bottleneck_clarity=5, should_continue=False)
    rs.human_tasks["HT-1"] = HumanTask(id="HT-1", task_title="提供內部資料：X",
        requested_input="內部 datasheet", why_needed="public 查不到",
        blocking_question="X", priority=5, can_continue_without_it=True,
        status=HumanTaskStatus.open)
    graph._build_and_gate_memo({"research_state": rs, "llm": "mock",
                                "explicit_emit": True, "base_dir": "runs"}, rs)
    assert len(calls) == 1                       # exactly one consolidated email
    assert any("內部" in t.requested_input or "datasheet" in t.requested_input for t in calls[0])
```

- [ ] **Step 2: Verify fail** (today the H3 internal-data task is not included).
- [ ] **Step 3: Implement** — in `_notify_needs_supplement`, gather BOTH the needs-supplement (B-4) tasks AND the open `blocked_by_internal_data`-linked HumanTasks (H3) into one `items` list (dedup by `id`), keep the once-per-run `_NOTIFY_EVENT_KIND` guard. `build_supplement_email` groups them under "需驗證補充" vs "需內部資料" headings. Still one email/run; still non-blocking.
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Regression** — `PYTHONPATH=src py -3 -m pytest tests/test_citation_notify_wiring.py tests/test_notify_email.py tests/test_human_push.py -q`. The flood-regression tests must still pass (still ≤1 email/run). Green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): consolidated supplement email (H3 internal-data + B-4), once/run"`

---

### Task 15: E1 — no early stop while researchable

**Files:**
- Modify: `src/cn5_research_cos/graph.py` (`_route` iteration-ceiling exit ~908; `_route_after_pull` ceiling ~931)
- Test: `tests/test_stop_conditions.py` (add)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stop_conditions.py  (add)
import cn5_research_cos.graph as g
from cn5_research_cos.models import ResearchState, TaskGrid, TaskCell, CellStatus, Decision

def test_ceiling_does_not_stop_while_open_high_impact_cell(monkeypatch):
    rs = ResearchState(run_id="r", original_question="q", iteration_count=99, task_grid=TaskGrid())
    rs.task_grid.cells["v|s"] = TaskCell(id="v|s", vendor="v", spec_group="s",
                                         objective="o", status=CellStatus.open, impact=5)
    monkeypatch.setattr(g.run_cap, "cap_hit_now", lambda: False)
    state = {"research_state": rs, "last_decision": Decision.continue_research,
             "max_iterations": 8}
    # with an open high-impact cell and caps not hit, the router must NOT divert to wrap-up
    assert g._route(state) != "deep_audit"        # not forced to terminal/review

def test_ceiling_stops_when_grid_converged(monkeypatch):
    rs = ResearchState(run_id="r", original_question="q", iteration_count=99, task_grid=TaskGrid())
    rs.task_grid.cells["v|s"] = TaskCell(id="v|s", vendor="v", spec_group="s",
                                         objective="o", status=CellStatus.covered, impact=5)
    monkeypatch.setattr(g.run_cap, "cap_hit_now", lambda: False)
    state = {"research_state": rs, "last_decision": Decision.synthesize, "max_iterations": 8}
    assert g._route(state) == "deep_audit"        # converged → allowed to wrap up
```

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — guard the iteration-ceiling exit in `_route` (and `_route_after_pull`): the ceiling only forces wrap-up when `run_cap.cap_hit_now()` OR `convergence.grid_converged(rs)` OR there is no open high-impact cell. While `grid.open_high_impact_cells(min_impact=4)` is non-empty and caps not hit, keep looping (return the normal `orchestrator_plan`). Add the import `from .decision import convergence`.

```python
    rs = state["research_state"]
    researchable = bool(getattr(rs, "task_grid", None)) and \
        bool(rs.task_grid.open_high_impact_cells(min_impact=4))
    ceiling = rs.iteration_count >= state.get("max_iterations", 8)
    if ceiling and not run_cap.cap_hit_now() and researchable and not convergence.grid_converged(rs):
        return "orchestrator_plan"       # keep researching; 8h cap is the real bound
    # ... existing terminal/synthesize/ceiling → deep_audit handling unchanged ...
```

- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Regression** — `PYTHONPATH=src py -3 -m pytest tests/test_stop_conditions.py tests/test_loop.py tests/test_hard_run_cap.py -q`. Ensure the hard-cap still stops (cap_hit overrides researchable). Full suite green.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(p8): no early stop while a high-impact cell is researchable (E1)"`

---

## Final integration

- [ ] **Full regression:** `PYTHONPATH=src py -3 -m pytest -q` → all green (P1–P8).
- [ ] **Live end-to-end (opt-in, manual):** re-run the switch-PK topic with real Albert + 8h cap; confirm: Socratic clarify pins the decision-anchor first (pauses if AFK); the loop adaptively re-decomposes the vendor×spec-group grid; H7 prompts once; ONE consolidated supplement email; findings-first cited partial PK table (filled cells + honest N/A + blocked-cell list). Command:
  `PYTHONPATH=src py -3 scripts/dogfood.py "topics/switch pk.txt" --llm real --albert real --run-id p8-switchpk` (set `CN5_COS_MAX_WALL_S` as desired; default 8h).
- [ ] **Dispatch final code reviewer** over the whole P8 diff.
- [ ] **Do NOT push** without explicit user confirmation.

## Self-review notes (gaps consciously deferred)

- The §9 global gate (SOTA-Alignment Governed Object / R23) is an ecosystem change under `~/.claude/` — NOT in this plan (separate, per the global-scope rule).
- 3-axis grid (vendor×part×spec_group) is supported by the `TaskCell.part_number` field but the orchestrator seeds 2-axis by default; 3-axis expansion is data-driven (no separate task needed — the orchestrator may emit `part_number` cells when product-dense).
- ②(a) self-reflect (`think`) is folded into the orchestrator's `plan()` call (it decides which cells next as part of building the grid) rather than a separate node, to avoid an extra LLM round; the plan-audit (②b) + H7 (②c) are the explicit seams.
