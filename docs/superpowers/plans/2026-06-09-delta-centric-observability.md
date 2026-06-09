# Delta-Centric Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the COS live-stream cards show what CHANGED (per-stage delta + a per-round research-status dashboard), not static snapshots.

**Architecture:** Pure deterministic renderers read existing state. A transient `obs_prev` cache on `ResearchState` lets each `render_*` diff against its last render; three cheap `TaskCell` fields (updated in `classify_grid_cells`) drive the per-round coverage delta. New `render_research_status` renders two side-by-side columns via `rich.Columns`→string. No new LLM calls, no stored history.

**Tech Stack:** Python 3.12, Pydantic v2, rich, pytest. Windows runner: `PYTHONPATH=src py -3 -m pytest`. Single test: `PYTHONPATH=src py -3 -m pytest tests/test_x.py::test_y -v`.

**Spec:** `docs/superpowers/specs/2026-06-09-delta-centric-observability-design.md`. **Invariant:** render reads existing structured state; no new LLM calls. **Build order:** model (1) → classify bookkeeping (2) → dashboard (3) → per-stage deltas (4) → wire+retire (5) → regression+live (6).

---

### Task 1: Model fields for delta tracking

**Files:** Modify `src/cn5_research_cos/models.py` (`TaskCell` ~136, `ResearchState` ~323). Test: `tests/test_models.py`.

- [ ] **Step 1: failing test** — append to `tests/test_models.py`:
```python
def test_delta_tracking_fields():
    from cn5_research_cos.models import TaskCell, ResearchState, CellStatus
    c = TaskCell(id="x|y", vendor="x", spec_group="y", objective="o")
    assert c.last_status is None and c.last_filled == 0 and c.stalled_cycles == 0
    rs = ResearchState(run_id="r", original_question="q")
    assert rs.prev_coverage == 0 and rs.obs_prev == {}
    # obs_prev is transient: excluded from the persisted dump
    assert "obs_prev" not in rs.model_dump()
```
- [ ] **Step 2: verify FAIL** — `PYTHONPATH=src py -3 -m pytest tests/test_models.py::test_delta_tracking_fields -v`.
- [ ] **Step 3: implement** — in `TaskCell` add (after `notes`):
```python
    # Observability delta (P10b): the status + filled-field count at the previous
    # classify pass, and how many consecutive passes the cell has not changed.
    last_status: "CellStatus | None" = None
    last_filled: int = 0
    stalled_cycles: int = 0
```
In `ResearchState` add (near the output fields):
```python
    # Observability delta (P10b): scalar coverage at the previous dashboard render.
    prev_coverage: int = 0
    # Transient per-stage "previous" cache so each render_* can show its delta.
    # Excluded from the persisted snapshot — rebuilt within a run, NOT domain state.
    obs_prev: dict = Field(default_factory=dict, exclude=True)
```
- [ ] **Step 4: verify PASS** — `PYTHONPATH=src py -3 -m pytest tests/test_models.py -q`.
- [ ] **Step 5: regression** — `PYTHONPATH=src py -3 -m pytest tests/test_models.py tests/test_persistence.py -q`.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/models.py tests/test_models.py && git commit -m "feat(p10b): TaskCell delta fields + ResearchState obs_prev/prev_coverage"`.

---

### Task 2: classify_grid_cells updates delta bookkeeping

**Files:** Modify `src/cn5_research_cos/graph.py` (`classify_grid_cells` ~518). Test: `tests/test_grid_delta.py` (new).

- [ ] **Step 1: failing test** — create `tests/test_grid_delta.py`:
```python
import cn5_research_cos.graph as g
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell, CellStatus,
    EvidenceBundle, FieldObservation, Source, SourceType, SourceQuality)


def _rs():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|f"] = TaskCell(id="NXP|f", vendor="NXP", spec_group="f",
        objective="o", success_criteria=["packet_buffer"])
    return rs


