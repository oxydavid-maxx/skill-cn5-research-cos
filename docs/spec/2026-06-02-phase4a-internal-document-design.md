# Phase 4a — internal-document research via paperwork scripts-as-toolbox (design)

> 2026-06-02. Decided via multi-round discussion. Builds on P2b (real brains, `Researcher` Protocol + `EvidenceBundle`), P3 (HITL + auto + H0 preflight fields). Parent: `docs/spec/phases-P2-P6-spec.md` (P4). P4 is SPLIT into **P4a (this — internal-document adapter, the BU-distinctive core)** and **P4b (web worker adapters + two-altitude source ranking + citation-discipline enforcement; deferred)**. DoD = the loop can take a raw internal PDF/datasheet (or an existing paperwork survey) and turn it into a cited `EvidenceBundle` that flows through the same audit-driven loop; P1–P3 tests stay green.

## Core decision — paperwork is a TOOLBOX (scripts), not a second agent (skills)
paperwork (`<gerrit CN5DD2_common>/plugins/paperwork`, v2.13+) has two layers:
- **`scripts/`** — plain deterministic Python CLIs (`pdf_outline_scan.py`, `extract_page_range_pdf.py`, `pdf2md.py` w/ `--backend pymupdf4llm|docling`, `collect_section_evidence.py`, …). No LLM, no agent, no plugin load. **We call these via subprocess.**
- **`skills/`** — markdown SKILL.md (orchestrator, reference-discovery, section-extraction, research-synthesis, …) that a Claude *agent* reads and follows, making LLM judgements + stopping for human confirmation. **We do NOT drive these** — the cockpit already owns that orchestration (LangGraph loop + COS decision + Researcher brain + H0–H6 HITL). Driving paperwork's skills = two orchestrators fighting + duplicate token-costing confirmation stops (rejected as Option B; defer by evidence, like the Albert cascade).

**Verified (not assumed), 2026-06-02:** the scripts are programmatically callable (`--help` confirmed); deps installed: `pymupdf4llm 1.27.2.3`, `docling`, `pymupdf`. A real `docs/paperwork-gateway/i3c-competitor-survey/` artifact exists with `reference-map.yaml` (role enum: standard|datasheet|application-note|whitepaper|market-report|internal-research; requirement_topics; coverage_gaps; extraction_strategy incl. `reuse-a1-fragment`), `spec-index.yaml` (per-fragment `source_pages` + `fragment_path`), `spec.md`. Large-PDF already solved there (MIPI I3C 594pp → 8 subsets/191pp; pymupdf4llm default, docling on-demand for table-heavy).

## Dependency resolution (gerrit, never vendored, never user-local-hardcoded)
- paperwork is an EXTERNAL gerrit dependency. Resolve its home via **`CN5_PAPERWORK_HOME`** (env or config key). Documented default discovery order: (1) `$CN5_PAPERWORK_HOME`; (2) a sibling `cn5dd2/CN5DD2_common/plugins/paperwork` checkout discovered upward from cwd; (3) absent → degrade.
- **NEVER** copy paperwork scripts into this repo (no vendoring). **NEVER** hardcode `D:/D-claude/cn5dd2/...` or any user-local path. README documents: "checkout CN5DD2_common from gerrit; set `CN5_PAPERWORK_HOME`."
- **Preflight check** (`paperwork/locate.py`): verify the home exists + `scripts/pdf2md.py` present; capture paperwork version (from `.claude-plugin/plugin.json`) into run metadata. If absent → the internal-document adapter cleanly **degrades to web-only** with a VISIBLE warning (logged + surfaced), never silent (per silent-staleness / degraded-emission lessons). A degraded internal-doc path may not be presented as if internal evidence was gathered.

