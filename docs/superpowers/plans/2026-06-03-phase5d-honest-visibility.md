# Phase 5d — Honest Debate Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** make the live debate visibility HONEST and robust — durable file (real 100%) + best-effort live stderr + detect-and-refuse non-tty — mirroring the red-teamed `skill-cn5-i-am-albert` pattern; drop all "100%/un-blockable" overclaim.

**Architecture:** extend `StageReporter` to a multi-sink writer (durable `runs/<id>/debate.md` fail-closed + flushed UTF-8 stderr + optional fail-silent tty); add a startup `refuse_if_hidden` guard (non-tty → exit 2 unless `--allow-redirect`); add `cos watch`. Spec: `docs/spec/2026-06-03-phase5d-honest-visibility-design.md`. Reference to MIRROR: `D:/D-claude/skill-cn5-i-am-albert/albert/deliberation.py` + `run_albert.py::_redirect_refusal`. Branch: `p5d-visibility-honest`. Do NOT push.

**Invariant:** P1–P5c stay green — `PYTHONPATH=src py -3 -m pytest -q` after each task.

---

### Task 1: Durable file sink (fail-closed) — the real 100%

**Files:** Modify `src/cn5_research_cos/observability/reporter.py`; Test `tests/test_reporter_durable.py`

- [ ] **Step 1: failing test** — a `StageReporter(run_dir=tmp)` writes every `stage()` block to `tmp/debate.md`, flushed; a write failure (unwritable dir) raises `VisibilityContractError` (fail-closed). Under stdout=devnull the file still has the content.
```python
def test_blocks_persisted_to_debate_md(tmp_path):
    r = StageReporter(run_dir=tmp_path, stream=io.StringIO())
    r.stage("albert_audit", "C-1 ...")
    assert "C-1" in (tmp_path/"debate.md").read_text(encoding="utf-8")
def test_fail_closed_on_unwritable(...): # raises VisibilityContractError
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — add `run_dir` to `StageReporter`; on `stage()` append `\n{block}\n` to `<run_dir>/debate.md` (utf-8), flush; wrap in try/except → raise `VisibilityContractError`. Mirror `albert/deliberation.py`. Keep the existing stream sink.
- [ ] **Step 4: run → PASS;** full suite green.
- [ ] **Step 5: commit** `feat(p5d): durable debate.md sink (fail-closed) — the real 100%`

---

### Task 2: Best-effort live stderr (flush + forced UTF-8) + fail-silent tty bonus

**Files:** Modify `observability/reporter.py`; Test `tests/test_reporter_live.py`

- [ ] **Step 1: failing test** — blocks go to a flushed stderr-like stream with UTF-8 (CJK round-trips, no mojibake); the optional tty write is fail-SILENT (a raising tty handle does NOT break the run, file+stderr still written).
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — default live sink = `sys.stderr` with `reconfigure(encoding="utf-8")` best-effort + flush per block; optional `_try_tty()` (`CONOUT$`/`/dev/tty`) wrapped fail-silent (open best-effort, write, ignore all errors). NEVER raise from the tty bonus.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p5d): live stderr (flush+utf8) + fail-silent tty bonus`

---

### Task 3: refuse-if-hidden guard (non-tty → exit 2 unless --allow-redirect)

**Files:** Create `observability/guard.py`; Modify `cli.py` (`run`/`run-auto` start); Test `tests/test_visibility_guard.py`

- [ ] **Step 1: failing test** — `refuse_if_hidden(streams, allow_redirect=False, embedded=False)` returns a refusal (exit-2 sentinel/raises typer.Exit) when NO stream is an interactive tty; returns None when a tty is present OR `allow_redirect` OR `embedded` OR `CN5_COS_ALLOW_REDIRECT=1`. Mirror `run_albert.py::_redirect_refusal`.
```python
def test_refuses_when_no_tty(...): assert refuse_if_hidden([_fake(notty)], allow_redirect=False) is not None
def test_allows_with_redirect_flag(...): assert refuse_if_hidden([_fake(notty)], allow_redirect=True) is None
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — `guard.refuse_if_hidden(...)`: `_isatty` per stream; if not embedded/allow_redirect/env and not any isatty → return a refusal message (exit 2). Wire into `cli.py` `run`/`run-auto`: add `--allow-redirect` (+ `CN5_COS_ALLOW_REDIRECT`), call the guard at start, print the refusal + exit 2 if hidden. Print the `runs/<id>/debate.md` path + `cos watch` hint on start.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p5d): refuse-if-hidden guard + --allow-redirect (mirror Albert)`

---

### Task 4: `cos watch <run_id>` + wire run_dir into the loop reporters

**Files:** Modify `cli.py` (`watch` command + pass `run_dir` to the StageReporter in `run`/`run-auto`), `graph.py` if needed; Test `tests/test_cos_watch.py`

- [ ] **Step 1: failing test** — `cos watch <run_id>` reads `runs/<run_id>/debate.md` and prints it (and would follow); the `run`/`run-auto` StageReporter is constructed with `run_dir=runs/<run_id>` so the debate persists.
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — `cos watch <run_id>`: resolve `runs/<run_id>/debate.md`, print existing content + `tail -f`-style follow (a simple poll loop; bounded/Ctrl-C). Pass `run_dir` when building the StageReporter in `run`/`run-auto`.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p5d): cos watch + run_dir-scoped debate.md`

---

### Task 5: HONEST red-team test (reports what breaks) + no-overclaim grep

**Files:** Create `tests/test_visibility_redteam.py` + `scripts/redteam_visibility.py` (extend); Test asserts honesty

- [ ] **Step 1: failing test** —
  - durable: spawn the mock-loop entrypoint via subprocess under `> file`, `| cat`, `2>&1`, stdout=devnull, background, and a non-tty PIPE → assert `runs/<id>/debate.md` is COMPLETE (incl. an Albert block) in EVERY case.
  - refuse: a non-tty subprocess without `--allow-redirect` exits 2 with guidance; with `--allow-redirect` it runs + file complete.
  - **no-overclaim structural grep:** assert NO source/docs/test under `src/`, `docs/spec/2026-06-03-phase5*`, `README.md` contains "100%" / "invincible" / "nothing can block" / "un-blockable" / "完全避免...擋掉" in a visibility-claim context (allow the honest-limits doc that NEGATES them).
  - **honesty ledger:** the red-team script prints DEFENDED (file always; accidental-hide refused) vs NOT-DEFENDED (no-screen; hostile-pty; chosen-redirect).
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** the red-team harness + the honesty assertions.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `test(p5d): honest red-team (durable always / refuse / no-overclaim grep)`

---

## Self-Review
- **Spec coverage:** ✅ durable file (T1), live stderr+tty bonus (T2), refuse guard (T3), cos watch (T4), honest red-team + no-overclaim (T5).
- **Placeholder scan:** none.
- **Type consistency:** `StageReporter(run_dir=, stream=)` (T1/T2) used by `cli` wiring (T4); `refuse_if_hidden(streams, allow_redirect, embedded)` (T3) signature stable.
- **No-overclaim:** the wording fix is enforced by the T5 grep test, not just prose.
