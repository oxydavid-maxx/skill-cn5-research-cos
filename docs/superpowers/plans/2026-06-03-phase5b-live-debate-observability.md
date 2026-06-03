# Phase 5b — Live Debate Observability + Gate Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** a colleague running `cos run` watches the adversarial debate live on screen (reasonable-length per-stage summaries INCLUDING Albert's full output), guaranteed visible under any invocation; and an explicit command emits a status memo.

**Architecture:** a deterministic built-in `StageReporter` writes a per-stage block to flushed stdout (non-tty safe); the loop nodes call it. The emission gate is fixed so `explicit` overrides completeness gates but not correctness gates. Red-team verified.

**Tech Stack:** Python 3.11, Rich, pytest, `py -3`. Spec: `docs/spec/2026-06-03-phase5b-live-debate-observability-design.md`. Branch: `p5-synthesis` (extends P5; do NOT push).

**Invariant:** P1–P5 (305 tests) STAY GREEN after every task — `py -3 -m pytest -q`.

---

### Task 1: StageReporter — render + flushed, non-tty-safe stdout

**Files:** Create `src/cn5_research_cos/observability/__init__.py`, `src/cn5_research_cos/observability/reporter.py`; Test `tests/test_stage_reporter.py`

- [ ] **Step 1: failing test** — a `StageReporter(stream)` writes a per-stage block; in a non-tty (a `io.StringIO`) the content STILL appears; it flushes per stage.
```python
import io
from cn5_research_cos.observability.reporter import StageReporter
def test_reporter_emits_to_non_tty_and_flushes():
    buf = io.StringIO()
    r = StageReporter(stream=buf)
    r.stage("expand", "5 issues: A; B; C")
    out = buf.getvalue()
    assert "expand" in out and "5 issues" in out
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** `StageReporter`: holds a stream (default `sys.stdout`), a Rich `Console(file=stream, force_terminal=False, soft_wrap=True)` OR plain writes; `stage(name, body)` writes a labeled block (`=== [name] ===\n{body}\n`) and calls `stream.flush()`. Must work when `stream` is a plain file/StringIO (no tty). No LLM.
- [ ] **Step 4: run → PASS;** `py -3 -m pytest -q` green.
- [ ] **Step 5: commit** `feat(p5b): StageReporter (flushed, non-tty-safe)`

---

### Task 2: Stage renderers — reasonable-length KEY info per stage, Albert FULL

**Files:** Modify `src/cn5_research_cos/observability/reporter.py` (add render helpers); Test `tests/test_stage_renderers.py`

- [ ] **Step 1: failing test** — `render_albert(audit)` contains EVERY challenge's text + why + status (not truncated) + verdict + the two risks; `render_readiness(score)` shows the 4 scores + reason; `render_convergence(state)` shows resolved/open counts.
```python
def test_render_albert_shows_every_challenge_full(...):
    txt = render_albert(audit)  # audit has 3 challenges
    for ch in audit.challenges:
        assert ch.challenge in txt and ch.why_albert_would_ask in txt and ch.status.value in txt
    assert audit.verdict ... in txt  # verdict + premature_end_risk + research_drift_risk present
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** render helpers (pure, ~3–8 lines each): `render_scope`, `render_expand`, `render_research`, `render_critique`, `render_albert` (FULL — loop all challenges, no slicing/truncation), `render_convergence`, `render_readiness`, `render_decision`. Reasonable length, KEY fields only (NOT a raw dump of the whole state).
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p5b): per-stage renderers (Albert shown in full)`

---

### Task 3: Wire reporter into the loop nodes (--stream flag)

**Files:** Modify `src/cn5_research_cos/graph.py` (call `reporter.stage(...)` in each node), `src/cn5_research_cos/cli.py` (`--stream` default ON for `run`/`run-auto`), `src/cn5_research_cos/state.py` (thread an optional reporter); Test `tests/test_reporter_wiring.py`

- [ ] **Step 1: failing test** — run the mock loop with a `StageReporter(StringIO)` threaded; assert the captured output contains the albert/readiness/decision stage markers in order (the debate is visible in a mock run).
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — thread an optional `reporter` into `GraphState`; each node, after computing, calls `reporter.stage(name, render_X(...))` if a reporter is present (None in normal tests → no output, so existing tests stay green). CLI builds a real `StageReporter(sys.stdout)` when `--stream` (default True). Mirror the existing metrics threading.
- [ ] **Step 4: run → PASS;** `py -3 -m pytest -q` green (the 305 must not break — reporter defaults to None in their states).
- [ ] **Step 5: commit** `feat(p5b): wire StageReporter into loop nodes + --stream`

---

### Task 4: Emission-gate fix (explicit overrides completeness, not correctness)

**Files:** Modify `src/cn5_research_cos/synthesis/gates.py`; Test `tests/test_emission_gates.py` (extend)

- [ ] **Step 1: failing test** — with an unresolved high-impact challenge AND a genuine (non-degraded) audit AND no unverified KEY claim: `check_emission(state, memo, explicit=True).emitted is True` (completeness overridden). With a degraded audit: still refused even with explicit. With an unverified KEY claim: still refused even with explicit.
- [ ] **Step 2: run → FAIL** (current code refuses on convergence regardless of explicit).
- [ ] **Step 3: implement** — in `check_emission`: gates 1 (degraded-audit) and 3 (citation) ALWAYS apply. Gates 2 (convergence) and 4 (readiness) are SKIPPED when `explicit=True`. Order preserved; refusal reason names the gate.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `fix(p5b): explicit emit overrides completeness gates, keeps correctness gates`

---

### Task 5: Red-team visibility harness (I/controller run it; MANDATORY)

**Files:** Create `scripts/redteam_visibility.py`; Test `tests/test_redteam_visibility.py` (the subprocess-pipe + non-tty cases, deterministic with mock loop)

- [ ] **Step 1: failing test** — spawn the mock loop in a `subprocess` with `stdout=PIPE` (non-tty), reading lines AS THEY ARRIVE; assert the Albert stage block + an Albert challenge text appear, and arrive BEFORE the process exits (incremental, not all-at-end).
```python
def test_albert_visible_through_subprocess_pipe(tmp_path):
    # run a tiny mock-loop entrypoint via subprocess.Popen, stdout=PIPE, bufsize=1
    # assert a line containing "[albert" + a challenge substring is read before .wait()
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** `scripts/redteam_visibility.py` — a tiny entrypoint that runs the MOCK loop with a `StageReporter(sys.stdout)` (deterministic, no LLM) so the red-team can exercise it cheaply; the test drives it via `subprocess.Popen(..., stdout=PIPE, bufsize=1)` and asserts incremental Albert output. Document (in the script header) the 6 invocation forms to run manually: tty / `| cat` / `> file` / non-tty Popen / `PYTHONUNBUFFERED` unset / background.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `test(p5b): red-team visibility (Albert output survives pipe/non-tty, incremental)`

---

### Task 6: Update the live memo test (now emits on explicit)

**Files:** Modify `tests/test_memo_live.py`

- [ ] **Step 1:** with the Task-4 gate fix, `check_emission(..., explicit=True)` now emits (correctness gates pass since the real audit ran). The existing assertion `memo.emitted is True` should now hold. Add an assertion that the run's `StageReporter` output (capture via a StringIO threaded into `run_auto`) contains Albert's challenges (the debate was visible).
- [ ] **Step 2:** controller runs it live after the build (opt-in). Implementer ensures it collects + skips cleanly.
- [ ] **Step 3: commit** `test(p5b): live memo emits on explicit + debate visible`

---

## Self-Review
- **Spec coverage:** ✅ reporter (T1), reasonable-length renderers + Albert full (T2), wiring + --stream (T3), gate fix (T4), red-team (T5), live test (T6).
- **Placeholder scan:** none — concrete tests + render-field lists.
- **Type consistency:** `StageReporter.stage(name, body)` (T1) used by renderers (T2) and wiring (T3); `check_emission(state, memo, explicit=)` (T4) matches the existing signature.
