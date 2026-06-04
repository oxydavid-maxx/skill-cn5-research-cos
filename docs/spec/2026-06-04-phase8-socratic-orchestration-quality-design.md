# Phase 8 — Socratic clarification + reusable orchestration loop + SOTA-aligned quality (design)

> 2026-06-04. P8 closes the architecture gap the AI-Escape-MRC run (`sota-gate-orchestrator-miss`) found: the orchestration layer was scoped to MVP at P2b ("LLM decompose, no grounding"; "ONE search per issue, no fan-out"), deferred to "P4/later", and never scheduled — so a single-level decompose + top-K became the permanent architecture by default. SOTA (ODR / GPT-Researcher / Anthropic / WebWeaver / WebDART) does large research as an **adaptive plan → reflect → parallel-delegate → audit → re-plan** loop fronted by **human clarification**. P8 makes the cockpit do that, and — per the MRC prevention — **carries a SOTA Coverage Matrix so the orchestration layer can never again be silently scoped out**.

> **DoD:** the cockpit (1) refuses to start research until a multi-round Socratic dialogue has pinned the question, decision-anchor, scope, success-form and constraints; (2) runs a reusable orchestration loop that re-decomposes adaptively every cycle from prior results + Albert challenges + coverage gaps; (3) delivers a findings-first cited report; (4) stays within an 8-hour / cost cap; (5) every layer is mapped against ODR/GPTR/Anthropic in the SOTA Coverage Matrix below with honest in_scope / deferred(+owner) / out labels. P1–P7 stay green.

---

## 0. Honesty conventions used in this spec

Each subsystem is tagged:
- **[SOTA]** — matches a verified reference-architecture pattern (citation in §1).
- **[NET-NEW]** — our deliberate strengthening BEYOND typical SOTA (not industry-standard; labelled so, never sold as standard).
- **[HAVE]** — already built (P1–P7). **[ADD]** — built in P8. **[CHANGE]** — existing node changed in P8.

---

## 1. SOTA Coverage Matrix (MANDATORY artifact — MRC prevention MRC-NC/TRC-NC)

Reference systems (verified 2026-06-04 via primary sources, §ref):
- **ODR** = LangChain Open Deep Research (LangGraph supervisor + think_tool + ConductResearch sub-agents + compress + report).
- **GPTR** = GPT-Researcher (planner → parallel executors → curation → publisher).
- **ANTH** = Anthropic multi-agent research (lead orchestrator → plan-to-memory → 3-5 parallel subagents → reflect → CitationAgent).
- **WW** = WebWeaver (dynamic outline, hierarchical section-by-section synthesis, per-subtask targeted retrieval).
- **WDART** = WebDART (dynamic decomposition + re-planning).
- **LG-HITL** = LangGraph human-in-the-loop plan-and-execute (interrupt + approve/edit/reject + checkpoint resume).

