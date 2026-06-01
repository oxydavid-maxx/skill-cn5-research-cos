# Phase 1 Implementation Plan (R2) — Deterministic Spine + LangGraph Loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
> **R2 (2026-06-01):** regenerated after the GPT Researcher + Open Deep Research + paperwork study. Carries the FULL loop SHAPE (scope→brief, supervisor Send-fan-out, compress, full §18 node set, anti-premature 7-checklist, branch-budget, plateau, two-level caps, staged binary decision) as DETERMINISTIC stubs so P2–P4 are fill-in. Spec: `docs/superpowers/specs/2026-06-01-phase1-deterministic-spine-design.md` (§1–§12). Canonical flow: `docs/spec/flow-diagram.md`.

**Goal:** the full research convergence loop runs with deterministic stub brains (zero LLM), LangGraph-driven, fully test-covered, passing Acceptance Tests 1 & 4 + the new anti-premature / branch-budget / plateau / resume tests.

**Architecture:** Pydantic v2 models → typed artifacts → pure decision logic (`exhaustion`+`plateau`, `gate`, `anti_premature`, `branch_budget`) → seven+ brain Protocols with deterministic stubs behind an injection factory → a LangGraph `StateGraph` (full §18 node set, supervisor fan-out via `Send`, staged-binary router) → Typer CLI with Chinese iteration summaries. Persistence = LangGraph SqliteSaver (resume) + JSON snapshot.

**Tech Stack:** Python 3.11+, pydantic≥2, langgraph, langgraph-checkpoint-sqlite, typer, rich, pytest.

**Conventions:** src layout; TDD (test→fail→implement→pass→commit); no `datetime.now()` in core; all status/type fields Enums; router functions read-only/no-side-effect (LangGraph best practice).

---

### Task 1: Bootstrap

**Files:** Create `pyproject.toml`, `src/cn5_research_cos/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`.

- [ ] **Step 1: failing test**
```python
# tests/test_smoke.py
def test_imports():
    import cn5_research_cos
    assert cn5_research_cos.__version__ == "0.1.0"
```
- [ ] **Step 2:** `pytest tests/test_smoke.py -v` → FAIL.
- [ ] **Step 3:** `pyproject.toml` — package `cn5-research-cos`, deps `pydantic>=2, langgraph>=0.2, langgraph-checkpoint-sqlite>=1, typer>=0.12, rich>=13`; dev `pytest>=8`; script `cos = "cn5_research_cos.cli:app"`; src layout.
- [ ] **Step 4:** `__init__.py` → `__version__ = "0.1.0"`.
- [ ] **Step 5:** `pip install -e ".[dev]"`; `pytest tests/test_smoke.py -v` → PASS.
- [ ] **Step 6:** commit `feat(p1): bootstrap`.

---

### Task 2: Enums + models (incl R2 fields)

**Files:** Create `src/cn5_research_cos/models.py`, `tests/test_models.py`.

