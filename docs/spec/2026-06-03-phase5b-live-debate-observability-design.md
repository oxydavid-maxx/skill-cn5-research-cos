# Phase 5b — live debate observability + emission-gate fix (design)

> 2026-06-03. Decided via discussion. Triggered by the P5 live run: the memo synthesis works end-to-end, but (a) the convergence gate refused an explicit-command emission (the predicted "gate deadlock" fragility), and (b) a colleague running `cos run` MUST be able to WATCH the adversarial debate live on screen. User directive 2026-06-03: "我要同事能看到辯論過程在螢幕上。絕對不可以被任何流程譬如 tee, cat, pipe 擋掉 … 每個 stage 印出關鍵資訊 … Albert 的 output 也一定要能夠顯示在螢幕上 … 不要流水帳 … 用盡各種 bypass 方法來紅隊驗證." Builds on P5 (on branch `p5-synthesis`, not merged). DoD: a colleague watching `cos run` sees a concise-but-substantial per-stage summary INCLUDING Albert's full output, GUARANTEED to reach stdout under every invocation form (red-team verified); the gate fix lets an explicit command emit a status memo.

## Component 1 — Live debate observability (the main work)
A **`StageReporter`** that the loop's nodes call to stream a per-stage, human-readable summary to the operator's terminal AS THE LOOP RUNS. Built INTO the loop (not an external wrapper) so it can never be forgotten (per the long-running-progress-heartbeat pattern).

**Per-stage summary — a reasonable-length block (NOT one line, NOT a流水帳 firehose):** ~3–8 lines of KEY info per stage:
- `scope` — the SOT brief objective + north-star (1–2 lines).
- `expand` — N issues + the top issue titles.
- `research` — per researched issue: a 1-line finding + its top source.
- `critique / skeptic` — the challenges/counterarguments raised this round.
- **`Albert audit` — Albert's FULL output shown (the debate core, NOT truncated):** every `AlbertChallenge` (the `challenge` text + `why_albert_would_ask` + `status` + `current_answer` if any), plus `verdict`, `premature_end_risk`, `research_drift_risk`, `recommended_next_action`. This is what the colleague most needs to see.
- `convergence` — resolved N / open M this round + WHICH challenge ids resolved (the debate progressing).
- `readiness` — the 4 scores + `should_continue` + the one-line reason.
- `decision` — the COS next action + its rationale.

**The debate thread must be legible:** Albert challenges X → next round's research targets X → challenge X resolved/still-open. The reporter labels each stage and ties Albert's challenges to the research that answers them.

**Guaranteed visibility (the hard requirement):**
- Writes to **stdout**, **explicitly flushed** every stage (no buffering hold-back). Use a Rich `Console`; in a non-tty (piped/redirected) it must STILL emit (force a terminal-independent write or fall back to plain `print(..., flush=True)`).
- It is the PRODUCT's own output (the `cos` CLI), streamed live — NOT written-to-a-file-then-shown. The colleague running `cos run` sees it in real time.
- Never gated behind `tee`/`cat`/`pipe`/redirect/background: the stream survives all of them.

## Component 2 — Emission-gate fix (Option A: completeness overridable, correctness hard)
The P5 live run refused emission on `explicit=True` because the convergence gate is unconditional. Fix `synthesis/gates.py check_emission`:
- **`explicit=True` bypasses the COMPLETENESS gates** — readiness AND convergence (a §22 memo is a status briefing that DOCUMENTS open challenges in its Albert Challenge Map / Blocking / Required-Human-Decisions sections, so emitting with open challenges on explicit command is honest).
- **`explicit` NEVER bypasses the CORRECTNESS gates** — degraded-audit (the Albert audit must have genuinely run) and citation (no unverified KEY claim / no fabrication). Those make the memo itself untrustworthy.
- Loop behavior (no change, but recorded): open challenges → CONTINUE the loop (more iterations, with live output); human-input needed → STOP at the HITL gate (H1/H3/H5). The memo is emitted on resolution OR explicit command.
- Update `tests/test_memo_live.py` to assert emission succeeds with `explicit=True` (correctness gates still pass since the audit genuinely ran).

## Red-team verification (MANDATORY — user directive; I actually run it)
Prove the per-stage debate summary (incl. Albert's full output) reaches stdout under EVERY invocation form. A `scripts/redteam_visibility.py` (or a test) exercises `cos run` / the loop with a `StageReporter` and asserts the per-stage Albert output appears, under:
1. direct tty, 2. `| cat` (piped), 3. `> file` (redirected), 4. non-tty subprocess (`subprocess` with `stdout=PIPE`), 5. `PYTHONUNBUFFERED` unset, 6. background run. Assert each stage's marker + Albert's challenge text is present and arrives incrementally (not all-at-the-end). If ANY form swallows it, that's a bug to fix, not to document around.

## Modules
- `src/cn5_research_cos/observability/reporter.py` — `StageReporter` (per-stage render + flushed stdout write; non-tty safe). Pure-ish: takes the state + stage name, renders a block, writes it.
- Wire `reporter.stage(...)` calls into the loop nodes in `graph.py` (scope/expand/research/critique/skeptic/albert_audit/convergence/readiness/decision). Gated by a `--stream` flag (default ON for `cos run`/`run-auto`; OFF in tests unless asserted).
- `synthesis/gates.py` — the gate fix.
- `scripts/redteam_visibility.py` — the red-team harness (diagnostic).

## Deterministic-vs-LLM split
All of this is DETERMINISTIC (rendering + stdout). No LLM. The reporter only formats existing state.

## Tests / DoD
- **Deterministic:** `StageReporter` renders each stage block with the right KEY fields (Albert block contains every challenge's text+why+status, NOT truncated); a non-tty `Console` still emits (capture stdout, assert content); the reporter flushes per stage (assert incremental, e.g. via a fake stream recording write order). Gate fix: `explicit=True` emits when correctness gates pass; still refuses on degraded audit / unverified KEY claim even with explicit.
- **Red-team (I run it):** the 6 invocation forms above all show the per-stage Albert output on stdout, incrementally. Paste the evidence.
- **Regression:** P1–P5 (all current tests) STAY GREEN.
- **Live (opt-in):** the fixed `tests/test_memo_live.py` passes (memo emits on explicit; the live stream shows Albert's debate).
- Committed; push on user confirmation.

## Out of scope
- A web/GUI dashboard (terminal stdout only for now).
- Persisting the debate transcript to a file (the live stream is the requirement; file persistence is separate).
