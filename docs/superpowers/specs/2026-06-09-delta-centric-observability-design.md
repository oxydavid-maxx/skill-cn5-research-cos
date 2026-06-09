# Delta-Centric Observability (Research-Status Dashboard + Per-Stage Deltas) — Design

**Date:** 2026-06-09
**Status:** approved (design); pending spec review
**Builds on:** P10a (`docs/superpowers/specs/2026-06-08-p10a-gate-wiring-and-flow-cards-design.md`) — the TaskGrid cell-status machinery this reads.

## Goal

Replace the current valueless per-stage summary cards with **delta-centric** output at two granularities, so a human watching a COS run sees *what changed*, never a static snapshot:

1. **Per-stage (within a round):** every stage card shows what THAT station just produced this invocation (its delta/contribution), or "本站無動作".
2. **Per-round (end of cycle):** one **研究現況 dashboard** — coverage roll-up + round-over-round delta + an action panel, rendered as two side-by-side columns.

## Core principle (one rule, two levels)

**A status card is only worth printing if it conveys CHANGE.** Show the delta, not the snapshot. If a stage did nothing, say so in one line. If a whole cycle produced no progress, print one line, not the board. No new LLM calls — read the structured state that already exists (`agent-deliberation-transparency` principle).

## Problem being fixed

Today's renderers (`observability/reporter.py`) print snapshots: `render_research` shows the last 3 bundles, `render_critique` shows all counterarguments, the coverage view shows absolute counts. Across cycles the same card reprints near-identically — the user cannot tell what moved. Worst case: `research_exhaustion=0/5` next to `next action: synthesize` with no reconciliation.

## §A — Per-stage delta cards

Each `render_*(state)` becomes delta-aware: it reports the change since the **last time that stage rendered** (cycle-over-cycle for that station) plus, where the node knows it, what it produced *this call*.

**Mechanism (no history stored):** a transient cache on `ResearchState`:
```python
    # observability delta cache — per-stage "previous" markers so each render_*
    # can show what changed since it last rendered. Transient (excluded from the
    # persisted snapshot); rebuilt within a run. NOT domain state.
    obs_prev: dict = Field(default_factory=dict, exclude=True)
```
Each renderer computes `current` for its stage, diffs against `state.obs_prev[stage]`, renders the delta, then writes `current` back into `obs_prev[stage]`. Pure except for that self-owned cache write; fully testable by seeding `obs_prev`.

**Per-stage card shapes (examples):**
```
[orchestrator]  +2 格 (Broadcom|fabric, TI|TSN) · 0 移除
[research]      +4 evidence · 新填 NXP CBS, Microchip queues · TI 仍 0
[critique]      +1 反論 (X 有 marketing bias)
[albert]        關閉 C-001 · +0 新挑戰 · verdict continue→exhausted
[decision]      synthesize (was continue_research) ← exhaustion 連 2 輪平
```
Rules: a stage with no change prints `本站無動作`. `render_albert` keeps its FULL challenge output (it is the debate core) but PREFIXES a one-line delta (challenges +N / closed M / verdict X→Y). Counts come from existing fields (`len(state.evidence)`, `issue_map[*].counterarguments`, `albert_challenge_map` statuses, the `Decision` + its prior value, `convergence`/`readiness` numbers).

Stages covered: `expand`, `research`, `critique`, `albert`, `convergence`, `readiness`, `decision`, `orchestrator`. `scope` (objective/north-star, set once) stays a snapshot — it has no per-round delta.

## §B — Per-round 研究現況 dashboard (A∪B layout)

A new `render_research_status(state) -> str`, emitted once per cycle right after `classify_grid_cells` (end of `node_collect`). Two columns via `rich.Columns` rendered to a string (box chars are unicode → still appends to `debate.md` as text; no TUI/Live, no tty dependency):