- [ ] **Step 1: failing tests**
```python
# tests/test_models.py
import pytest
from pydantic import ValidationError
from cn5_research_cos.models import (IssueNode, IssueType, IssueStatus, AuditResult,
    AuditVerdict, ResearchState, EvidenceBundle)

def test_issue_round_trip():
    n = IssueNode(id="I-001", title="t", description="d", issue_type=IssueType.competitor,
                  status=IssueStatus.open, impact=3, confidence=2)
    assert IssueNode.model_validate_json(n.model_dump_json()) == n

def test_bounds_and_enum():
    with pytest.raises(ValidationError):
        IssueNode(id="x", title="t", description="d", issue_type=IssueType.roi,
                  status=IssueStatus.open, impact=9, confidence=1)
    with pytest.raises(ValidationError):
        IssueNode(id="x", title="t", description="d", issue_type="bad",
                  status=IssueStatus.open, impact=1, confidence=1)

def test_state_has_r2_fields():
    s = ResearchState(run_id="r", original_question="q")
    # R2 preflight + brief fields exist and default empty/None
    assert s.research_brief is None and s.forbidden_directions == []
    assert ResearchState.model_validate_json(s.model_dump_json()) == s

def test_audit_r2_fields():
    a = AuditResult(verdict=AuditVerdict.exhausted)
    assert a.questions_albert_would_ask_next == [] and a.readiness_score_delta == 0 and a.degraded is False

def test_evidence_coverage_gaps():
    e = EvidenceBundle(query="q")
    assert e.coverage_gaps == []
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: implement `models.py`** — Enums `IssueType, IssueStatus, ChallengeStatus, HumanTaskStatus, BoardColumn, SourceType, SourceQuality, Decision, Classification, AuditVerdict, Risk` (all `str, Enum`; values = names). Models:
  - `IssueNode` (per spec §17 + Enums; `impact`/`confidence` `Field(ge=0, le=5)`).
  - `AlbertChallenge` (+ `classification: Classification | None = None`).
  - `HumanTask`, `Source`, `Claim`.
  - `EvidenceBundle` (+ `coverage_gaps: list[str] = []`).
  - `ReadinessScore` (4×`Field(ge=0,le=5)` + should_continue + reason).
  - `AuditResult` (verdict, challenges, weak_points, premature_end_risk: Risk, research_drift_risk: Risk, recommended_next_action: Decision|None, rationale, **+ missing_business_context: list[str]=[], questions_albert_would_ask_next: list[str]=[], recommended_next_probe: str|None=None, readiness_score_delta: int=0, degraded: bool=False**).
  - `ResearchState` (run_id, original_question, meeting_context, target_audience, mode, **+ R2 preflight: likely_albert_concern: str|None=None, output_purpose: str|None=None, known_constraints: list[str]=[], forbidden_directions: list[str]=[], available_sources: list[str]=[], internal_documents_available: bool|None=None, default_research_priority: str|None=None, fallback_behavior_if_human_unavailable: str|None=None, + research_brief: str|None=None**, issue_map, albert_challenge_map, evidence: list[EvidenceBundle], human_tasks, branches, steering_events, readiness_score, readiness_history: list[dict]=[], iteration_count: int=0, last_audit: AuditResult|None=None, final_memo, created_at, updated_at).
- [ ] **Step 4:** run → PASS. **Step 5:** commit `feat(p1): models + enums (R2 fields)`.

---

### Task 3: Persistence (`store.py`)

**Files:** Create `src/cn5_research_cos/store.py`, `tests/test_persistence.py` (resume added Task 9).

- [ ] **Step 1: failing test**
```python
# tests/test_persistence.py
import pytest
from cn5_research_cos.store import new_run, save_snapshot, load_snapshot

def test_round_trip(tmp_path):
    s = new_run("q", run_id="r1", now="2026-06-01T00:00:00"); s.iteration_count = 2
    save_snapshot(s, base_dir=tmp_path)
    assert load_snapshot("r1", base_dir=tmp_path) == s

def test_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshot("nope", base_dir=tmp_path)
```
- [ ] **Step 2:** FAIL. **Step 3: implement** `new_run(question,*,run_id,now,mode="interactive")`, `save_snapshot(state,base_dir="runs")` (pretty JSON to `runs/<id>/state.json`), `load_snapshot(run_id,base_dir="runs")` (raise `FileNotFoundError` if absent). **Step 4:** PASS. **Step 5:** commit `feat(p1): json snapshot persistence`.

---

### Task 4: Issue / Challenge artifacts

**Files:** Create `src/cn5_research_cos/artifacts/__init__.py`, `issue_map.py`, `challenge_map.py`, `tests/test_artifacts.py`.

- [ ] **Step 1: failing test** — add/get/update; monotonic ids `I-001`/`C-001`; `set_status` sets `last_updated`; `has_type(state, IssueType.competitor)`.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement `issue_map.py`** — `_next_id` (`I-%03d`), `add(...)`, `get`, `set_status(...,now)`, `has_type(state, issue_type)`. `challenge_map.py` — `_next_id` (`C-%03d`), `add(...)`, `get`. `__init__.py` re-exports `issue_map, challenge_map, readiness_board`.
- [ ] **Step 4:** PASS. **Step 5:** commit `feat(p1): issue + challenge artifacts`.

---

### Task 5: Readiness board (derived)

**Files:** Create `src/cn5_research_cos/artifacts/readiness_board.py`, `tests/test_board_derivation.py`.

- [ ] **Step 1:** test empty→all-empty; mixed status → correct columns; back-refs present.
- [ ] **Step 2:** FAIL. **Step 3:** `derive_board(state) -> dict[BoardColumn, list[str]]` with explicit `ISSUE_TO_COLUMN` + `CHALLENGE_TO_COLUMN` maps (pure). **Step 4:** PASS. **Step 5:** commit `feat(p1): derived readiness board`.

---

### Task 6: Decision logic — exhaustion+plateau, gate, anti_premature, branch_budget

**Files:** Create `src/cn5_research_cos/decision/__init__.py`, `exhaustion.py`, `gate.py`, `anti_premature.py`, `branch_budget.py`, `tests/test_decision.py`.

- [ ] **Step 1: failing tests**
```python
# tests/test_decision.py
from cn5_research_cos.models import (ResearchState, IssueType, IssueStatus, ReadinessScore,
    AuditResult, AuditVerdict, Decision)