| Subsystem | Reference(s) | In our design | Status |
|---|---|---|---|
| Human clarification before research | ANTH (light), Ask-to-Clarify, AGENT-CQ | §2 multi-round Socratic, blocking | **in_scope** (P8). Multi-round-until-pinned is **[NET-NEW]** vs typical one-shot clarify. |
| Research brief | ODR brief-writer, GPTR | §2 brief locked by the dialogue | **in_scope** ([HAVE], grounded by §2) |
| Planner / decomposition | GPTR planner, ANTH decompose, WW outline | §3 ① orchestrator builds task grid | **in_scope** (P8 [ADD]) — was single-level only |
| Adaptive re-decomposition each cycle | WDART, ODR supervisor reflect-loop | §3 ⑥→① re-plan from results+challenges+gaps | **in_scope** (P8 [ADD]) — was re-rank only |
| Structured task grid = report sections | WW, WebThinker section-aware | §4 vendor×spec-group cells ↔ report rows | **in_scope** (P8 [ADD]) |
| Subtask spec {objective, output-format, tools, boundaries} | ANTH | §3 ① per-cell spec | **in_scope** (P8 [ADD]) — issue nodes were thin |
| Self-reflection before dispatch | ODR think_tool | §3 ②(a) | **in_scope** (P8 [ADD]) |
| Independent audit of the plan | — (SOTA uses self-reflection only) | §3 ②(b) Albert plan-audit | **in_scope** **[NET-NEW]** (honest: not SOTA-standard) |
| Human plan approval | LG-HITL ("Plan it, Review it, Execute it") | §5 H7 first-cycle + major re-plan | **in_scope** (P8 [ADD], [SOTA]) |
| Parallel sub-agent dispatch | ODR ConductResearch, ANTH, GPTR | §3 ③ supervisor top-K + asyncio.gather | **in_scope** ([HAVE] P2b-accel) |
| Per-subagent own context window | ANTH, ODR | §3 sub-agent compress→return condensed | **in_scope** ([HAVE]) |
| Search → reflect → refine in subagent | ANTH interleaved-thinking, ODR think_tool | §3 sub-agent research→reflect→critic | **in_scope** ([HAVE], P4b critic) |
| Compress before return | ODR compress, GPTR context-mgmt | §3 compress | **in_scope** ([HAVE]) |
| Results audit / drift check | ANTH reflect (self) | §3 ⑤ Albert results-audit | **in_scope** **[NET-NEW strengthening]** (SOTA self-reflects; we use external Albert) |
| Section-aware synthesis (merge-and-edit) | WW, WebThinker | §3 synthesize: cell→row | **in_scope** (P8 [CHANGE] synthesis) |
| Citation pass | ANTH CitationAgent, ODR/GPTR numbered | §3 cite (verbatim≥0.85 / flatten-to-primary) | **in_scope** ([HAVE] P4b). Verbatim-verify is **[NET-NEW]** (both refs prompt-only) |
| Embedding source filter | GPTR EmbeddingsFilter 0.35 | small-input short-circuit (no embeddings) | **in_scope** ([HAVE] P4b, faithful to GPTR small-input regime) |
| Source curation (5-dim) | GPTR curator | opt-in curator | **in_scope** ([HAVE] P4b) |
| Hard cost/time cap | (production guidance, $5-30/session) | §6 E1 8h + cost cap | **in_scope** (P8 [CHANGE] default 8h) |
| Model tiering by role | ANTH (lead vs subagent), ODR | §6 E2 Sonnet research / Opus synth / Opus Albert | **in_scope** (P8 [CHANGE]) |
| Document/internal research | paperwork toolbox | internal_doc researcher | **in_scope** ([HAVE] P4a) |
| RL-tuned planner (OPERA-style) | OPERA arxiv 2508.16438 | — | **out** (reason: needs RL training pipeline; not subscription-SDK feasible; revisit only on evidence) |
| Embedding-based RAG over a vector store | classic RAG | — | **out** (reason: subscription SDK has no embedding key; small-input regime; WebSearch + paperwork cover retrieval) |

> Deferred rows MUST name an owner+phase; out rows MUST give a reason. There are currently **no deferred rows** (everything large-research-core is in_scope for P8); the two **out** rows carry reasons. This is the artifact R23 (the global gate, §9) will check.

---

## 2. Component A — Socratic clarification (H0 upgrade) [ADD/CHANGE]

**Problem it fixes:** the switch-PK dogfood ran `run-auto`, which skipped clarify, so nobody pinned the decision-anchor → research finished only able to ask "what's this for?". SOTA note: LLM agents "overhedge or implicitly guess users' intent rather than asking" (Ask-to-Clarify) — exactly that failure.

**Behaviour:**
- After `intake`, enter a **mandatory, multi-round** clarification loop. The cockpit's LLM **asks** targeted Socratic questions; **the human answers** (the LLM never answers on the human's behalf). One question-cluster per round; reflect; ask again until converged.
- **Convergence criterion (all four must be pinned):**
  1. **Purpose / decision-anchor** — what decision will this research feed (RFQ scoring / selection / investment / definition reference …).
  2. **Scope boundaries** — what is in / out (e.g. silicon-only vs incl. roadmap).
  3. **Success form** — the exact deliverable shape (which table, which columns are load-bearing).
  4. **Constraints** — NDA / public-only / time / depth caps; plus an intake of **existing material** the human can drop into the per-topic reference store.
- **AFK default = PAUSE at clarify** (do NOT proceed on assumptions). Opt-in override: the human passes `--assume-brief <file>` / says "best-effort, run on my stated assumptions" → the cockpit proceeds with the stated assumptions **recorded verbatim in the brief** and surfaced in the deliverable.
- **Output:** a locked `research_brief` + `decision_criterion` (sets `state.default_research_priority`, so the in-loop H1 "criterion unknown" pause rarely fires) + `success_form` + the **seed task-grid axes** (feeds §4).

**[NET-NEW] honesty:** multi-round-until-pinned exceeds typical one-shot SOTA clarify; documented as our strengthening.

**Files:** `decision/clarify.py` (new convergence check, 4-criterion), `graph.py::node_clarify` ([CHANGE] H0 from one-shot to loop), `brains/clarifier.py` (new: generates Socratic questions from the gap between the current brief and the 4 criteria), `models.py` (add `decision_criterion`, `success_form`, `clarify_converged` to `ResearchState`).