def _bundle_with_obs():
    src = Source(id="S1", title="DS", url="https://nxp.com/x.pdf",
                 source_type=SourceType.primary, quality=SourceQuality.high)
    return EvidenceBundle(query="q", issue_id="NXP|f", sources=[src],
        observations=[FieldObservation(field="packet_buffer", value="128 kB", source_ref="S1")],
        public_exhausted=True)


def test_changed_cell_resets_stall_and_records_moved():
    rs = _rs()
    rs.evidence.append(_bundle_with_obs())
    g.classify_grid_cells(rs)
    cell = rs.task_grid.cells["NXP|f"]
    assert cell.stalled_cycles == 0 and cell.last_status == CellStatus.covered and cell.last_filled == 1
    assert "NXP|f" in rs.obs_prev.get("grid_moved", [])


def test_unchanged_cell_increments_stall():
    rs = _rs()
    rs.evidence.append(_bundle_with_obs())
    g.classify_grid_cells(rs)   # pass 1: covered, stall 0
    rs.obs_prev["grid_moved"] = []
    g.classify_grid_cells(rs)   # pass 2: same evidence -> no change
    cell = rs.task_grid.cells["NXP|f"]
    assert cell.stalled_cycles == 1 and "NXP|f" not in rs.obs_prev.get("grid_moved", [])
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** — replace the loop body in `classify_grid_cells` (in `src/cn5_research_cos/graph.py`) so it records delta bookkeeping. The function becomes:
```python
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
```
- [ ] **Step 4: verify PASS** — `PYTHONPATH=src py -3 -m pytest tests/test_grid_delta.py -v`.
- [ ] **Step 5: regression** — `PYTHONPATH=src py -3 -m pytest tests/test_grid_delta.py tests/test_cell_classify_wiring.py tests/test_loop.py -q`.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/graph.py tests/test_grid_delta.py && git commit -m "feat(p10b): classify_grid_cells records stall/last_status/last_filled + grid_moved"`.

---

### Task 3: render_research_status dashboard

**Files:** Modify `src/cn5_research_cos/observability/reporter.py` (new `render_research_status`). Test: `tests/test_research_status_card.py` (new).

- [ ] **Step 1: failing test** — create `tests/test_research_status_card.py`:
```python
from cn5_research_cos.observability import reporter as R
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell, CellStatus)


def _grid_rs():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    def cell(cid, v, status, filled, total, stalled=0):
        c = TaskCell(id=cid, vendor=v, spec_group="f", objective="o",
                     success_criteria=[f"k{i}" for i in range(total)])
        c.status = status; c.last_filled = filled; c.stalled_cycles = stalled
        return c
    rs.task_grid.cells["NXP|f"] = cell("NXP|f", "NXP", CellStatus.partial, 3, 5)
    rs.task_grid.cells["BCM|f"] = cell("BCM|f", "Broadcom", CellStatus.blocked, 0, 4)
    rs.task_grid.cells["TI|f"] = cell("TI|f", "TI", CellStatus.na, 0, 4, stalled=3)
    rs.prev_coverage = 1
    rs.obs_prev["grid_moved"] = ["NXP|f"]
    return rs


def test_dashboard_shows_headline_delta_and_actions():
    rs = _grid_rs()
    out = R.render_research_status(rs)
    assert "研究現況" in out
    assert "%" in out and "▲" in out          # headline coverage move
    assert "NXP" in out and "Broadcom" in out and "TI" in out
    assert "需要你出手" in out or "需內部" in out  # blocked -> action panel
    # prev_coverage advanced to current total filled (3+0+0 = 3)
    assert rs.prev_coverage == 3


def test_no_progress_cycle_one_line():
    rs = _grid_rs()
    rs.obs_prev["grid_moved"] = []            # nothing moved this cycle
    rs.prev_coverage = 3                       # coverage unchanged
    out = R.render_research_status(rs)
    assert "無新進展" in out
    assert "\n" not in out.strip()             # exactly one line