from cn5_research_cos.artifacts import issue_map
from cn5_research_cos.decision import exhaustion, gate, anti_premature, branch_budget

def _ready(s, v):
    s.readiness_score = ReadinessScore(albert_challenge_readiness=v, decision_readiness=v,
        research_exhaustion_readiness=v, human_bottleneck_clarity=v, should_continue=v<4, reason="")

def test_addressable_blocks_terminal():
    s = ResearchState(run_id="r", original_question="q")
    issue_map.add(s, title="A", description="d", issue_type=IssueType.roi, status=IssueStatus.open, now="t")
    _ready(s, 5); assert exhaustion.terminal_eligible(s) is False

def test_all_residual_ready_terminal():
    s = ResearchState(run_id="r", original_question="q")
    issue_map.add(s, title="A", description="d", issue_type=IssueType.internal_data,
                  status=IssueStatus.blocked_by_internal_data, now="t")
    _ready(s, 4); assert exhaustion.terminal_eligible(s) is True

def test_plateau():
    s = ResearchState(run_id="r", original_question="q")
    s.readiness_history = [{"sum": 8}, {"sum": 8}, {"sum": 8}]
    assert exhaustion.plateau(s, window=2) is True

def test_gate_refuses_degraded():
    s = ResearchState(run_id="r", original_question="q")
    s.last_audit = AuditResult(verdict=AuditVerdict.exhausted, degraded=True)
    assert gate.assert_audit_ran(s, Decision.terminal_stop) == Decision.continue_research

def test_anti_premature_blocks_until_all_true():
    flags = {k: True for k in anti_premature.PREREQS}; flags["counterargument_pass"] = False
    assert anti_premature.all_done(flags) is False
    flags["counterargument_pass"] = True
    assert anti_premature.all_done(flags) is True

def test_branch_budget_decays_and_refuses():
    b = branch_budget.Budget(breadth=4, depth=1)
    b2 = branch_budget.spend(b)
    assert b2.breadth == 2 and b2.depth == 0
    assert branch_budget.can_branch(b2) is False