## Three-tier consume/generate (token-tiered; "high-quality only")
The internal-document Researcher, per issue, in order:
1. **Tier 1 — opportunistic consume (cheapest, highest quality).** If a relevant high-quality paperwork survey already exists (a gateway folder under `CN5_PAPERWORK_GATEWAY` / a brief-supplied `available_sources` path) whose `requirement_topics` overlap the issue → read its `reference-map.yaml` + `spec-index.yaml` + `fragments/` + `spec.md` → map into `EvidenceBundle`. Zero PDF processing, zero LLM extraction. ("高品質的才使用" — consume only on a genuine topic match, gated by a deterministic overlap check.)
2. **Tier 2 — generate from raw PDF (token-efficient, deterministic + one cheap LLM call).** For raw PDFs (the brief's `internal_documents_available` / a `reference/pdf/` intake) with no existing survey:
   1. `pdf_outline_scan.py <pdf> --keywords <issue keywords> --out outline.json` — locate candidate sections (no LLM).
   2. **our existing cheap Researcher brain** reads the outline → picks target page-range(s) for THIS issue (the chain's ONLY LLM call; structured output `{ranges: [{pages, why, role}]}`).
   3. `extract_page_range_pdf.py <pdf> --pages <N-M,…> --out subset.pdf` — subset target pages only (NEVER whole PDF).
   4. `pdf2md.py subset.pdf --backend docling -o frag.md` — the fragment-of-record backend (paperwork v7.0.1+ `docling-strict` default forbids `pymupdf4llm` for citable fragments, exit 2). docling is model-based and slower than pymupdf4llm (the cost of citation-grade fidelity); pymupdf4llm is only for non-citable scratch and is NOT used here. The subprocess gets a generous explicit timeout so a slow-but-valid docling conversion is never silently killed/truncated. `table_heavy` is now just an outline hint, not a backend selector. — fragment MD.
   5. build a minimal `reference-map`-shaped record (role + source_pages + fragment_path) + cited `Claim`s (verbatim quote from the fragment) → `EvidenceBundle`.
3. **Tier 3 — NOT in P4a.** Full agentic paperwork invocation (drive the `orchestrator` skill via an SDK sub-agent) is the most token-expensive (nested agentic loops + confirmation stops). Deferred; added later only if evidence shows tier-1/2 miss what paperwork's synthesis skills catch.

## Adapter + routing (same hot-swap pattern as `--llm`)
- New `brains/internal_doc.py::InternalDocResearcher` implements the EXISTING `Researcher` Protocol (`research(state, issue_id) -> EvidenceBundle`, plus the async variant for the P2b fan-out). Hot-swappable behind a `--research-source {web,internal,auto}` selector (default `auto`).
- `auto` routing is DETERMINISTIC (Python, no LLM): per issue, internal if the brief marks internal docs/surveys relevant to that issue, else web; `both` when the brief says the issue needs cross-checking internal-vs-market. Routing reads the SOT brief's `available_sources` / `internal_documents_available` (P2a/§8.1). The web `RealResearcher` is unchanged.
- Per-worker selective-extraction discipline (C3) lives entirely in tier-2; the loop/supervisor/parallel-fan-out (already real from P2b accel) are UNCHANGED.

## EvidenceBundle mapping (paperwork → our schema)
- `EvidenceBundle.sources[]` ← reference-map references: `Source{role ← reference-map role enum, title, locator = fragment_path#pages, origin = "internal"}`.
- `EvidenceBundle.claims[]` ← cited findings: each `Claim{text, source_refs → resolvable fragment+pages, verbatim_quote (from fragment, the C2 seed)}`.
- `EvidenceBundle.coverage_gaps[]` ← reference-map `coverage_gaps` (tier 1) / sections the brain wanted but no fragment produced (tier 2).
- Confidence/contradiction are NOT in paperwork → derived by our existing `RealSourceCritic` / `RealSkeptic` downstream (unchanged). Full verbatim-≥0.85 enforcement + flatten-to-primary = P4b; P4a only PRESERVES the verbatim quote paperwork already carries.

## Paperwork version contract
We target the gerrit paperwork plugin at its `docling-strict` (v7.0.1+) behavior. Concretely: `pdf2md.py`'s `backend_policy` defaults to `docling-strict`, so `--backend pymupdf4llm` is REFUSED (exit 2) for fragment-of-record output. Our evidence IS fragment-of-record (the cockpit cites it for citation discipline), so docling is the ONLY valid backend for tier-2 — used always, regardless of `table_heavy`. A script policy-error (or any paperwork-script non-zero exit / timeout / launch failure) surfaces as a DISTINCT extraction-FAILURE gap (`internal_doc.has_extraction_failure(bundle)` is True, a visible `logger.error` is emitted, and NO sources/claims are fabricated) — it is NEVER masked as a benign "no relevant content" gap (silent-staleness / degraded-emission discipline). docling being model-based makes tier-2 slower than the old pymupdf4llm default; that is the accepted cost of citation-grade fidelity, and the subprocess timeout is sized generously (not the fast-script default) so a slow-but-valid conversion is not killed.

## H0 preflight intake (ties to P3)
At preflight, when the brief indicates internal docs are relevant, prompt the user (chief-of-staff style, minimal) to drop available references into `reference/pdf/` OR point at a gerrit paperwork survey folder. Populates the brief's `available_sources` / `internal_documents_available`. The most convenient user flow: drop raw PDFs (tier 2) OR point at an existing survey (tier 1); the adapter handles both.

## Deterministic-vs-LLM split (per §14)
- **Deterministic:** dependency resolution, tier selection, topic-overlap gate, subprocess calls (outline/extract/convert), EvidenceBundle assembly, routing. All unit-testable without LLM.
- **LLM (narrow, one call/issue in tier 2):** the page-range picker (outline → ranges, structured output). Reuses the existing cheap brain + sdk_client isolation.

## Tests / DoD
- **Deterministic (no LLM, no network):**
  - dependency resolution: `CN5_PAPERWORK_HOME` honored; sibling-checkout discovery; absent → degrade-to-web-only with a visible warning (assert the warning + that internal evidence is not faked).
  - tier-1 consume on the REAL `i3c-competitor-survey` fixture (read-only, committed pointer or copied minimal fixture) → schema-valid `EvidenceBundle` with sources (roles), cited claims (resolvable fragment+pages), coverage_gaps. Topic-overlap gate: matching topic consumes, non-matching skips.
  - tier-2 chain with the scripts MOCKED (fake subprocess returning canned outline/subset/frag) + a SCRIPTED fake page-range brain → deterministic `EvidenceBundle`; assert NEVER whole-PDF (pages always a bounded subset), pymupdf4llm default / docling only on table-heavy flag.
  - `auto` routing low/web vs internal vs both on hand-built briefs.
  - `--research-source` hot-swap leaves the loop + P1/P2/P3 tests green.
- **Live (opt-in `CN5_COS_LLM_TESTS=1` and `CN5_PAPERWORK_HOME` set):** tier-2 runs the REAL paperwork scripts on a small real PDF (outline → extract a page range → pdf2md) and the real page-range brain → a cited `EvidenceBundle`; skip cleanly if either is unset. (Prior-increment lesson: a live-only subprocess/encoding bug can pass mocked tests — so one real-script live test is required.)
- Committed; push on user confirmation.

## Out of scope (explicit)
- paperwork **skills** invocation / full agentic generation (Option B / tier 3) — deferred.
- Web worker adapters (`gpt_researcher`/`odr`), two-altitude source ranking, full citation-discipline enforcement (verbatim-≥0.85 fuzzy, flatten-to-primary) — **P4b**.
- Parallel fan-out (already real, P2b accel). Final memo / synthesis (P5). Real external Albert (P6).