def test_no_grid_returns_empty():
    rs = ResearchState(run_id="r", original_question="q")
    assert R.render_research_status(rs) == ""
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** — add to `src/cn5_research_cos/observability/reporter.py`:
```python
_STALL_THRESHOLD = 2
_BAR_WIDTH = 10


def _bar(filled: int, total: int) -> str:
    total = max(1, total)
    n = round(_BAR_WIDTH * filled / total)
    return "█" * n + "░" * (_BAR_WIDTH - n)


def _coverage(grid) -> tuple[int, int]:
    """(filled fields, total criteria) across all cells with criteria."""
    f = sum(c.last_filled for c in grid.cells.values())
    t = sum(len(c.success_criteria) for c in grid.cells.values())
    return f, t


def render_research_status(state: "ResearchState") -> str:
    """P10b — per-round research-status dashboard: coverage + round delta (left) and
    the action panel (right), as two columns. One line when nothing moved this cycle.
    Pure/deterministic: reads TaskGrid cell statuses + the delta bookkeeping."""
    grid = getattr(state, "task_grid", None)
    if grid is None or not grid.cells:
        return ""
    filled, total = _coverage(grid)
    prev = getattr(state, "prev_coverage", 0)
    moved = list((state.obs_prev or {}).get("grid_moved", []))
    state.prev_coverage = filled  # advance for next render

    pct = round(100 * filled / max(1, total))
    prev_pct = round(100 * prev / max(1, total))
    # no-progress cycle: nothing moved AND coverage flat -> one line, never reprint
    if not moved and filled == prev:
        blocked = [c for c in grid.cells.values() if c.status.value == "blocked"]
        stalled = [c for c in grid.cells.values() if c.stalled_cycles >= _STALL_THRESHOLD]
        flags = []
        if blocked:
            flags.append("/".join(sorted({c.vendor for c in blocked})) + " 卡住")
        if stalled:
            flags.append("/".join(sorted({c.vendor for c in stalled})) + " 停滯")
        tail = ("（" + " · ".join(flags) + "）") if flags else ""
        return f"研究現況：無新進展{tail}"

    # left column: per-vendor coverage bars + round delta marker
    from collections import defaultdict
    by_vendor: dict = defaultdict(lambda: [0, 0, [], 0])  # filled,total,statuses,stalled
    for c in grid.cells.values():
        agg = by_vendor[c.vendor]
        agg[0] += c.last_filled
        agg[1] += len(c.success_criteria)
        agg[2].append(c.status.value)
        agg[3] = max(agg[3], c.stalled_cycles)
    moved_vendors = {grid.cells[cid].vendor for cid in moved if cid in grid.cells}
    head = f"研究現況  {prev_pct}%→{pct}%  ▲+{pct - prev_pct}%"
    left = [head]
    for vendor in sorted(by_vendor):
        f, t, statuses, st = by_vendor[vendor]
        mark = "▲" if vendor in moved_vendors else ("—停滯" if st >= _STALL_THRESHOLD else "")
        blk = sum(1 for s in statuses if s == "blocked")
        tag = f" ⛔{blk}" if blk else ""
        left.append(f"{vendor:<10} {_bar(f, t)} {f}/{t}{tag} {mark}")

    # right column: action panel
    right = ["待處理:"]
    blocked_vendors = sorted({c.vendor for c in grid.cells.values() if c.status.value == "blocked"})
    if blocked_vendors:
        right.append("需要你出手: " + ", ".join(blocked_vendors) + " 需內部")
    empty = sorted({v for v, agg in by_vendor.items() if agg[0] == 0})
    if empty:
        right.append("最大缺口: " + ", ".join(empty) + " 全空白")
    stalled_v = sorted({c.vendor for c in grid.cells.values() if c.stalled_cycles >= _STALL_THRESHOLD})
    if stalled_v:
        right.append("停滯: " + ", ".join(stalled_v))

    try:
        from rich.columns import Columns
        from rich.panel import Panel
        from rich.console import Console
        import io
        console = Console(file=io.StringIO(), width=88)
        console.print(Columns([Panel("\n".join(left)), Panel("\n".join(right))]))
        return console.file.getvalue().rstrip("\n")
    except Exception:  # noqa: BLE001 - rich missing/odd width: degrade to stacked text, visibly
        return "\n".join(left) + "\n--\n" + "\n".join(right)
```
- [ ] **Step 4: verify PASS** — `PYTHONPATH=src py -3 -m pytest tests/test_research_status_card.py -v`.
- [ ] **Step 5: regression** — `PYTHONPATH=src py -3 -m pytest tests/test_research_status_card.py tests/test_observability.py -q` (if `test_observability.py` exists; else just the new file).
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/observability/reporter.py tests/test_research_status_card.py && git commit -m "feat(p10b): render_research_status dashboard (coverage + round delta + action panel)"`.

---

### Task 4: Per-stage delta cards (obs_prev)

**Files:** Modify `src/cn5_research_cos/observability/reporter.py` (`render_expand`, `render_research`, `render_critique`, `render_convergence`, `render_decision`; `render_albert` prefix). Test: `tests/test_stage_deltas.py` (new).

- [ ] **Step 1: failing test** — create `tests/test_stage_deltas.py`:
```python
from cn5_research_cos.observability import reporter as R
from cn5_research_cos.models import (ResearchState, EvidenceBundle, Claim, Source,
    IssueNode, IssueType, IssueStatus)