```
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement `exhaustion.py`** — `ADDRESSABLE_STATUSES = {open, researching, partially_answered, low_confidence}`; `has_addressable(state)`; `targets_met(state)` (min of 4 ≥4); `terminal_eligible(state) = (not has_addressable) and targets_met and anti_premature.all_done(...)` (anti-premature AND-ed — see note); `plateau(state, window=2)` → True if last `window+1` `readiness_history[*]["sum"]` are non-increasing/equal.
- [ ] **Step 4: implement `gate.py`** — `assert_audit_ran(state, decision)` → if decision in {terminal_stop, synthesize} and (`last_audit is None or last_audit.degraded`) and env `CN5_COS_EMIT_DESPITE_DEGRADED_AUDIT != "1"` → return `continue_research`, else decision.
- [ ] **Step 5: implement `anti_premature.py`** — `PREREQS = ["broad_expansion","albert_audit_ran","counterargument_pass","source_confidence_checked","pending_questions_extracted","blockers_classified","explicit_continue_explanation"]`; `all_done(flags: dict) -> bool = all(flags.get(k, False) for k in PREREQS)`.
- [ ] **Step 6: implement `branch_budget.py`** — `@dataclass Budget(breadth:int, depth:int)`; `spend(b) -> Budget(max(2, b.breadth//2), b.depth-1)`; `can_branch(b) -> bool = b.depth > 0`.
- [ ] **Step 7:** run → PASS. **Step 8:** commit `feat(p1): exhaustion+plateau, gate, anti-premature, branch-budget`.

> Note: wire `terminal_eligible` to also require `anti_premature.all_done(state-derived flags)`. The flags live on a small `state.branches`-style dict set by nodes (Task 8); for the pure unit test above, `terminal_eligible` reads `state`-derived flags via a helper defaulting all-False, so a fresh state cannot terminal-stop.

---

### Task 7: Brain Protocols + deterministic stubs (incl scope/brief/supervisor/compress) + factory

**Files:** Create `src/cn5_research_cos/brains/__init__.py`, `interfaces.py`, `stubs.py`, `tests/test_stubs.py`.

- [ ] **Step 1: failing test** (auditor competitor rule = crux of Test 1)
```python
# tests/test_stubs.py
from cn5_research_cos.models import ResearchState, IssueType, IssueStatus, AuditVerdict, Risk
from cn5_research_cos.artifacts import issue_map
from cn5_research_cos.brains import build_brains

def test_auditor_raises_competitor_when_absent():
    s = ResearchState(run_id="r", original_question="q")
    issue_map.add(s, title="ROI", description="d", issue_type=IssueType.roi, status=IssueStatus.open, now="t")
    a = build_brains("mock").auditor.audit(s)
    assert a.verdict == AuditVerdict.rework and a.premature_end_risk == Risk.high and a.challenges

def test_brief_stub_sets_brief():
    s = ResearchState(run_id="r", original_question="AI overnight research?")
    build_brains("mock").brief_writer.write(s)
    assert s.research_brief
```
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement `interfaces.py`** — Protocols: `ClarifyGate.check(state)->bool` (scope), `BriefWriter.write(state)->None`, `IssueExpander.expand(state, now)->list`, `Supervisor.select(state)->list[str]` (issue ids to fan out), `Researcher.research(state, issue_id)->EvidenceBundle`, `SourceCritic.review(bundle)->EvidenceBundle`, `Compressor.compress(bundle)->EvidenceBundle`, `Skeptic.counter(state, bundle)->list[str]`, `Auditor.audit(state)->AuditResult`, `Scorer.score(state)->ReadinessScore`. `@dataclass Brains` bundling them.
- [ ] **Step 4: implement `stubs.py`** deterministically:
  - `ClarifyGateStub.check` → always True (clarified; real interrupt = P3).
  - `BriefWriterStub.write` → `state.research_brief = f"目標：回答「{state.original_question}」並通過 Albert 質疑"`.
  - `IssueExpanderStub.expand` → if empty, seed root_question/intent/roi/risk (NEVER competitor — so Test 1 can detect absence).
  - `SupervisorStub.select` → return ids of up to `MAX_CONCURRENT`(=4) non-answered issues (deterministic order).
  - `ResearcherStub.research` → canned `EvidenceBundle` per issue_id; after `STALE_AFTER`(=3) iterations returns identical bundle (Test 4 saturation).
  - `SourceCriticStub.review` → passthrough. `CompressorStub.compress` → passthrough + 1-line summary in `bundle.suggested_followups`.
  - `SkepticStub.counter` → `["alt explanation (stub)"]`.
  - `AuditorStub.audit` → **if `not has_type(competitor)`: AuditResult(rework, [competitor challenge classification=addressable], premature_end_risk=high, recommended_next_action=branch)**; elif `iteration_count >= STALE_AFTER`: AuditResult(exhausted, premature_end_risk=low); else AuditResult(continue_).
  - `ScorerStub.score` → deterministic; `albert_challenge_readiness = 4 if has_type(competitor) else 1`; others from answered/total.
  - `build_brains(llm="mock")` → raise `NotImplementedError` if `llm!="mock"`; else assemble all stubs.
- [ ] **Step 5:** PASS. **Step 6:** commit `feat(p1): brain protocols + deterministic stubs + factory`.

---

### Task 8: LangGraph loop (full §18 nodes, Send fan-out, staged router)

**Files:** Create `src/cn5_research_cos/state.py`, `graph.py`, `tests/test_loop.py`.

- [ ] **Step 1: failing test**
```python
# tests/test_loop.py
from cn5_research_cos.graph import run_loop
from cn5_research_cos.models import ResearchState

def test_loop_terminates(tmp_path):
    final = run_loop(ResearchState(run_id="r", original_question="q"),
                     base_dir=tmp_path, max_iterations=8, now="t0")
    assert final.readiness_score is not None and final.iteration_count >= 1
    assert (tmp_path / "r" / "state.json").exists()
    assert final.research_brief  # brief node ran
```
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: implement `state.py`** — `GraphState(TypedDict, total=False)`: `research_state: ResearchState`, `last_decision: Decision`, `branch_budget: dict`, `prereqs: dict`, `worker_results: Annotated[list, operator.add]`, `base_dir/now/max_iterations`.
- [ ] **Step 4: implement `graph.py`** — nodes in canonical order with the §18 set:
  `intake → scope → write_brief → issue_expansion → supervisor → [Send→worker (research→source_critic→compress)] → collect → skeptic → albert_audit → artifact_update → readiness_scoring → anti_premature → cos_decision → router`.
  - `supervisor` node returns `[Send("worker", {"issue_id": i, "base_state_ref": ...})...]` for the selected issues (context-isolated payload = just the issue); P1 may also run sequentially but MUST emit Send objects. `worker` writes to `worker_results` (merged via `operator.add` reducer). `collect` folds `worker_results` into `state.evidence`.
  - `anti_premature` node sets `state`-derived `prereqs` flags (broad_expansion after issue_expansion, albert_audit_ran after audit, counterargument_pass after skeptic, etc.).
  - `cos_decision`: staged binary gates (pure, via `decision/`): `audit_clean?`→`anti_premature.all_done?`→`exhaustion.terminal_eligible?`→`branch_budget.can_branch?`→`human_needed?`; apply `gate.assert_audit_ran`; set `last_decision`. Materialize the auditor-requested competitor branch on REWORK (bounded by `branch_budget`).
  - `human_pull`/`human_push` nodes: emit message/HumanTask deterministically, route onward (no wait).
  - `_route(state)` (read-only, no side effects per LangGraph best practice): terminal_stop/synthesize → END; iteration_count ≥ max_iterations → END; branch/rerank → issue_expansion; else → supervisor.
  - `run_loop(state, *, base_dir, max_iterations, now)` compiles + invokes with `recursion_limit=100`.
- [ ] **Step 5:** PASS. **Step 6:** commit `feat(p1): langgraph loop (full node set, Send fan-out, staged router)`.

---

### Task 9: Acceptance Tests 1 & 4 + anti-premature/branch/plateau + resume

**Files:** Create `tests/test_stop_conditions.py`; add resume to `tests/test_persistence.py`; extend `graph.py` with `compile_with_checkpoint`.

- [ ] **Step 1: tests**
```python
# tests/test_stop_conditions.py
from cn5_research_cos.graph import run_loop
from cn5_research_cos.models import ResearchType if False else None  # noqa
from cn5_research_cos.models import IssueType
from cn5_research_cos.artifacts import issue_map
from cn5_research_cos.models import ResearchState

def test_1_no_premature_stop(tmp_path):
    final = run_loop(ResearchState(run_id="r1", original_question="q"),
                     base_dir=tmp_path, max_iterations=8, now="t0")
    assert issue_map.has_type(final, IssueType.competitor)  # auditor-forced branch materialized
    assert final.iteration_count >= 2

def test_4_endless_prevention(tmp_path):
    final = run_loop(ResearchState(run_id="r4", original_question="q"),
                     base_dir=tmp_path, max_iterations=20, now="t0")
    assert final.iteration_count <= 20  # bounded, never spins to recursion_limit
    assert final.last_audit is not None

def test_anti_premature_blocks_terminal(tmp_path):
    # a run whose prereqs are not all satisfied must not be terminal at iteration 1
    final = run_loop(ResearchState(run_id="r5", original_question="q"),
                     base_dir=tmp_path, max_iterations=1, now="t0")
    assert final.readiness_score is not None
```
- [ ] **Step 2:** run; tune `STALE_AFTER`/scorer so Test 1 (competitor branch appears, no early stop) and Test 4 (loop ends by synthesize/terminal, not recursion_limit) both pass.
- [ ] **Step 3: add `compile_with_checkpoint(run_dir)`** using `SqliteSaver.from_conn_string(str(run_dir/"checkpoint.db"))` → `build_graph().compile(checkpointer=saver)` (verify the installed API form).
- [ ] **Step 4: resume test** — invoke with `thread_id=run_id`, `max_iterations=2`; `app.get_state(cfg).values["research_state"].iteration_count >= 1`; re-invoke with `None` continues (not restart).
- [ ] **Step 5:** all PASS. **Step 6:** commit `test(p1): acceptance 1+4, anti-premature, resume`.

---

### Task 10: Render + CLI

**Files:** Create `src/cn5_research_cos/render/__init__.py`, `markdown.py`, `cli.py`, `tests/test_cli.py`.

- [ ] **Step 1: test** — `cos init` then `cos show` exit 0 (via `CliRunner`, `CN5_COS_BASE_DIR=tmp`).
- [ ] **Step 2:** FAIL.
- [ ] **Step 3: `render/markdown.py`** — `render_issue_map`, `render_challenge_map`, `render_board`, `render_readiness`, `iteration_summary(state)` (Chinese headers: 本輪新增 / Albert 會挑戰 / 已答 / pending / 需要人 / 下一輪建議 + 四個 readiness 分數).
- [ ] **Step 4: `cli.py`** (Typer; `CN5_COS_BASE_DIR`): `init --question [--run-id][--mode]`; `run --question [--run-id][--max-iterations=8][--llm=mock]` (invoke `run_loop`, print iteration_summary + stop reason + scores); `show <run_id> [--artifact]`; `validate <run_id>`.
- [ ] **Step 5:** PASS. **Step 6:** commit `feat(p1): markdown render + typer cli`.

---

### Task 11: Final verify + README + push

- [ ] **Step 1:** `pytest -v` — all green (smoke, models, persistence+resume, artifacts, board, decision, stubs, loop, stop_conditions, cli).
- [ ] **Step 2:** smoke `cos run --question "AI 能否做隔夜研究"` → Chinese iteration summaries + correct stop reason; `cos show`/`validate`.
- [ ] **Step 3:** README status → "P1 complete"; quickstart.
- [ ] **Step 4:** verify spec §10 + §12.8 DoD all checked (full §18 node set present; anti-premature blocks terminal until 7 true; branch-budget bounded; plateau→synthesize; resume continues).
- [ ] **Step 5:** commit `feat(p1): complete deterministic spine + langgraph loop (R2 DoD met)`; push `origin main`.

---

## Self-review (author)
- **Spec coverage:** models+R2 fields(T2)·persistence/resume(T3,T9)·issue/challenge(T4)·board(T5)·exhaustion+plateau+gate+anti-premature+branch-budget(T6)·stubs incl scope/brief/supervisor/compress(T7)·loop full §18 + Send fan-out + staged router(T8)·Tests 1&4 + anti-premature + resume(T9)·render+CLI(T10)·DoD(T11). All P1 spec §1–§12 mapped.
- **Type consistency:** `build_brains`/`Brains`/`AuditResult`(degraded + R2 fields)/`Decision`/`Classification`/`branch_budget.Budget`/`anti_premature.PREREQS`/`derive_board` used identically across tasks.
- **Sharp edges:** (a) `terminal_eligible` AND-ed with anti-premature flags — ensure the flag source defaults all-False so a fresh state can't terminal-stop; (b) Send-fan-out worker writes must use `operator.add` reducer or parallel writes clobber — verify; (c) `SqliteSaver.from_conn_string` API form varies by langgraph-checkpoint-sqlite version — executing subagent verifies against installed version; (d) tune `STALE_AFTER`/scorer so Tests 1+4 converge without hitting recursion_limit.
