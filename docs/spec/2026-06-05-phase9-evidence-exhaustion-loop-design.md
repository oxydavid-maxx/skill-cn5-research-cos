# Phase 9 — per-cell evidence-exhaustion sub-loop + multi-backend document extraction (design)

> 2026-06-05. The agent's purpose is to **exhaustively find data and research** ("竭盡所能"). A live dogfood proved it does NOT: for NXP SJA1105 the cockpit (and the agent doing it manually) declared `packet buffer / VLAN table / queues / CBS count / package / AEC grade / architecture` as **N/A / NDA-gated** — yet **every one is in the PUBLIC datasheet** (`128 kB frame buffer`, `4096 VLANs`, `8 egress queues/port`, `10 802.1Qav CBS`, `LFBGA159 12×12mm`, `AEC-Q100 Grade 2 −40~+105°C`, `store-and-forward`). The data was one PDF-read away. Root cause: **research per cell is one-shot and snippet-only**, and the **N/A / needs-human decision is made before public sources are exhausted**.

> **DoD:** a cell is only classified `n/a`/`needs_internal` AFTER a per-cell retrieval sub-loop has exhausted public modalities (search → fetch primary → multi-backend PDF/doc extract → reflect → escalate). Web-found public PDFs are auto-extracted. HITL supplement fires ONLY for genuinely-locked sources (myICP/NDA) after public exhaustion. The SJA1105 specs above come back filled+cited, not N/A.

---

## 0. Honesty conventions
`[SOTA]` matches a verified reference pattern (§ref). `[NET-NEW]` = our strengthening beyond typical SOTA. `[HAVE]`/`[ADD]`/`[CHANGE]` = build status. No spec claims a value as N/A/NDA until the §1 exhaustion loop reports `public_exhausted`.

## 1. SOTA Coverage Matrix (MANDATORY — MRC prevention)

| Subsystem | Reference(s) | In our design | Status |
|---|---|---|---|
| Read primary source CONTENT (not just snippets) | GPTR (scrape+read pages), WebThinker (navigate-in) | §A② fetch+read primary | **in_scope** (P9 [ADD]) — was snippet-only |
| Per-subtask "enough? else search-more" reflection loop | ODR `think_tool` gate, Anthropic interleaved-thinking | §A③ reflect + §A exhaustion gate | **in_scope** (P9 [ADD]) — was one-shot |
| Retrieval-depth / modality escalation | Anthropic (multi-tool), WebThinker | §A④ escalate (alt query / fetch / extract / mirror) | **in_scope** (P9 [ADD]) |
| Multi-backend doc extraction w/ fallback | (robustness; no single SOTA) | §B docling→pymupdf4llm→pypdf | **in_scope** **[NET-NEW]** (docling OOM'd live → fallback needed) |
| Auto-extract web-found PDFs | GPTR scrapes any found URL | §B route any fetchable doc → extractor | **in_scope** (P9 [ADD]) — extraction was human-drop-only |
| N/A decided AFTER exhaustion | GPTR/ODR conclude after reading | §C classify post-exhaustion | **in_scope** (P9 [CHANGE]) — was synthesis-time on transient evidence |
| HITL supplement only for locked sources | ANTH (lead asks human for gaps) | §C `needs_internal` after public-exhausted → once/run email | **in_scope** ([HAVE] P5c/P8, re-gated by §C) |
| Embedding source filter / curation | GPTR | [HAVE] P4b | in_scope |
| Outer orchestration loop (plan→audit→dispatch→re-plan) | WDART, ODR, ANTH | [HAVE] P8 | in_scope (unchanged) |
| RL-tuned retriever | OPERA | — | **out** (RL pipeline; not subscription-SDK feasible) |

> Deferred rows: none. Out row carries a reason. R23 (global gate) checks this artifact.

## 2. Component A — per-cell evidence-exhaustion sub-loop (the core) [ADD]

Today `RealResearcher.research(state, issue_id)` does ONE `call_structured_websearch` and returns — snippet-only, single-shot (P2b: "ONE search per issue"). Replace with an inner convergence sub-loop run PER dispatched cell/issue, BEFORE the cell is classified:

```
research_cell(cell) -> CellEvidence:           # inner loop, bounded
  tried = set(); rounds = 0
  while rounds < MAX_CELL_ROUNDS and not _cell_satisfied(cell, evidence):
    ① SEARCH (breadth): query → candidate sources (incl. datasheet/PDF URLs)   [HAVE, reused]
    ② FETCH + READ primary: for each high-value candidate not yet read —
         - HTML/page → fetch + read CONTENT (not snippet)
         - PDF/doc   → download → §B extract → read CONTENT                     [ADD]
    ③ REFLECT (think): which target fields for this cell are still missing?
         emit {got: [...], missing: [...], untried_modalities: [...]}            [ADD]
    ④ ESCALATE on missing: pick an untried modality and loop —
         alt query phrasing / alt source (vendor page, distributor mirror,
         alldatasheet) / "download the datasheet PDF" / different extractor      [ADD]
    rounds += 1; tried |= used_modalities
  return CellEvidence(values{field:(value,[S-id])}, status=_classify(cell))      # §C
```

- **Exhaustion gate** `_cell_satisfied` / `public_exhausted`: satisfied when the cell's target fields are filled OR `K` consecutive rounds add nothing new AND no untried modality remains. Bounded by `MAX_CELL_ROUNDS` (env `CN5_COS_MAX_CELL_ROUNDS`, default 4) + the global cost/wall cap.
- **Target fields per cell** come from the TaskCell's `output_format` (the spec-group's columns) — so the loop knows WHAT it's hunting and when it's "enough".
- Runs inside the existing concurrent fan-out (per cell, bounded by the semaphore) — the OUTER loop and dispatch are unchanged (P8).

