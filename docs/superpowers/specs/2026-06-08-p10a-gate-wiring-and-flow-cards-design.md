# P10a — Gate Wiring + Flow-Card Living Doc — Design

**Date:** 2026-06-08
**Status:** approved (design); pending spec review
**Builds on:** P9 (`docs/spec/2026-06-05-phase9-evidence-exhaustion-loop-design.md`)

## Goal

Two coupled pieces, one spec:

1. **Wire the three already-built-but-unwired deterministic gates** into the
   research/classification flow: `grade_source` (CRAG), `triangulate`
   (cross-source), `public_exhausted` (explicit exhaustion gate).
2. **Establish the P9/P10a flow as a living design artifact** — a flow diagram
   plus a summary card for every node and every loop, kept in sync with the code
   via a card↔file cross-reference table.

## Core invariant (unchanged, reinforced)

**The LLM only EXTRACTS structured observations; ALL decisions (grade /
triangulate / exhaustion / classification) are deterministic code.** `n/a` must
be code-provable: a field is `na` only when public modalities were genuinely
exercised and still produced nothing.

## Problem being fixed

P9 shipped `grade_source`, `triangulate`, `public_exhausted` as unit-tested
modules but **nothing in the pipeline calls them** (verified by grep). And
`classify_cell` returns `na` whenever `filled` is empty **without proving the
loop actually exhausted the fetch modality** — a hole: a cell cut off by
`MAX_CELL_ROUNDS` with unfetched doc URLs could be wrongly stamped `na`.

Also: `triangulate` needs per-field `(value, source)` observations, but today
the bundle carries only free-text `claims`. Two free-text claims about the same
field almost never match → "infinite contradiction". So triangulation is
meaningless without a **structured (field→value) observation layer**.

---

## §A — Data model (`models.py`)

New typed observation + two bundle fields. `claims` (narrative) is unchanged;
`observations` is the structured layer the gates consume.

```python
class FieldObservation(BaseModel):
    field: str            # MUST be one of the owning cell's success_criteria
    value: str            # the extracted value, e.g. "128 kB", "4096"
    source_ref: str       # Source.id this value came from
    quote: str = ""       # verbatim span supporting the value
    confidence: int = Field(default=0, ge=0, le=5)

# EvidenceBundle additions:
    observations: list[FieldObservation] = Field(default_factory=list)
    public_exhausted: bool = False   # loop stamps: were public modalities exhausted for this cell?
```

Default-empty so every existing P1–P9 bundle round-trips unchanged.

## §B — Extraction layer (LLM extracts) (`brains/real.py`)

Both extraction passes additionally emit `observations[]`:

- **Round-1 websearch** (`_RESEARCH_SCHEMA`/`_RESEARCH_SYSTEM`/`_user_prompt`):
  include the owning cell's `success_criteria` in the prompt; add an
  `observations` array to the schema `{field, value, quote, confidence,
  source_indices}`.
- **Doc re-extract** (`_extract_from_text` / `_EXTRACT_SCHEMA` / `_EXTRACT_SYSTEM`):
  same — pass `success_criteria`, emit `observations`.
- The researcher resolves the cell via `state.task_grid.cells.get(issue_id)`
  (issue_id == cell.id on the grid path). If no cell / no `success_criteria`,
  `observations` is simply empty (back-compat; behaves like P9).
- Schema still offers **no N/A option** — a field absent from the doc is omitted.