def _rs():
    return ResearchState(run_id="r", original_question="q")


def test_research_delta_counts_new_evidence():
    rs = _rs()
    rs.evidence.append(EvidenceBundle(query="NXP", claims=[Claim(claim="c")],
                                      sources=[Source(id="S1", title="t")]))
    first = R.render_research(rs)
    assert "+1" in first                       # +1 evidence since last (0)
    second = R.render_research(rs)             # nothing new
    assert "本站無動作" in second


def test_critique_delta_counts_new_counterargs():
    rs = _rs()
    n = IssueNode(id="I1", title="t", description="d", issue_type=IssueType.risk,
                  status=IssueStatus.open, impact=3, confidence=2)
    n.counterarguments = ["bias A"]
    rs.issue_map["I1"] = n
    assert "+1" in R.render_critique(rs)
    assert "本站無動作" in R.render_critique(rs)
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** — add a tiny delta helper + make the renderers diff against `obs_prev`. Add near the top of the render helpers in `reporter.py`:
```python
def _delta_count(state, key: str, current: int) -> int:
    """current minus the value stored under obs_prev[key]; updates the store.
    Used by per-stage cards to show 'what changed since I last rendered'."""
    prev = (state.obs_prev or {}).get(key, 0)
    state.obs_prev[key] = current
    return current - prev
```
Rewrite the relevant renderers to LEAD with their delta (keep their existing detail BELOW only when there is a delta):
```python
def render_research(state: "ResearchState") -> str:
    d = _delta_count(state, "research_n", len(state.evidence))
    if d <= 0:
        return "本站無動作"
    lines = [f"+{d} evidence"]
    for b in state.evidence[-d:]:
        top = b.claims[0].claim if b.claims else "(no claim)"
        lines.append(f"  • {b.query}: {top}")
    return "\n".join(lines)


def render_critique(state: "ResearchState") -> str:
    seen = []
    for n in state.issue_map.values():
        for c in n.counterarguments:
            if c not in seen:
                seen.append(c)
    d = _delta_count(state, "critique_n", len(seen))
    if d <= 0:
        return "本站無動作"
    lines = [f"+{d} 反論"]
    for c in seen[-d:]:
        lines.append(f"  • {c}")
    return "\n".join(lines)


def render_expand(state: "ResearchState") -> str:
    d = _delta_count(state, "expand_n", len(state.issue_map))
    if d <= 0:
        return "本站無動作"
    issues = sorted(state.issue_map.values(), key=lambda n: n.impact, reverse=True)
    lines = [f"+{d} issues"]
    for n in issues[:6]:
        lines.append(f"  • [{n.issue_type.value} impact={n.impact}] {n.title}")
    return "\n".join(lines)


def render_convergence(state: "ResearchState") -> str:
    from ..decision import convergence as _c
    open_n = len(_c.unresolved_challenges(state)) if hasattr(_c, "unresolved_challenges") else 0
    d = _delta_count(state, "convergence_open", open_n)
    arrow = "→" if d == 0 else ("↓" if d < 0 else "↑")
    return f"open challenges {arrow} {open_n}" + (f" ({d:+d})" if d else " (no change)")


def render_decision(decision: "Decision", rationale: str = "") -> str:
    # decision has no state handle; render the chosen action + (optional) rationale.
    label = getattr(decision, "value", str(decision))
    return f"決定: {label}" + (f"  ← {rationale}" if rationale else "")
```
And PREFIX `render_albert` with a one-line delta while keeping its full challenge output:
```python
def render_albert(audit: "AuditResult") -> str:
    # (keep the existing full-challenge body; just prepend a delta line)
    body = _render_albert_body(audit)   # rename the existing implementation to _render_albert_body
    n = len(audit.challenges)
    return f"verdict {audit.verdict.value} · {n} challenge(s)\n{body}"
```
(Where `render_albert` takes `audit` not `state`, it has no `obs_prev`; the prefix is a within-call summary, not a cross-call delta — acceptable per spec: albert shows full content + a summary line.)
- [ ] **Step 4: verify PASS** — `PYTHONPATH=src py -3 -m pytest tests/test_stage_deltas.py -v`.
- [ ] **Step 5: regression** — `PYTHONPATH=src py -3 -m pytest tests/test_stage_deltas.py tests/test_research_status_card.py -q` then any existing observability tests.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/observability/reporter.py tests/test_stage_deltas.py && git commit -m "feat(p10b): per-stage delta cards via obs_prev (research/critique/expand/convergence + albert prefix)"`.

---

### Task 5: Wire dashboard into node_collect + retire thin live cards

**Files:** Modify `src/cn5_research_cos/graph.py` (`node_collect` — emit `render_research_status`; remove the `convergence`/`readiness` live `_report` calls). Test: `tests/test_dashboard_wiring.py` (new).

- [ ] **Step 1: failing test** — create `tests/test_dashboard_wiring.py`:
```python
import cn5_research_cos.graph as g
from cn5_research_cos.observability import reporter as R


