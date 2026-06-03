# Phase 6 — Real Albert Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** swap the Albert simulator for the real external `skill-cn5-i-am-albert` via its CLI + `to_audit_result` contract, behind the existing `Auditor`/`build_auditor` seam, feeding the P4b convergence engine; deterministic (mocked-subprocess) build now, live TC4-baseline validation later.

**Architecture:** subprocess `run_albert.py --input <json> --json-out [--quick|--fast|--flash]` → `albert/cockpit_contract.py::to_audit_result` → `AuditResult` → `challenge_map.upsert`. Deterministic speed cascade by stage+risk. `ALBERT_HOME` resolution (never vendored), degrade-visibly if absent. Spec: `docs/spec/2026-06-03-phase6-real-albert-design.md`. Reference: `D:/D-claude/skill-cn5-i-am-albert/` (`run_albert.py`, `albert/cockpit_contract.py`, `albert/profile.py`). Branch: `p6-real-albert`. Do NOT push.

**Invariant:** P1–P5d (391) stay green — `PYTHONPATH=src py -3 -m pytest -q` after each task. Mock the subprocess in ALL deterministic tests (NO real Albert / no network). Live tests opt-in `CN5_COS_LLM_TESTS=1`+`ALBERT_HOME`.

---

### Task 1: `albert/locate.py` — ALBERT_HOME resolution (mirror paperwork/locate)

**Files:** Create `src/cn5_research_cos/albert/locate.py`; Test `tests/test_albert_locate.py`

- [ ] **Step 1: failing test** — `find_albert_home()`: `$ALBERT_HOME` → sibling `skill-cn5-i-am-albert` checkout discovery (walk up from cwd) → None; validity = `run_albert.py` present; `albert_version(home)` from `README`/a version file if present else "unknown". Absent → None.
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** mirroring `brains/paperwork/locate.py` (read it). Deterministic, tmp-dir + env-monkeypatch tests.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p6): albert home resolution (ALBERT_HOME, never vendored)`

---

### Task 2: `decision/audit_tier.py` — deterministic speed cascade

**Files:** Create `src/cn5_research_cos/decision/audit_tier.py`; Test `tests/test_audit_tier_speed.py`

- [ ] **Step 1: failing test** — `audit_tier_for(stage, state) -> "flash"|"quick"|"fast"|"normal"`: per-iteration sentinel→`flash`; readiness-approaching OR last-audit drift/premature-risk high→`quick`; pre-synthesize→`fast`; final/high-stakes/H6→`normal`. Pure, hand-built states.
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** pure function (no LLM, no datetime). Map speed→Albert CLI flag: flash→`--flash`, quick→`--quick`, fast→`--fast`, normal→(no flag/default).
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p6): deterministic audit-speed cascade (flash/quick/fast/normal)`

---

### Task 3: `albert/real_adapter.py` — input build + subprocess + contract parse + merge

**Files:** Create `src/cn5_research_cos/albert/real_adapter.py`; Test `tests/test_albert_real_adapter.py`

- [ ] **Step 1: failing test** (mock the subprocess + the contract):
  - `build_albert_input(state) -> dict` includes the current answer/proposal + SOT brief + the **prior OPEN challenges** (from `albert_challenge_map`) so Albert tracks/resolves.
  - `RealAlbert.audit(state)` writes the input json, invokes `run_albert.py --input … --json-out <speed>` (mock `subprocess.run` returning a canned contract JSON), parses via the contract (or a vendored copy of the contract mapping if `ALBERT_HOME` not importable — read `albert/cockpit_contract.py` to decide: prefer subprocess + JSON, not importing Albert's package) → `AuditResult`; merges via `challenge_map.upsert` (resolved/escalated/new).
  - Speed selected via `audit_tier_for`.
  - A non-zero subprocess exit / unparseable JSON → degraded `AuditResult` that CANNOT drive terminal_stop (assert the degrade guard).
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — `build_albert_input`, `RealAlbert` (Auditor Protocol), subprocess invoke (list args, utf-8, timeout sized for the speed: flash short / normal up to ~25min), parse the JSON-out (the `to_audit_result`-shaped contract) → `AuditResult`. Read `albert/cockpit_contract.py` to match the exact JSON contract shape. NO importing Albert's python package (subprocess + JSON only, scripts-as-toolbox).
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p6): real Albert adapter (subprocess + contract -> AuditResult -> convergence)`

---

### Task 4: wire `--albert real|sim` + degrade guard + flash availability

**Files:** Modify `brains/__init__.py`/`stubs.py` (`build_auditor`/`build_brains` gains `albert="sim"|"real"`), `cli.py` (`--albert`), `graph.py` (use `audit_tier_for`); Test `tests/test_albert_hotswap.py`

- [ ] **Step 1: failing test** — `--albert sim` (default) = the existing simulator; `--albert real` = `RealAlbert` (mock subprocess). Hot-swap leaves the loop green. ALBERT_HOME absent + `--albert real` → degrade-visibly (warning + degraded audit, loop continues, terminal_stop not driven by degraded audit). **flash availability:** check `run_albert.py --help` for `--flash`; if absent, the per-iteration sentinel falls back to the existing simulator and logs it (do NOT fail).
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** the seam + CLI flag + degrade path + flash-availability check (a one-time capability probe of the Albert CLI).
- [ ] **Step 4: run → PASS;** **full suite green (P1–P5d = 391).**
- [ ] **Step 5: commit** `feat(p6): --albert real|sim hot-swap + degrade guard + flash-availability probe`

---

### Task 5: live opt-in test (controller/later runs it)

**Files:** `tests/test_albert_live.py`

- [ ] **Step 1:** opt-in (`CN5_COS_LLM_TESTS=1` + discoverable `ALBERT_HOME`): one real `--quick` audit returns a valid contract → `AuditResult` with real challenges; a challenge resolves or escalates across two rounds (convergence consumes real Albert). Skips cleanly otherwise; collects without error. Do NOT run it (controller does — real Albert is 5+ min).
- [ ] **Step 2: commit** `test(p6): opt-in live real-Albert audit + convergence consume`

---

## Self-Review
- **Spec coverage:** ✅ locate (T1), speed cascade (T2), adapter+contract+merge+degrade (T3), hot-swap+flash-probe (T4), live (T5). Acceptance = TC4 baseline (controller, later).
- **Placeholder scan:** none.
- **Type consistency:** `RealAlbert.audit(state) -> AuditResult` matches the `Auditor` Protocol; `audit_tier_for(stage, state)` (T2) used by the adapter (T3) + graph (T4); `build_albert_input(state) -> dict` (T3) stable.
- **Scripts-as-toolbox:** subprocess + JSON contract only; NO importing Albert's package; NEVER vendor; ALBERT_HOME resolution.