`_build_bundle` maps raw observations → `FieldObservation` (resolving
`source_indices`→`source_ref`), dropping any whose `field` is not in the cell's
`success_criteria` (defensive: the LLM can't invent fields).

## §C — Gate wiring: per-cell synthesis (code decides) (`decision/cell_synthesis.py`, new)

```python
@dataclass
class CellSynthesis:
    filled: set[str]                  # fields with an accepted, triangulated value
    chosen: dict[str, str]            # field -> winning value
    contradictions: set[str]          # fields where sources disagreed
    weak: set[str]                    # fields only weakly_sourced

def synthesize_cell(cell, bundles) -> CellSynthesis:
    # 1. grade every source across the cell's bundles (retrieval_grade.grade_source)
    # 2. DROP observations whose source graded "incorrect" (marketing/low) — junk
    #    does not fill success_criteria. "ambiguous" sources are KEPT AS-IS — no
    #    quality mutation; triangulate already treats a lone medium/secondary
    #    source as weakly_sourced, so "ambiguous" naturally lands as weak.
    # 3. per field: gather surviving [(value, source)] -> triangulation.triangulate
    #       status corroborated|weakly_sourced -> field is FILLED (record chosen value)
    #       status none -> not filled
    #       contradiction flag recorded
    # 4. return filled / chosen / contradictions / weak
```

Reuses `retrieval_grade.grade_source` and `triangulation.triangulate` verbatim —
**this is the wiring**. No LLM. Deterministic.

## §D — Exhaustion + classification (`decision/cell_exhaustion.py`, `graph.py`)

**In the loop** (`brains/real.py::_escalate` / `_escalate_async`): track
`modalities_tried` — `"search"` always (round 1 ran). The **fetch/extract
modality counts as exhausted when no unfetched doc-URL source remains** — this
covers BOTH "fetched every doc we found" AND the vacuous "round-1 found zero doc
URLs" case (you cannot fetch what does not exist). The modality is NOT exhausted
only when the loop exits via `MAX_CELL_ROUNDS` with doc URLs still unfetched.

So the loop's stop-reason directly yields the stamp:

```python
# loop exits when: criteria met, OR todo (unfetched doc URLs) is empty, OR MAX_CELL_ROUNDS
drained = (no unfetched doc-URL source remains)        # fetch+extract exhausted (incl. vacuous)
if drained:
    modalities_tried = {"search", "fetch", "extract"}
bundle.public_exhausted = cell_exhaustion.public_exhausted(
    cell, filled=<synthesize_cell(cell, [bundle]).filled>,
    modalities_tried=modalities_tried, all_modalities={"search","fetch","extract"},
    rounds_no_new=<loop counter>)
# => True when criteria met OR all modalities exhausted OR K rounds no-new;
#    False only when MAX_CELL_ROUNDS cut the loop off with docs left to fetch.
```

The loop's STOP decision also uses `public_exhausted` (the old ad-hoc
"no new doc-source / no new claim" stop becomes the `rounds_no_new` signal
feeding the gate). `MAX_CELL_ROUNDS` remains the hard cap.

**`classify_cell` gains a `public_exhausted: bool` parameter:**

```python
def classify_cell(cell, *, filled, gated_detected, public_exhausted) -> CellStatus:
    if crit and crit.issubset(filled):      return covered
    if gated_detected and not crit ⊆ filled: return blocked   # needs_internal
    if filled:                               return partial
    if public_exhausted:                     return na         # code-proven empty
    return open                              # NOT exhausted -> keep researching next round
```

**`classify_grid_cells` (`graph.py`)** now:
- builds `filled` via `cell_synthesis.synthesize_cell(cell, cell_bundles)`
  (replacing the substring scan over claims),
- `public_exhausted` for the cell = OR of `bundle.public_exhausted` across the
  cell's bundles,
- calls the 5-state `classify_cell`.

The new `open` return reuses the existing `CellStatus.open` (cell stays eligible
for re-selection next loop iteration instead of being prematurely `na`).

## §E — Flow-card living doc

This spec file is the artifact. Below is the full, current flow with a card per
node and per loop, then a card↔file table that MUST be updated whenever a node
moves. (Lightweight manual sync — no code generator, YAGNI.)

### Flow (P10a)