---

## 3. Component B — reusable orchestration loop (the core) [ADD/CHANGE]

**The loop head moves from `supervisor` to `orchestrator(re-plan)`.** Every cycle runs the SAME spine; the previous cycle's audit feeds the next re-plan (not an orphan front stage).

```
WRITE BRIEF →
┌─ OUTER ORCHESTRATION LOOP (reused every cycle) ───────────────────────┐
│ ① PLAN / DECOMPOSE  [ADD]                                              │
│    orchestrator builds/updates the structured task grid (§4);          │
│    each cell = subtask spec {objective, output-format, tools, boundary}│
│    input = prior results + prior Albert challenges + coverage gaps     │
│ ② REFLECT + AUDIT                                                      │
│    (a) self-reflect think: which cells next?            [ADD][SOTA]    │
│    (b) Albert plan-audit (flash, skip if plan unchanged)[ADD][NET-NEW] │
│    (c) H7 human plan-approval (first cycle + major re-plan) [ADD][SOTA]│
│ ③ DISPATCH supervisor top-K uncovered/high-impact cells [HAVE]         │
│    → per-cell parallel sub-agents (own context):                       │
│       research(websearch) → reflect gaps → source-critic → compress    │
│ ④ COLLECT + skeptic  [HAVE]                                            │
│ ⑤ AUDIT RESULTS (Albert): quality/drift; challenges → next ① [HAVE]   │
│ ⑥ READINESS / DECIDE  [CHANGE: loop-back target = ①, not supervisor]   │
│    ├ converged (grid covered + Albert satisfied) → exit → synthesize   │
│    ├ cap hit (8h / cost) → exit → synthesize (degraded-honest)         │
│    ├ critical claim unverifiable → H3-family supplement email (once)+↻ │
│    ├ all paths blocked / high-risk drift → H5/H1/H2 pause + email      │
│    └ else → loop back to ① (re-plan)                                   │
└───────────────────────────────────────────────────────────────────────┘
→ SYNTHESIZE (Opus, section-aware: each cell → a report row) → CITE → DELIVER
```

**SOTA grounding:** ODR (supervisor + think_tool + ConductResearch + compress), ANTH (orchestrator-worker, plan, 3-5 parallel, reflect, CitationAgent), WDART (dynamic decomposition + re-planning = the ⑥→① adaptive re-plan), WW (section-by-section synthesis).

**Files:** `graph.py` ([CHANGE] insert `node_orchestrator_plan` as loop head; `_route_after_decide` loops to it not supervisor; add `node_plan_audit` flash seam + `node_plan_approval` H7), `brains/orchestrator.py` (new: builds/updates the task grid), `decision/audit_tier.py` ([CHANGE] add the plan-audit flash tier).

---

## 4. Component C — structured task grid (section-aware) [ADD]

- **Axes (decision, §11 calibration):** default **vendor × spec-group** (2-axis). Cells where the matrix is sparse collapse; for product-dense vendors a cell may expand to **vendor × part-number × spec-group** (3-axis) on demand.
- **Each cell ↔ one report row/section** → synthesis is **merge-and-edit**, not free-form (WW/WebThinker). N/A is a first-class cell state.
- **Coverage tracking per cell:** `covered | partial | blocked(NDA/internal) | n/a(no public data) | open`. The grid IS the convergence signal (⑥): converged when no `open` high-impact cell remains AND Albert satisfied.
- Persisted in the per-topic reference store (P7 B) so re-runs accumulate.

**Files:** `models.py` (`TaskCell`, `TaskGrid`), `brains/orchestrator.py`, `brains/reference_store.py` ([CHANGE] persist/restore the grid).

---

## 5. Component D — HITL gates: H0–H6 unchanged + H7 new [CHANGE/ADD]

**Existing H0–H6 (code-grounded, P3) — names/numbers NOT changed:**

| Gate | Meaning | Where | Blocking |
|---|---|---|---|
| **H0 preflight** | clarify (UPGRADED to §2 multi-round Socratic) | front | yes |
| **H1 pull-direction** | direction unclear → pull human (high-risk) | loop ⑥ | yes |
| **H2 call-decision** | a decision needs the human | loop ⑥ | yes |
| **H3 push-human** | needs internal data → HumanTask, continue adjacent | loop ⑥ | no |
| **H4 ad-hoc steering** | `cos steer <run_id> "..."` → next cycle re-ranks/branches | loop, anytime | no (human-initiated) |
| **H5 call-help** | hard blocker → interrupt (even in auto) | loop ⑥ | yes |
| **H6 final-review** | interrupt before synthesize/terminal (confirm/revise) | exit | yes |