def test_research_status_emitted_in_collect(monkeypatch):
    calls = []
    monkeypatch.setattr(g._obs, "render_research_status", lambda rs: "DASH")
    # capture _report stage names
    orig = g._report
    def spy(state, name, fn, *a):
        calls.append(name)
        return orig(state, name, fn, *a)
    monkeypatch.setattr(g, "_report", spy)
    from cn5_research_cos.models import ResearchState, TaskGrid
    state = {"research_state": ResearchState(run_id="r", original_question="q", task_grid=TaskGrid()),
             "now": "t", "worker_results": [], "prereqs": {}}
    g.node_collect(state)
    assert "research_status" in calls
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** — in `node_collect`, after the existing `classify_grid_cells(rs)` call, add:
```python
    _report(state, "research_status", _obs.render_research_status, rs)
```
And in the graph, REMOVE (or comment with a one-line rationale) the live `_report(state, "convergence", ...)` and `_report(state, "readiness", ...)` calls — the dashboard subsumes them (they remain computed; they're just no longer emitted as headline live cards). Locate them with `grep -n "_report(state, \"convergence\"\|_report(state, \"readiness\"" src/cn5_research_cos/graph.py` and remove those specific calls only. If a render is needed for `debate.md`, leave the underlying compute; only drop the `_report` emit.
- [ ] **Step 4: verify PASS** — `PYTHONPATH=src py -3 -m pytest tests/test_dashboard_wiring.py -v`.
- [ ] **Step 5: regression** — `PYTHONPATH=src py -3 -m pytest tests/test_dashboard_wiring.py tests/test_loop.py tests/test_loop_metrics.py -q` (loop tests confirm the graph still runs; if loop_metrics needs a live subprocess and hangs, skip it and note).
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/graph.py tests/test_dashboard_wiring.py && git commit -m "feat(p10b): emit research-status dashboard in node_collect; retire convergence/readiness live cards"`.

---

### Task 6: Full regression + live real-scenario verification

**Files:** none (verification).

- [ ] **Step 1: full deterministic suite** — `powershell -NoProfile -Command "Get-Process python,py -ErrorAction SilentlyContinue | Stop-Process -Force"` then:
`PYTHONPATH=src py -3 -m pytest -q -p no:cacheprovider -m "not llm" --ignore=tests/test_cli.py --ignore=tests/test_cli_hitl.py --ignore=tests/test_cli_sot.py --ignore=tests/test_cos_watch.py --ignore=tests/test_sot_clarifier.py --ignore=tests/test_loop_real.py --ignore=tests/test_loop_metrics.py`
Expected: all green. Fix any renderer test that asserted the OLD snapshot card text (update to the new delta text).
- [ ] **Step 2: render smoke (no LLM)** — write a tiny throwaway driver that builds a `ResearchState` with a populated `TaskGrid` (mixed covered/partial/blocked/na/open cells, a `grid_moved` list, a `prev_coverage`) and prints `render_research_status(rs)` and one cycle of the per-stage cards, so the dashboard is seen ON SCREEN with the real renderer (no LLM). Confirm: headline `X%→Y% ▲`, per-vendor bars, action panel, and the no-progress one-liner path (run twice — second with nothing moved). Paste the rendered output.
- [ ] **Step 3: live real-scenario (opt-in, clean env — NOT nested)** — run the actual COS pipeline far enough to emit at least one real `research_status` card on screen (e.g. the existing mock-LLM `run_loop` path, which exercises node_collect→classify→render without a live `claude` subprocess: `PYTHONPATH=src py -3 -c "from cn5_research_cos.graph import run_loop; from cn5_research_cos.models import ResearchState; run_loop(ResearchState(run_id='dash-demo', original_question='q'), base_dir='runs', max_iterations=3, now='t0')"` with stdout shown). Confirm a research-status card renders during the run and that a no-progress cycle prints the one-liner (not a reprinted board). Capture the on-screen output.
- [ ] **Step 4: commit any fixes** — `git add -A && git commit -m "test(p10b): full regression green; dashboard rendered live"`.

---

## Self-review notes
- **Spec coverage:** §A(per-stage delta)→T4, §B(dashboard A∪B + no-progress)→T3, §C(cell delta bookkeeping)→T1+T2, §D(wire+retire)→T5, §E(testing)→every task, §F(YAGNI: no values, no TUI, no history, no P10a-logic-change)→honored (T3 uses Columns→string not Live; deltas from obs_prev + 3 cell fields).
- **Type consistency:** `obs_prev` dict key conventions — `grid_moved` (T2 writes, T3 reads), `research_n`/`critique_n`/`expand_n`/`convergence_open` (T4 `_delta_count`); `prev_coverage` (T1 defines, T3 reads+advances); `_coverage`/`_bar`/`_delta_count` helpers (T3/T4 define + use).
- **Invariant:** every renderer reads existing state only; zero LLM calls; deterministic (no wall-clock).
- **Live (real-scenario):** T6 Step 2 (render smoke) + Step 3 (mock-LLM run_loop emitting the card on screen) — the user asked to SEE it; both print rendered output, no live `claude` subprocess needed.