```
[node_orchestrator_plan → Orchestrator.plan]                         (card 1)
        │ TaskGrid: cells + success_criteria + expected_sources
        ▼
[select_research_issues] → selected[] top-K                          (card 0.5)
        │
 ╔═ LOOP A: node_research_fanout (≤MAX_CONCURRENT) ════════════════════════╗
 ║  Phase 1 (async): per issue → research_async                            ║
 ║    [Round-1 WebSearch → _build_bundle: sources+claims+observations]     ║ (card 2)
 ║    ╔═ LOOP B: _escalate evidence-exhaustion (≤MAX_CELL_ROUNDS) ═╗       ║
 ║    ║  doc-URL source unfetched:                                  ║       ║ (card B)
 ║    ║    fetch_and_extract → doc_extract chain                    ║       ║ (cards 3,4)
 ║    ║    _extract_from_text (LLM) → claims + observations         ║       ║ (card 5)
 ║    ║  track modalities; stop via public_exhausted; stamp bundle  ║       ║ (card D1)
 ║    ╚══════════════════════════════════════════════════════════════╝     ║
 ║  Phase 2 (sync): source_critic → ranking → compressor                   ║ (card 2.5)
 ╚══════════════════════════════════════════════════════════════════════════╝
        │ worker_results
        ▼
[node_collect pre: persist sources + reference scan]                 (card 8.0)
        ▼
[classify_grid_cells → synthesize_cell(grade+triangulate) → classify_cell]
        │   grade_source (card 6) · triangulate (card 7) · public_exhausted (card D2)
        ▼  covered / partial / na / blocked / open
[blocked → _mint_blocked_cell_tasks → HumanTask] → [_notify_needs_supplement once/run]  (card 10)
```

### Cards

(Each card: 名稱 / 輸入 / 動作 / 輸出 / 決策者 / 檔案 · 狀態)

- **Card 1 — Orchestrator.plan** · `brains/orchestrator.py` · pre-P10a.
  問題→TaskGrid cells（含 success_criteria/expected_sources）。LLM 產結構，程式組裝。
- **Card 0.5 — select_research_issues** · `graph.py` · pre-P9. 選 top-K issue。純程式。
- **Card 2 — Round-1 WebSearch** · `brains/real.py::research*` · P10a-changed.
  一次 WebSearch → bundle(sources+claims+**observations**)。LLM 抽取。
- **Loop B — _escalate** · `brains/real.py` · P9, P10a-changed. 抓未取 doc-URL→抽取→併回；
  追蹤 modalities；停止改用 public_exhausted；蓋章 bundle.public_exhausted。程式停、LLM 抽。