```
┌─ 研究現況 c3  30%→38% ▲+8% ─┐  ┌─ 待處理 ──────────┐
│ NXP       ██████████░ 5/8 ▲+1│  │ ⛔ Broadcom 3 需內部│
│ Broadcom  ███░░░ 1/8 ⛔3      │  │ 🕳 TI 全空白        │
│ Microchip ████░░ 2/8 ▲+2     │  │ ⚠ TI 停滯 3 輪      │
│ TI        ░░░░░ 0/8 —停滯     │  │                   │
└──────────────────────────────┘  └───────────────────┘
```
- **Left = 現況+round delta** (A's compare, inline as `▲+1 / —停滯`, NOT a reprinted previous-cycle card).
- **Right = 待處理 / action panel** (B): `需要你出手` = blocked(needs_internal) cells; `最大缺口` = lowest-coverage vendor and/or longest-stalled cell.
- **Coverage** = filled success-criteria fields / total, aggregated per vendor (group cells by `cell.vendor`). A "field" is covered when it is in `synthesize_cell(cell, bundles).filled`; the per-cell count is `covered_fields/total_criteria`.
- **Glyph ↔ P10a status:** covered=full bar · partial=half · blocked=⛔ · na=灰/空(灰) · open w/ evidence=研究中 · open w/o evidence=未開始.

**No-progress cycle:** if no cell moved this cycle (every researched cell `stalled_cycles>0` and coverage delta = 0), render ONE line instead of the board:
```
研究現況 c3：無新進展（TI/Broadcom 卡住）
```

## §C — Round-delta mechanism (cell-level, no history)

Two cheap fields on `TaskCell`, updated inside `classify_grid_cells` (the only domain-code change):
```python
    last_status: CellStatus | None = None   # status at previous classify pass
    stalled_cycles: int = 0                 # consecutive classify passes with no change
```
Plus one scalar on `ResearchState`:
```python
    prev_coverage: int = 0   # total covered fields at previous dashboard render (for the headline %)
```
In `classify_grid_cells`, after computing `cell.status` and `syn.filled`:
- compute a per-cell `changed = (cell.status != cell.last_status) or (len(syn.filled) != <prev filled count>)`;
- `stalled_cycles = 0 if changed else stalled_cycles + 1`;
- record `cell.last_status = cell.status`.
The renderer reads these + `prev_coverage` (then updates `prev_coverage`). "moved this cycle" = cells with `stalled_cycles == 0` and a non-open final status; "停滯" = researched cell (has evidence) with `stalled_cycles >= STALL_THRESHOLD` (default 2). "未開始" = `open` with no evidence.

NOTE: to know the per-cell *previous filled count* for `changed`, store it alongside: extend to `last_filled: int = 0` on `TaskCell` (set each pass). (Three TaskCell fields total: `last_status`, `last_filled`, `stalled_cycles`.)

## §D — Replace vs augment

- **Add:** `render_research_status` (the dashboard) as a prominent per-cycle card.
- **Retire from the live stream:** the two thinnest now-subsumed cards — `convergence` (open-count only) and `readiness` (4 raw scores) — their signal is folded into the dashboard (coverage + stall). They remain computed and written to `debate.md` (dev/audit), just not surfaced as headline live cards. (If the user later wants them back, it's a one-line re-enable.)
- **Keep:** `albert` (challenge content), `decision`, and all per-stage delta cards from §A.

## §E — Testing

- **Per-stage delta (§A):** for each touched renderer, a test seeding `obs_prev[stage]` + a state, asserting the rendered delta string (e.g. orchestrator +2 cells; research +N evidence; "本站無動作" when unchanged; albert prefix + full challenges retained).
- **Dashboard (§B):** construct a TaskGrid with mixed statuses + `prev_coverage`; assert headline `X%→Y% ▲`, per-vendor bars with `▲/—`, action panel (blocked → 需要你出手; lowest → 最大缺口); the **no-progress** one-liner path.
- **Round-delta (§C):** `classify_grid_cells` sets `stalled_cycles`/`last_status` correctly across two passes (moved resets to 0; unchanged increments); 未開始 vs 停滯 distinction.
- All pure/deterministic; no LLM, no wall-clock.

## §F — Scope (YAGNI)

- NO per-field value display (no "128 kB"), NO agent rule/threshold reasoning on the cards.
- NO stored per-cycle history / snapshot list — deltas come from the transient `obs_prev` cache + the three `TaskCell` fields.
- NO `rich.Live`/TUI/in-place repaint — plain string blocks emitted via the existing `StageReporter` (keeps file-append + non-tty behaviour).
- Do NOT change P10a classify *logic* — only append the `last_status`/`last_filled`/`stalled_cycles` bookkeeping.

## File change map

| File | Change |
|---|---|
| `src/cn5_research_cos/models.py` | `TaskCell`: +`last_status`, +`last_filled`, +`stalled_cycles`; `ResearchState`: +`obs_prev` (exclude), +`prev_coverage` |
| `src/cn5_research_cos/graph.py` | `classify_grid_cells`: update the 3 TaskCell bookkeeping fields; emit `render_research_status` after classify in `node_collect` |
| `src/cn5_research_cos/observability/reporter.py` | new `render_research_status` (rich.Columns→str); make `render_expand/research/critique/albert/convergence/readiness/decision` delta-aware via `obs_prev` |
| `tests/...` | new unit tests per §E |
| this spec | the design |