**New:**
| **H7 plan-approval** | human OKs the task-grid decomposition before expensive research; **first cycle always; subsequent cycles only on a MAJOR re-decomposition** (new top-level branch / grid axis change), small re-ranks do NOT re-prompt | loop ②(c) | yes (first cycle); skipped otherwise |

**Consolidated supplement notify [CHANGE]:** extend the once-per-run supplement email (P5c B-4, decision-critical-unverifiable) to ALSO include the open **H3 internal-data** HumanTasks — ONE consolidated email per run listing everything the human must supply, with: what's missing, why it's blocked (NDA / myICP / non-public), and which cells/issues it unblocks. Still **once per run**, still non-blocking (continue unblocked cells). Only **all-paths-blocked** escalates to H5 pause.

**AFK:** H0 default-pause (§2); H7 default-pause on first cycle unless `--assume-brief`/best-effort; H1/H2/H5 always pause; H3/H4/supplement never block.

**Files:** `graph.py` (`node_plan_approval` H7), `notify/email.py` ([CHANGE] consolidate H3 + B-4 into one builder), `decision/risk.py` (unchanged classify_pull).

---

## 6. Component E — riders

### E1 — hard cap (run 8 hours) [CHANGE]
- `CN5_COS_MAX_WALL_S` **default → 28800 (8h)**; `CN5_COS_MAX_COST_USD` default kept (configurable). `run_cap.cap_exceeded` unchanged in shape.
- **Do not stop early while researchable:** `max_iterations` / branch-budget decay must NOT terminate the loop while any high-impact cell is `open` AND under the caps. The ONLY stops are: grid converged, all-blocked (H5), or cap hit. (Removes the premature iteration-ceiling stop for long runs; §10/§11 anti-endless still bounds via the caps.)

**Files:** `decision/run_cap.py` (default), `graph.py::_route_after_decide` ([CHANGE] gate the iteration-ceiling exit behind "no open researchable cell").

### E2 — model tier (PhD researcher + professor auditor) [CHANGE]
- `DEFAULT_MODEL` (researcher / web research) haiku → **`claude-sonnet-4-6`** (env `CN5_COS_LLM_MODEL` still overrides).
- Final `synthesis` (`brains/synthesis.py`) haiku → **`claude-opus-4-8`** (the deliverable).
- **Albert** auditor: Opus tiers unchanged (flash Opus / quick / fast / normal).
- Mechanical micro-steps (slug, dedup, query-split, the clarifier question-gen) may stay **haiku** (cheap, no reasoning depth needed).
- Cost note: validated by E1's hard cap; an 8h Sonnet-researcher run is bounded by `CN5_COS_MAX_COST_USD`.

**Files:** `llm/sdk_client.py` (`DEFAULT_MODEL`), `brains/synthesis.py` (model), `brains/clarifier.py` (haiku).

---

## 7. Deterministic vs LLM

LLM (narrow calls only): clarifier question-gen, orchestrator decompose, self-reflect, per-cell researcher, synthesis; Albert (external). **Everything else deterministic:** the loop/FSM, convergence + coverage tracking, task-grid bookkeeping, H-gate routing, caps, citation verify (verbatim≥0.85 / flatten-to-primary), email consolidation, model-tier selection.

## 8. Unchanged / regression

P1–P6 nodes (intake, scope, brief-write, research fan-out, critic, compress, skeptic, readiness, citation, paperwork/docling, real Albert P6) keep their contracts. The loop is RE-WIRED (head = orchestrator) but each existing node's signature is preserved. P7 (reference store, run-cap, findings-first, real-Albert fix) all stay. All existing tests must stay green; H0/H4/H6 behavioural tests updated for the multi-round H0 + the new H7.

## 9. Global companion (ecosystem) — separate deliverable

The MRC prevention MRC-NC/MRC-ND is an **ecosystem** change and per the global rule lives under `~/.claude/`, NOT in this repo: the **"SOTA-Alignment Governed Object"** — (a) a spec-template requirement for the §1 SOTA Coverage Matrix, (b) an owner-bound deferred-scope register, (c) class-tagged feedback (a user catch triggers a CLASS re-audit, not a local patch), enforced by a gate (candidate **R23**, re-aimed per the MRC Phase-5 audit at detection surfaces, not spec-write-time alone). Tracked separately; referenced here so P8's matrix has a consumer.