- **Card 3 — fetch_and_extract** · `brains/retrieval.py` · P9. 下載+抽取；fail-visible。純程式。
- **Card 4 — doc_extract 鏈** · `brains/doc_extract.py` · P9 (docling opt-in). pymupdf4llm→pypdf；docling opt-in。純程式。
- **Card 5 — _extract_from_text** · `brains/real.py` · P9, P10a-changed. 文件全文→claims+**observations**。LLM 抽取，不可宣告 N/A。
- **Card 6 — grade_source** · `decision/retrieval_grade.py` · **P10a-wired** (was unwired). 每來源 correct/ambiguous/incorrect。純程式。
- **Card 7 — triangulate** · `decision/triangulation.py` · **P10a-wired** (was unwired). 每 field 跨源 corroborate/weak/矛盾。純程式。
- **Card 2.5 — critique 鏈** · `run_research_fanout` Phase 2 · pre-P9. source_critic→ranking→compressor。
- **Card 8.0 — node_collect 前置** · `graph.py::node_collect` · pre-P9. persist sources + reference scan（fail-soft）。
- **Card C — synthesize_cell** · `decision/cell_synthesis.py` · **P10a-new**. grade→丟 incorrect→triangulate per field→filled/chosen。純程式。
- **Card D1 — public_exhausted (loop)** · `decision/cell_exhaustion.py` · **P10a-wired**. 迴圈停止 + 蓋章。純程式。
- **Card D2 — classify_cell (5-state)** · `decision/cell_exhaustion.py` · P9, P10a-changed. covered/partial/na/blocked/**open**；na 需 public_exhausted。純程式。
- **Card 8 — classify_grid_cells** · `graph.py` · P9, P10a-changed. synthesize_cell→filled；OR bundle.public_exhausted→classify_cell。純程式。
- **Card 10 — supplement + notify** · `graph.py` · P9. blocked cell→HumanTask；once-per-run email。純程式，fail-soft。

### Card↔file cross-reference (sync table — update on every flow change)

| Card | Symbol | File | Status |
|---|---|---|---|
| 1 | `RealOrchestrator.plan` | brains/orchestrator.py | pre |
| 0.5 | `select_research_issues` | graph.py | pre |
| 2 | `RealResearcher.research/_build_bundle` | brains/real.py | P10a |
| B | `RealResearcher._escalate*` | brains/real.py | P10a |
| 3 | `fetch_and_extract` | brains/retrieval.py | P9 |
| 4 | `extract_doc` | brains/doc_extract.py | P9 |
| 5 | `RealResearcher._extract_from_text` | brains/real.py | P10a |
| 6 | `grade_source` | decision/retrieval_grade.py | P10a-wired |
| 7 | `triangulate` | decision/triangulation.py | P10a-wired |
| 2.5 | `run_research_fanout` Phase 2 | graph.py | pre |
| 8.0 | `node_collect` (pre-classify) | graph.py | pre |
| C | `synthesize_cell` | decision/cell_synthesis.py | P10a-new |
| D1/D2 | `public_exhausted`/`classify_cell` | decision/cell_exhaustion.py | P10a |
| 8 | `classify_grid_cells` | graph.py | P10a |
| 10 | `_mint_blocked_cell_tasks`/`_notify_needs_supplement` | graph.py | P9 |

## §F — Testing

- **Unit:** `FieldObservation` round-trip; `synthesize_cell` (drops incorrect-source
  obs; triangulates per field; contradiction resolved by primary; weak vs
  corroborated); `classify_cell` 5 states incl. `na` requires `public_exhausted`
  and `open` when not exhausted.
- **Integration:** loop emits observations → synthesize → classify end-to-end
  (mock LLM); `_escalate` stamps `public_exhausted` correctly (true exhaustion vs
  MAX_ROUNDS cutoff).
- **Regression:** all existing P1–P9 tests green (observations default empty →
  old paths unchanged; classify_grid_cells with no observations behaves as P9 —
  but note `na`-gate now requires exhaustion; adjust any P9 test asserting `na`
  on a non-exhausted cell).
- **Live (opt-in):** re-run NXP SJA1105; confirm `observations` fill
  VLAN=4096 / queues=8 / CBS, `chosen` values surface, and `na` appears only on
  genuinely exhausted-empty cells.

## Scope boundaries (YAGNI)

- **NOT** doing grade's "ambiguous → refine + re-fetch another round" (extra loop
  cost; rejected during brainstorm).
- **NOT** building an automated card generator — the cross-ref table is manually
  maintained.
- **NOT** fixing Gap B (LLM-hallucinated 404 datasheet URLs / robust retrieval /
  HTML datasheet) — that is a separate follow-up (P10b), explicitly out of scope.

## File change map

| File | Change |
|---|---|
| `src/cn5_research_cos/models.py` | + `FieldObservation`; + `EvidenceBundle.observations`, `.public_exhausted` |
| `src/cn5_research_cos/brains/real.py` | observations in both extraction passes; `_escalate*` track modalities + stamp `public_exhausted`; pass `success_criteria` |
| `src/cn5_research_cos/decision/cell_synthesis.py` | NEW — `synthesize_cell` (wires grade + triangulate) |
| `src/cn5_research_cos/decision/cell_exhaustion.py` | `classify_cell` gains `public_exhausted` param → 5 states |
| `src/cn5_research_cos/graph.py` | `classify_grid_cells` uses `synthesize_cell` + bundle exhaustion |
| `tests/...` | new unit + integration; fix P9 `na` assertions |
| this spec | the living flow-card doc |