**Files:** `brains/real.py` (`RealResearcher` → an exhaustion-loop researcher; keep the `Researcher`/`research_async` Protocol so the fan-out is unchanged), new `brains/retrieval.py` (the modality-escalation + reflect helpers), `decision/cell_exhaustion.py` (the deterministic `public_exhausted` / `_cell_satisfied` gate).

## 3. Component B — unified multi-backend document extraction [ADD/CHANGE]

Today docling is the only backend and only runs on human-dropped reference files; docling **OOM'd live** (`std::bad_alloc`) with no fallback, and web-found PDFs never reach it.

- **Fallback chain** `extract_doc(path) -> (text, backend_used)`: try **docling** → on failure (OOM/parse/exit) try **pymupdf4llm** → then **pypdf**. Each failure is recorded VISIBLY (degrade-with-warning, never silent). Live-proven: docling OOM → pymupdf4llm extracted 72,894 chars from SJA1105. (Honor the v7 docling-strict gotcha: pymupdf4llm exits 2 on fragments → call the lib directly in the fallback, not the strict CLI policy.)
- **Route web-found docs through it:** when §A② hits a candidate whose URL is a fetchable doc/PDF, download to the per-topic reference store and run `extract_doc` — public datasheets get read, not just human-dropped files. Unify the web and internal-doc paths at the extractor.

**Files:** `brains/doc_extract.py` (the fallback chain), `brains/internal_doc.py` ([CHANGE] use the chain), `brains/retrieval.py` ([CHANGE] download+extract web-found PDFs into the reference store).

## 4. Component C — classify AFTER exhaustion; HITL only for locked [CHANGE]

Move the `n/a` / `needs_supplement` decision out of synthesis-time-on-transient-evidence into the per-cell loop's exit:
- `covered` / `partial` — target fields filled (cited) by the loop.
- `n/a (public-exhausted)` — the loop tried search+fetch+all extract backends+alternate sources and the field genuinely is not in ANY public source. (Honest N/A, earned.)
- `needs_internal` — the field exists but is behind a registration/NDA wall the loop DETECTED (e.g. a vendor page that gates the datasheet behind myICP/login). ONLY this status feeds the once-per-run consolidated supplement email (P8 §5) asking the human to drop the locked doc into the reference store.

So HITL-ask-human fires precisely for genuinely-locked sources after public exhaustion — never (as happened live) a silent premature N/A, and never (the inbox-flood) for things the loop could have fetched.

**Files:** `decision/cell_exhaustion.py` (`classify_cell`), `synthesis/memo.py` ([CHANGE] `route_citations` consumes the cell status instead of re-deciding on transient evidence), `graph.py::_notify_needs_supplement` ([CHANGE] source from `needs_internal` cells).

## 5. Deterministic vs LLM
LLM: the per-cell reflect (`think`: got/missing/untried) + the existing researcher search synthesis. Everything else deterministic: the exhaustion gate, modality escalation order, the extraction fallback chain, doc download/routing, cell classification, HITL routing.

## 6. SOTA grounding (§ref)
- GPTR — scrapes + reads page CONTENT per sub-query, not snippets ([DeepWiki](https://deepwiki.com/assafelovic/gpt-researcher/1-overview)).
- Anthropic — subagents do iterative search with interleaved-thinking after each tool result to find gaps + refine ([engineering](https://www.anthropic.com/engineering/multi-agent-research-system)).
- ODR — per-subagent `research → search → think_tool(enough?) → loop → compress` ([internals](https://www.bolshchikov.com/p/open-deep-research-internals-a-step)).
- WebThinker — Deep Web Explorer navigates INTO pages ([MarkTechPost](https://www.marktechpost.com/2025/05/06/this-ai-paper-introduce-webthinker-a-deep-research-agent-that-empowers-large-reasoning-models-lrms-for-autonomous-search-and-report-generation/)).
- Proof case — SJA1105 datasheet ([NXP](https://www.nxp.com/docs/en/data-sheet/SJA1105.pdf)): 128kB buffer / 4096 VLAN / 8 queues / 10 CBS / LFBGA159 / AEC-Q100 Grade2 — all public, all wrongly N/A'd one-shot.

## 7. Tests / DoD
- **A (exhaustion loop):** a cell with a target field absent from search snippets but present in a (mocked) fetched primary doc → the loop fetches+reads+fills it (not N/A); a field absent from ALL mocked modalities → `n/a (public-exhausted)` only after K rounds; bounded by MAX_CELL_ROUNDS. (mock search/fetch)
- **B (extraction fallback):** docling raising → pymupdf4llm used → text returned + backend recorded; all backends fail → visible gap, not silent. A web-found PDF URL → downloaded to reference store + extracted.
- **C (classify + HITL):** `needs_internal` (gated-source detected) → once-per-run supplement email; `n/a (public-exhausted)` → NO email (earned N/A); `covered` → cited value. No premature N/A on a field reachable by any modality.
- **Regression:** P1–P8 green; the outer orchestration loop unchanged.
- **Live (opt-in):** re-run switch-PK → NXP SJA1105 row comes back with 128kB buffer / 4096 VLAN / 8 queues / 10 CBS / AEC-Q100 Grade2 filled+cited (not N/A); only genuinely myICP-locked fields → supplement email.

## 8. Pipeline / sequencing
spec → writing-plans → subagent-driven-development (TDD, P1–P8 green) → live switch-PK re-run proving the SJA1105 specs fill. The §9 global gate (R23 SOTA-Alignment) and the P8 fixes are prerequisites already on main.
