# Phase 5 — synthesis + final memo (design)

> 2026-06-03. Decided via discussion (+ grounded check of paperwork: research-synthesis is skill-only and produces a 5-section topic-report, NOT our §22 decision-memo → memo synthesis is cockpit-specific; citation validation = our P4b modules only, no paperwork quality-gate). Builds on P4a (internal-doc evidence, already cited), P4b (convergence `gate_emission` live; citation modules built but not wired), P3 (H6 gate). Parent: `docs/spec/phases-P2-P6-spec.md` (P5). DoD: the cockpit produces a gated §22 decision-memo; after P5, run the **TC4 partial-reset baseline** (`docs/poc/tc4-partial-reset-reference.md`).

## Grounded corrections (honesty ledger)
- paperwork `research-synthesis` is **skill-only** (no script entry) and emits a **5-section topic-report**, a DIFFERENT shape from our §22 decision-memo. So P5 synthesis is **cockpit-specific** — we do NOT drive paperwork's synthesis skill (consistent with the P4a scripts-as-toolbox decision; avoids the nested-agent path). My earlier "P5 reuses paperwork research-synthesis" was an over-claim; corrected here.
- **What we actually reuse:** doc-grounded evidence is ALREADY cited from P4a (`collect_section_evidence` verbatim quotes + `[[ref-id,§N]]`) → flows straight into the memo, no re-synthesis. Citation validation = **our P4b modules only** (user decision 2026-06-03) — no paperwork quality-gate backstop.

## Components

### 1. Web source-text capture (PREREQUISITE — unblocks P4b web citation verify)
The web researcher schema currently captures no source full-text, so `citation/verify.py`'s web verbatim-≥0.85 difflib check has nothing to verify against. **Fix:** extend `RealResearcher`'s structured output so each web `Source`/`Claim` carries a **relevant excerpt** (the quoted span + a small surrounding window), NOT the full page (token-efficient). Internal-doc claims already carry their fragment quote from P4a. Deterministic test: a web claim's excerpt is populated and is what `verify` checks.

### 2. Synthesis brain — the §22 decision-memo (cockpit-specific, LLM)
`brains/synthesis.py::RealSynthesizer` (behind a `Synthesizer` Protocol + `--llm` hook, mock stub stays for tests). Produces the §22 memo, **9 sections**:
1. Executive Answer · 2. Albert Challenge Map (from `albert_challenge_map`, status-annotated) · 3. What We Can / Cannot Say · 4. What Is Blocking Us · 5. Required Human Decisions / Inputs · 6. Evidence Summary (doc-grounded cited from P4a + web cited from P4b) · 7. Risks & Assumptions · 8. Recommended Next Action · 9. Appendix.
- **Blocker type labeling (deterministic):** every blocker in §4 labeled one of `research / internal-data / permission / human-judgment / BU-preference / Albert-decision`.
- **Language:** Chinese meeting-ready wording (§21); technical terms untranslated.
- LLM writes the prose; the section SET + gates + blocker labels are deterministic Python.

### 3. Wire in the P4b citation modules (close the P4b caveat)
At memo assembly: `citation/verify` (web claims, now have excerpts) → `citation/policy` tiered escalation (unverified→reverify→human-by-criticality→flag) → `flatten_to_primary` (memo claims cite primary `Source`, never a digest). This is where the P4b-built-but-unwired modules finally run in the live path.

### 4. Three emission gates + H6 (all enforced BEFORE the memo emits)
- **Degraded-audit gate (decision #8):** the Albert audit must have genuinely run (not degraded/mock) — already a rule; assert here.
- **Convergence gate:** `convergence.gate_emission` (already live from P4b) — no unresolved HIGH-impact Albert challenges.
- **Citation gate:** no unverified KEY (decision-critical) claim in the memo (from `citation/policy`).
- **Readiness gate:** memo emits ONLY when the readiness target is met OR the user gives an explicit command.
- **H6 final-review** (P3 `interrupt()`): human confirm/revise before "Done".
All gates deterministic; each independently testable (refuses when its condition is unmet).

## Modules
- `brains/synthesis.py` (RealSynthesizer + Synthesizer Protocol; mock stub), extend `brains/real.py` RealResearcher (excerpt capture) + its schema, `synthesis/memo.py` (deterministic memo assembly: section set, blocker labeling, citation wiring, gate checks), wire into `graph.py` terminal/synthesize node + the H6 gate.

## Deterministic-vs-LLM split (§14)
- **Deterministic:** the 4 gates, blocker labeling, memo section set/structure, citation verify/policy/flatten wiring, excerpt→verify plumbing, readiness check.
- **LLM (narrow):** the synthesis brain (prose per section), structured output; the researcher excerpt extraction. Control stays in Python.

## Tests / DoD
- **Deterministic (mock brains):** memo has all 9 §22 sections; blocker types labeled (each of the 6 kinds routed correctly on hand-built states); each gate REFUSES independently — degraded audit → no memo; unresolved high-impact challenge → no memo (convergence gate); unverified key claim → no memo (citation gate); below readiness + no explicit command → no memo; H6 interrupt present before Done. Web excerpt capture populates the field `verify` reads; a web claim with a non-matching excerpt is caught by the now-wired citation path; a digest-citing memo claim is flattened.
- **Regression:** P1–P4b (all current tests) STAY GREEN.
- **Live (opt-in `CN5_COS_LLM_TESTS=1`):** a short real run reaches readiness (or explicit command) and emits a §22 memo with cited evidence + an Albert Challenge Map; skip cleanly without the opt-in.
- **Baseline:** after P5 merges, run the **TC4 partial-reset baseline** end-to-end (web + internal-doc TC4 UM via P4a + Albert convergence + memo) and log the run against `docs/poc/tc4-partial-reset-reference.md` (what it reached/challenged/missed).
- Committed; push on user confirmation.

## Out of scope
- paperwork research-synthesis skill / quality-gate (decided: cockpit-specific memo + our own citation validation).
- Real external Albert skill (P6); richer Albert / packaging / hardening (P6).
- Enterprise UI, Slack/Teams, multi-BU memory (§23 not-yet).