## 10. Tests / DoD

- **A (Socratic H0):** a deterministic clarifier stub → the loop refuses to leave clarify until all 4 criteria are set; AFK → pauses; `--assume-brief` → proceeds with assumptions recorded. (mock LLM)
- **B (orchestration loop):** loop head = orchestrator; after a research cycle the grid re-decomposes from injected Albert challenges + gaps (a new cell appears targeting an uncovered vendor×spec); loop-back goes to ① not supervisor. (deterministic, fake brains)
- **C (task grid):** cells map to report rows; coverage states transition; converged only when no open high-impact cell + Albert satisfied.
- **D (H7):** first cycle pauses for plan-approval; a small re-rank does NOT re-prompt; a major re-decomposition DOES. (mock interrupt)
- **D2 (consolidated email):** H3 internal-data tasks + B-4 critical-unverifiable → exactly ONE email per run listing all; all-blocked → H5 pause.
- **E1 (8h cap):** default wall = 28800; loop does not exit on iteration-ceiling while an open researchable cell exists under caps; exits on cap with current findings.
- **E2 (model tier):** researcher resolves to sonnet, synthesis to opus, Albert tiers unchanged, clarifier to haiku (assert the model passed to each call; no real LLM).
- **Regression:** P1–P7 green.
- **End-to-end (live, opt-in):** re-run `topics/switch pk.txt` — Socratic clarify pins the decision-anchor first; the loop adaptively decomposes vendor×spec-group; 8h/cost-capped; ONE consolidated supplement email; findings-first cited partial PK table (filled cells + honest N/A + blocked-cells list). A research report, not a questions dump.

## 11. Pipeline / sequencing + open calibration (decide on spec review)

Pipeline: this spec → `writing-plans` → `subagent-driven-development` (TDD, P1–P7 green) → live switch-PK re-run → ONE findings email. Caps + once-per-run notify prevent blow-up.

**Calibration points to confirm on review (defaults chosen = "do it right"):**
1. **Albert plan-audit cadence** — default: every cycle via flash, **skipped when the plan is unchanged** from last cycle.
2. **Task-grid axes** — default: 2-axis (vendor×spec-group), 3-axis on demand for product-dense vendors.
3. **⑤+②(b) merge** — default: keep separate (results-audit ≠ plan-audit); MAY merge into one Albert call later if cost shows it.
4. **H7 cadence** — default: first cycle always + major re-decomposition only.
5. **H0 convergence** — default: all 4 criteria pinned; no extra "type CONFIRM" step.
6. **AFK** — default: pause at H0/H7 unless `--assume-brief`/best-effort.

---

## ref — verified SOTA sources (2026-06-04)

- ODR — [langchain-ai/open_deep_research](https://github.com/langchain-ai/open_deep_research); [ODR internals walkthrough](https://www.bolshchikov.com/p/open-deep-research-internals-a-step) (supervisor + think_tool + ConductResearch + compress + report-generator).
- ANTH — [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) (orchestrator-worker; lead plans→memory; 3-5 parallel subagents; reflect; CitationAgent; ~15× tokens; +90.2% vs single-agent).
- GPTR — [assafelovic/gpt-researcher (DeepWiki)](https://deepwiki.com/assafelovic/gpt-researcher/1-overview) (planner→parallel executors→curation→publisher; EmbeddingsFilter; 5-dim curator).
- WW — [WebWeaver: dynamic outlines for open-ended deep research](https://arxiv.org/abs/2509.13312) (dynamic outline; hierarchical section-by-section synthesis; per-subtask targeted retrieval).
- WDART — [WebDART: Dynamic Decomposition and Re-planning](https://arxiv.org/pdf/2510.06587).
- Clarification — [Ask-to-Clarify (multi-turn instruction disambiguation)](https://arxiv.org/pdf/2509.15061); note: LLM agents "overhedge or implicitly guess users' intent rather than asking" — the exact switch-PK failure.
- LG-HITL — [LangGraph human-in-the-loop plan-and-execute (approve/edit/reject + interrupt + checkpoint resume)](https://docs.langchain.com/oss/python/langchain/human-in-the-loop).
- 2026 survey — [Deep Research Agent Architectures](https://zylos.ai/research/2026-04-21-deep-research-agent-architectures) (core loop = Plan→Search→Read→Reflect→Iterate→Synthesize + multi-agent parallelism; context-budget + $5-30/session economics).
- OPERA (out, reason) — [arxiv 2508.16438](https://arxiv.org/abs/2508.16438) (RL-enhanced planner-executor; needs RL training, not subscription-SDK feasible).
