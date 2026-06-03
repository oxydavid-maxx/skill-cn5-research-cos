# Phase 6 — real Albert integration (design)

> 2026-06-03. Boundary confirmed with user: **P6 = swap the simulator for the real external Albert skill + validate on the TC4 baseline; P7 = hardening / packaging / v2-email.** Builds on P2b (Albert simulator + `to_audit_result` contract seam), P3 (audit-tiering `build_auditor` seam), P4b (convergence engine — what real Albert must drive), P5/P5b/P5c (memo + live debate stream + citation honesty). Grounded against the now-built `D:/D-claude/skill-cn5-i-am-albert` (the user revised it; 3 speeds live). DoD: the loop runs end-to-end on the REAL Albert and the TC4 standing baseline produces a §22 memo whose Albert Challenge Map is from real Albert.

## Grounded — how the real Albert is invoked (verified 2026-06-03)
- **CLI subprocess + JSON contract (scripts-as-toolbox / contract pattern, same family as paperwork + the P2b simulator seam):** `py -3 <ALBERT_HOME>/run_albert.py --input <albert_input.json> --json-out [--quick|--fast] [--resume <id>] [--user-email <addr>]` → parse the JSON out via `albert/cockpit_contract.py::to_audit_result` → our `AuditResult`. NOT a nested SDK agent.
- **Speeds (live): `--quick` (5min) · `--fast` (10min) · default `thorough` = normal (20min).** `flash` (LLM-only, ~secs) is PROPOSED, not yet in Albert → deferred (see Cascade).
- Albert also exposes `--resume <id>` (its own checkpoint) and `--user-email` (it can email the human itself).

## Components
1. **Real Albert adapter** (`albert/real_adapter.py`, behind the existing `Auditor` Protocol / `build_auditor` seam): build `albert_input.json` from `ResearchState` (the current answer/proposal + the SOT brief + **the prior OPEN challenges** from `albert_challenge_map` so Albert tracks/resolves rather than re-asks — feeds the P4b convergence engine), subprocess-invoke `run_albert.py` with the stage-selected speed, parse via `to_audit_result` → `AuditResult`, merge back through `challenge_map.upsert` (resolved/escalated/new). Replaces `RealAlbertSimulator` at the `--albert real` hook (simulator kept for `--albert sim` / fast deterministic tests).
2. **Dependency resolution** (`albert/locate.py`, mirror `paperwork/locate.py`): resolve `ALBERT_HOME` (env → sibling `skill-cn5-i-am-albert` checkout discovery → absent). NEVER vendored; never user-local-hardcoded. Preflight verifies `run_albert.py` present + captures Albert version. Absent → the audit **degrades VISIBLY** and a degraded audit may NOT drive `terminal_stop` / count as a passed audit (decision #8, already enforced — assert with real Albert).
3. **4-speed cascade** (deterministic `audit_tier_for(stage, state) -> speed`, §14, wired through `build_auditor`):
   - per-iteration sentinel → **cheap sentinel** (the existing haiku simulator) for now; swap to Albert `--flash` once it exists (P7/later). Real Albert is 5–20min → MUST NOT run per-iteration.
   - escalation (readiness approaching / last sentinel flagged drift/premature-risk high) → **`--quick` (5min)**.
   - pre-synthesize (before the §22 memo gate) → **`--fast` (10min)**.
   - final / high-stakes / explicit deep / H6 → **normal (20min)**.
4. **Convergence integration:** Albert's output (challenges + status + the §20 signals: premature_end_risk / research_drift_risk / recommended_next_action) flows into `challenge_map.upsert` + `decision/convergence`; prior open challenges flow INTO `albert_input.json`. This is the closed loop the P4b engine was built for — now driven by the real reviewer.
5. **Live debate stream (P5b):** the StageReporter's `albert_audit` block now renders the REAL Albert output (it already renders the `AuditResult` shape — confirm no change needed). Albert's own per-run progress (it has a heartbeat) should not double-print; surface a concise per-call line.

## Cost / latency (measured-aligned)
Real Albert at a gate = 5–20min, run RARELY (gates only). Per-iteration stays cheap (sentinel). Loop body ~$1/iter unchanged. The soft budget warning (P5) now also reflects Albert-gate time. A `run-auto` overnight with real Albert at gates could be hours — the soft budget line lets the operator interrupt; no hard cap (P5c decision).

## Deterministic-vs-LLM
Deterministic: speed selection, input assembly, contract parse, convergence merge, degrade guard. LLM/agent: the real Albert subprocess (its own FSM). Control stays in our Python.

## Tests / DoD
- **Deterministic (mock the subprocess):** `audit_tier_for` picks the right speed per stage/risk; `real_adapter` builds a valid `albert_input.json` (incl. prior open challenges) and maps a canned `to_audit_result` JSON → `AuditResult` → `challenge_map.upsert`; `locate` discovery + absent→degrade (degraded audit cannot drive terminal_stop); `--albert real|sim` hot-swap leaves P1–P5c green.
- **Live (opt-in `CN5_COS_LLM_TESTS=1` + `ALBERT_HOME`):** one real `--quick` Albert audit returns a valid contract → AuditResult with real challenges; the convergence loop consumes it (a challenge resolves or escalates across rounds).
- **Acceptance — the TC4 standing baseline** (`docs/poc/tc4-partial-reset-reference.md`): run end-to-end (web + internal-doc TC4 refs via P4a + real Albert at gates + §22 memo), log what it reached/challenged/missed vs the frozen findings.
- Committed; push on user confirmation.

## Out of scope (→ P7)
flash mode wiring; v2 email-reply supplement; PostgresSaver; packaging; broad hardening/monitoring.
