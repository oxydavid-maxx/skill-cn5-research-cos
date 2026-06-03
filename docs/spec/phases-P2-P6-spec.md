# Phase Specs P2–P6 (R2-confirmed) — locked spec-level definitions

> 2026-06-01. Confirms each later phase's spec-level scope AFTER the R2 revision (GPT Researcher + Open Deep Research + paperwork study; see `gap-audit-2026-06-01.md` + backbone REVISION R2). Purpose: anti-goldfish — lock what each phase delivers so its future detailed spec only elaborates, never re-derives. Each phase still gets a per-phase fine-tune + detailed spec + plan before it is built.
>
> **Invariant across all phases:** every phase is the SAME loop (canonical = `flow-diagram.md` Revised engineering flow), runnable + independently verifiable, just more real. Every new capability binds at the injection hook / a stable interface defined in P1, so later phases are fill-in not rewrite. P1 (deterministic, zero-LLM) ships the full node SHAPE as stubs; P2–P4 replace stubs with real implementations.

---

## P2 REPARTITION + fork decisions (2026-06-01, multi-round discussion)

P2 is **split into two independent phases P2a + P2b** (P3–P6 numbering UNCHANGED). Fork decisions:
- **F1 Albert source:** P2b uses a **self-written cheap-LLM Albert simulator** that emits an `albert_challenge`-shaped dict and wires ONLY to the external skill's frozen **`to_audit_result` contract** (`skill-cn5-i-am-albert/albert/cockpit_contract.py`, schema `schemas/albert_challenge.schema.json`). The real external skill (now fully built, 73 tests, contract designed against our `AuditResult`) is flipped in at **P6**, not P2.
- **F2 Transport:** **Claude Agent SDK** (`query()` + `output_format=json_schema`), reusing the proven `sdk_client` pattern from escape-mrc / the Albert skill. Runtime = standalone process (no nested-session #573).
- **F3 Testing:** **cheap model, run real LLM live** (no cassette/mock machinery). Assertions on structure/contract/schema/behavior, not verbatim text. LLM tests are **API-key-gated** (skip without a key). P1's pure-logic tests stay deterministic.
- **F5 Model/cost:** cheapest model (Haiku-tier) for all P2 brains; `ALBERT_FAST_MODEL`-style cheap routing.
- **F6 SOT:** **reuse `skill-deep-research` Socratic engine** (`agents/socratic_mentor_agent.md` + `references/socratic_questioning_framework.md` — multi-round, 1–2 Q/turn, 4 convergence signals, anti-stagnation caps, INSIGHT→brief compiler) + a thin custom SOT-lifecycle wrapper (persist/version/revise/conflict-surface — the part no existing tool gives). ODR clarify is one-shot → borrow only its brief-writer prompt. NOT `superpowers:brainstorming` (that is a dev-process skill, one-shot).

### P2a — SOT Clarification Front-end (next to build; own detailed spec)
**Goal:** when a topic arrives, run a GENUINE multi-round clarifying dialogue (unlimited rounds until clear) → produce + persist the **SOT `research_brief`** that constrains all downstream work; revisable; conflicts surfaced for human discussion. Runnable in P2a via CLI back-and-forth (real interrupt/auto = P3). Detailed spec: `docs/superpowers/specs/2026-06-01-phase2a-sot-clarification-design.md`.

### P2b — Real LLM brains + Albert simulator (after P2a; own detailed spec)
**Goal:** swap the P1 stub brains in the loop for real cheap-LLM ones (issue-expander w/ grounded decomposition, researcher, source-critic, skeptic, compress, scorer, COS reasoning) behind the same Protocols + `--llm real` hook; Albert simulator → `to_audit_result` contract; typed null-exit critique. DoD: Acceptance Test 3; the loop runs on real cheap LLM and still converges/stops correctly.

---

## (original) P2 — Real Albert (external skill) + real LLM brains  [superseded by P2a+P2b above; kept for reference]

**Goal:** swap P1's deterministic stub brains for real ones via Claude Agent SDK, behind the SAME `brains/` Protocols + injection hook (`--llm real`). The loop, state, persistence, decision logic, guardrails are UNCHANGED from P1.

**What becomes real (was stub in P1):**
- `Auditor` → CLIENT/ADAPTER to external `skill-cn5-i-am-albert` (O-4 integration contract). Adapter maps the skill's rubric output (3 ambiguities → 10 soul questions → missing-evidence → decision-gate → verdict) into `AuditResult` (`AlbertChallenge[]` + `premature_end_risk`/`research_drift_risk`/`recommended_next_action` + `readiness_score_delta`). Until the external skill stabilizes, a real-LLM Albert simulator (prompt-defined, §20 contract) stands in behind the same adapter.
- `IssueExpander` → grounded decomposition (B3): a cheap retrieval/seed pass BEFORE LLM decomposition (GPTR pattern). In P2 grounding may be a light web search; full retrieval = P4.
- `Researcher` / `SourceCritic` / `Skeptic` → Claude Agent SDK structured-output brains.
- `compress` node → real cite-preserving compression (ODR `compress_research`): raw worker output → cited summary; replace-semantics so artifact store / readiness context don't bloat.
- Critique stage → typed null-exit (B8): `source_critic`→`skeptic`→`albert_audit` yields **clean | challenges[]**; only clean advances; Albert `premature_end_risk=high` overrides a clean skeptic.

**Evidence citation schema enforcement seeds here (C2):** `Claim.source_refs` resolvable; `Source` role; `EvidenceBundle.coverage_gaps`. Full verbatim-≥0.85 + flatten-to-primary enforcement is P4.

**Cross-cutting:** Claude Agent SDK transport (retry/backoff; reconnect on dead session); structured-output contract validation with single-shot retry-with-named-critique on schema violation (escape-mrc borrow); **degraded-audit guard active** — a degraded/errored/mock audit may NOT drive terminal_stop or count as passed (emission gate, decision #8).

**DoD / verify:** **Acceptance Test 3** (Albert generates the expected challenge set); P1 loop + all P1 tests still green with `--llm real` swapped only at the hook; Albert integration contract (O-4) has a passing closed-loop entry; structured-output contract validated. Fixtures + recorded outputs for deterministic CI.

**Out of scope:** real parallel worker execution (P4); interactive human waiting / auto mode (P3); final memo (P5).

---

## P3 — Human steering (H0–H6 via interrupt) + auto mode

**Goal:** make the human-steering layer real and add overnight auto mode. The loop gains genuine pause/resume.

**What becomes real:**
- **Real LangGraph `interrupt()` HITL (B6)** bound to the H0–H6 gates: H0 preflight, H1 pull-direction, H2 call-external-decision, H3 push-human-task, H5 call-help → pause via `interrupt()`, surface artifacts + options + default-if-no-response (§13 style), resume via `Command`. H4 ad-hoc steering records a `steering_event` and re-ranks/branches mid-run. H6 final-review gates the memo (P5 seam).
- **Preflight populates the §8.1 fields** (the model fields added in P1) — minimal high-leverage questions only (§8.1 chief-of-staff style), not a questionnaire.
- **Auto mode** `cos run-auto --max-iterations`: runs multiple research/audit/update cycles without constant input; §8.2 allowed / §8.3 forbidden enforced; §8.4 blocker handling (soft→lower-confidence-continue; medium→human-task+continue-adjacent; hard→call-help+pause); default-action-if-no-response after a timeout/turn.
- **Interactive clarify** (ODR clarify pattern) at scope: `need_clarification?` → ask → resume.

> **SOT / iterative scope clarification (user directive 2026-06-01) — FIRST-CLASS requirement, do NOT model as a one-shot questionnaire.** When a topic first arrives, the `scope → write_brief` front-end (B1) must run a GENUINE back-and-forth clarification dialogue — **high-quality and precise, not lengthy; unlimited rounds, repeating until the problem and direction are genuinely clear** (no fixed question count, never "just ask 2 rounds and move on"). Its output is the **Source-of-Truth (SOT) brief**, written into state (`research_brief`) as the north-star that constrains ALL downstream research + Albert-audit so they cannot drift.
> - **`superpowers:brainstorming` is NOT the model here** — that is our *dev-process* skill (one-way, one-shot); the cockpit's *runtime* clarification is a multi-turn interrupt()-driven loop that keeps probing until clear.
> - **Revisable by HITL:** any of the 7 human-steering gates (H0–H6) may come back and amend the SOT brief later.
> - **Conflict handling:** if a later finding / steering event CONFLICTS with the established SOT, the system must **explicitly surface the conflict and run a human back-and-forth** to resolve it (do not silently overwrite the SOT, do not silently ignore the conflict). Resolution is by discussion-until-clear, not by a round cap.
> - Acceptance (P3): given an under-specified topic, scope runs >1 clarification round and only proceeds once the brief is confirmed; a later conflict with the brief triggers an explicit human-resolution interrupt, not a silent overwrite.

**DoD / verify:** **Acceptance Test 2** (internal-data need → HumanTask + continue adjacent + mark confidence) and **Acceptance Test 5** (auto mode: multiple iterations, Albert audit each, readiness updated, final state explains stop reason); interrupt/resume round-trips on the existing checkpoint (resume continues, not restarts); §10 auto-mode extra guardrails enforced (>1 cycle, ≥1 adversarial, ≥1 branch/rerank, final scoring).

**Out of scope:** real research engines (P4); memo (P5).

---

## P4 — Real research workers + source ranking + internal-document adapter

> **STATUS 2026-06-03:** SPLIT into **P4a (internal-document via paperwork scripts-as-toolbox)** and **P4b (convergence + source ranking + citation discipline)** — both BUILT + merged (P4a) / on branch (P4b), all tests green. Detailed specs: `docs/spec/2026-06-02-phase4a-internal-document-design.md`, `docs/spec/2026-06-03-phase4b-convergence-ranking-citation-design.md`. **One open caveat carried to P5:** P4b's citation modules (`citation/verify|policy`, `flatten_to_primary`) are built + unit-tested but **NOT yet wired into the live loop** (need web source-text capture + P5 memo assembly — see the P5 forward-deps block). Convergence `gate_emission` + two-altitude ranking ARE live. paperwork is a gerrit `CN5_PAPERWORK_HOME` dependency (scripts only, never vendored; v7.0.1+ `docling-strict` → fragments use `--backend docling`).

**Goal:** the research node gets real data via pluggable, hot-swappable adapters, and source/citation discipline becomes enforced.

**What becomes real:**
- **Supervisor parallel fan-out (B2)** flips from P1's Send-shape-but-sequential to genuine `asyncio` parallel isolated workers, concurrency cap `MAX_CONCURRENT` (3–8). Per-worker inner cap (B5).
- **Worker adapters (§16), stable interface, hot-swap:** `stub` (kept) | `gpt_researcher` | `odr` | **`paperwork` internal-document/datasheet survey (C1)** | internal-RAG. Each returns an `EvidenceBundle`. The paperwork adapter consumes its `spec.md` + `reference-map.yaml` (sources ← registry; claims ← §4 cited findings); confidence/contradiction derived in our Source Critic (paperwork has none).
- **Two-altitude source ranking (B7):** cheap per-branch filter (embedding/heuristic) always + optional LLM curator (relevance/credibility/reliability) on survivors.
- **Citation discipline ENFORCED (C2):** resolvable citation per claim; **verbatim quote ≥0.85 fuzzy** (anti-fabrication); source role declared; coverage-gaps recorded; **flatten-to-primary-source** (never cite a sibling worker's digest).
- **Document handling (C3):** `reference/pdf/` + `reference/fragments/` (docling-converted, only target sections per the large-PDF rule) + `reference-map` registry; **structural provenance YAML is citation source-of-truth, not embeddings.** PDF→MD only when a program needs machine-verified citations/tables (per C3 decision table); never ingest whole large PDFs (outline→page-range→convert-target-only).

**DoD / verify:** loop runs on real web + internal-document research; adapter hot-swap leaves the loop/tests unchanged; a comparison-table output has every cell cited + verbatim-checked; coverage-gaps surfaced; large-PDF handled by selective extraction (no whole-file ingest).

**Out of scope:** final memo (P5).

---

## P5 — Synthesis + final memo

**Goal:** the terminal/synthesis node produces the deliverable, gated.

**What becomes real:**
- `Synthesis` brain (§6.6): updates artifacts, executive language, Chinese meeting-ready wording.
- **Final memo (§22)** sections (Executive Answer / Albert Challenge Map / What We Can/Cannot Say / What Is Blocking Us / Required Human Decisions-Inputs / Evidence Summary / Risks & Assumptions / Recommended Next Action / Appendix); memo must label each blocker type (research / internal-data / permission / human-judgment / BU-preference / Albert-decision).
- **Emission gate enforced (decision #8):** memo produced ONLY when readiness target met (or explicit user command), AND the Albert audit genuinely ran (not degraded). **H6 final-review** human gate before "Done".

**⚠️ P5 CARRIES FORWARD DEPENDENCIES from P4a/P4b (recorded so they are not forgotten):**
- **REUSE paperwork `research-synthesis` for document-grounded sections** (Evidence Summary / §4 findings): it already emits a 5-section cited topic-report (every claim `[[ref-id,§N]]`) + `quality-gate` citation checks. Do NOT re-write a cited-synthesis for doc claims. P5 WRAPS it with web findings + Albert Challenge Map + blockers + Required-Human-Decisions + decision-memo format (§22) — the parts paperwork lacks. (Mirrors P4a scripts-as-toolbox division of labor.)
- **WIRE IN the P4b citation modules** (`citation/verify.py`, `citation/policy.py`, `flatten_to_primary`): they are BUILT + unit-tested in P4b but **NOT yet called in the live loop** (deferred here by design). P5 memo assembly is where they plug in (`policy.gate_emission` + `flatten_to_primary` on memo claims; web-claim verbatim verify).
- **P5 PREREQUISITE:** the web researcher schema must CAPTURE source full-text (it currently does not) so `citation/verify.py`'s web verbatim-≥0.85 difflib check has text to verify against. (Internal-doc claims are already paperwork-verified — no difflib.)
- **Already live (no action):** `convergence.gate_emission` (refuses memo while high-impact challenges unresolved) wired from P4b; two-altitude ranking runs before compress from P4b.

**DoD / verify:** memo only at readiness or explicit command; §22 sections all present; blocker types labeled; emission gate refuses a memo on a degraded audit (tested) AND while high-impact Albert challenges unresolved (convergence gate) AND while a KEY claim is unverified (citation gate); doc-grounded sections via paperwork `research-synthesis` (not re-invented); H6 review gate present. **First run of the standing TC4 baseline** (`docs/poc/tc4-partial-reset-reference.md`) happens after P5.

**Out of scope (still):** enterprise UI, Slack/Teams, multi-BU memory (§23 not-yet list).

---

## P6 — Albert epic deepening + hardening

**Goal:** polish + deepen.

**Scope:** richer Albert (challenge patterns / personalization HOOKS per §29 — NOT personalized training in MVP); guardrail hardening; packaging decision (O-3: does this become an installed Claude Code skill?); examples/docs; performance (LangGraph PostgresSaver if SqliteSaver write-throughput bottlenecks under concurrency — per 2026 production guidance); reference-monitoring.

**⚠️ P6 CARRIES FORWARD DEPENDENCIES from P3/P4 (recorded so they are not forgotten):**
- **Swap the Albert SIMULATOR for the real external skill** `skill-cn5-i-am-albert` behind the frozen `to_audit_result` contract — and it must feed the P4b **convergence engine** (prior open challenges in, resolved/escalated out, dedup/merge). The real Albert is what the convergence loop was built to converge against.
- **Audit tiering full model-cascade** (deferred from P3 by evidence): only escalate Sonnet→Opus→real-Albert if the cheap sentinel demonstrably MISSES what real Albert catches; `build_auditor(tier, model)` seam already exists.
- **paperwork version-contract hardening:** pin/verify the gerrit `CN5_PAPERWORK_HOME` dependency (v7.x `docling-strict`); preflight version check + the visible degrade-to-web-only path (P4a) are the seam.

**DoD / verify:** richer Albert audit demonstrably catches more; real Albert drives the convergence loop end-to-end; e2e hardened; ship-ready; packaging resolved.

---

## What CHANGED vs pre-R2 (summary for confirmation)

- **P2:** + grounded decomposition, real compression, typed null-exit critique, evidence-citation schema, Albert via external-skill adapter (was "in-repo Albert prompt").
- **P3:** + real `interrupt()` HITL (was "emit message"), interactive clarify, §8.1 preflight population.
- **P4:** + supervisor parallel fan-out, two-altitude source ranking, **paperwork internal-doc adapter**, docling document handling, enforced citation discipline + structural provenance (was just "stub→one real adapter").
- **P5:** + emission gate + H6 final-review gate (unchanged otherwise).
- **P6:** + PostgresSaver-under-concurrency note (otherwise unchanged).
