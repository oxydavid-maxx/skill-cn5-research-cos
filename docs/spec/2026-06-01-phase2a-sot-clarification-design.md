# Phase 2a — SOT Clarification Front-end (as-built design)

> 2026-06-01. Built on branch `p2a-sot`. Full decision trail: the approved plan (`~/.claude/plans/zippy-gliding-mochi.md`) + `docs/spec/phases-P2-P6-spec.md` (P2a). Lives in `docs/spec/` (not `docs/superpowers/specs/`) to sit beside the other design docs.

## Goal
When a research topic arrives, run a **genuine multi-round clarifying dialogue** (unlimited rounds until clear, never one-shot) → compile a persisted **SOT brief** (north-star that constrains all downstream research+audit). Revisable; conflicts surfaced for human discussion, never silently overwritten.

## Architecture (as built) — deterministic control, narrow LLM
The "iterate-until-converged" loop is NOT built here — it is the **standalone reusable skill `skill-cn5-ask`** (`cn5_ask`: a deterministic LangGraph engine `step → assess(signals) → converged?(rule) → repeat|stop`, SqliteSaver checkpoint, pluggable `StepFn`/`ConvergenceRule`/`CompileFn`/`ConvergeConfig`). **P2a is its first consumer** — it supplies only the narrow plug-ins:
- `sot_step_fn` — ONE narrow LLM call (`sot/prompts/ask_turn.md` via `llm/sdk_client.py`, cheap model): given the dialogue, ask 1–2 clarifying questions + assess signals C1–C4 → `StepResult{output:{questions}, signals:{C1..C4}}`.
- `ConvergenceRule(signals=[C1,C2,C3,C4], threshold_k=3, stability_window=2)` — C1 Objective clarity / C2 Scope stability / C3 Constraint awareness / C4 Decision framing.
- `sot_compile_fn` — one narrow LLM call (`brief_writer.md`, ODR-adapted) → `SOTBrief`.
- Turn-based driving: each `cos clarify` invocation clamps the engine's per-call `max_turns` to `prior+1` so exactly ONE step runs, persists to `runs/<id>/clarify_checkpoint.db`, emits questions, exits; the human's next `--answer` resumes the same thread. Hard cap 12.

**Reuse:** `ask_turn.md` copies the questioning CONTENT (persona, depth probes, `[Q:CLARIFY|PROBE|STRUCTURE|CHALLENGE]` taxonomy, "what does NOT count as progress") from `skill-deep-research`'s Socratic assets, retargeted from paper→cockpit (objective/scope/constraints/deliverable). ALL control (loop/convergence/stop/cap/checkpoint/routing) is deterministic in `cn5_ask` — no monolith prompt self-manages.

## Modules (`src/cn5_research_cos/`)
- `llm/sdk_client.py` — Claude Agent SDK structured-JSON wrapper (cheap model; retry/backoff; raises `LLMUnavailableError` if no key — does NOT fake).
- `sot/brief.py` — `SOTBrief` model + persist/version/load/supersede (`runs/<id>/brief.v<N>.md` + json sidecar).
- `sot/conflict.py` — PURE deterministic `detect(brief, change) -> Conflict|None`; never silent overwrite.
- `sot/clarifier.py` — the glue (`sot_step_fn`, `sot_compile_fn`, `ConvergenceRule`, turn-based `ClarifySession` over `cn5_ask`).
- `sot/prompts/{ask_turn.md, brief_writer.md}`.
- `cli.py` += `cos clarify --question [--answer] --run-id`, `cos brief <id>`, `cos revise-brief <id> --field`.
- Integration: confirmed `SOTBrief` mirrors into `ResearchState.research_brief`; loop's `--llm mock` path unchanged (P1's 33 tests stay green).

## Status / verification
- **Deterministic core: VERIFIED.** `pytest` = 62 passed + 2 skipped (key-gated live); P1's 33 still green. A scripted-fake StepFn drives the full loop → converge at turn 3 → SOTBrief `brief.v1` written → `research_brief` mirrored; `revise-brief` surfaces a high-severity conflict + writes `brief.v2` superseding v1; `cos run --llm mock` preserves the brief.
- **Live LLM dialogue: NOT verified in this env** — no `ANTHROPIC_API_KEY` / `CLAUDE_CODE_OAUTH_TOKEN`, so the real multi-round clarification (the user-facing value) could not be run here. The wiring is proven deterministically; the live path is unit-tested via the structured-JSON contract but UNEXERCISED against a real model. To verify: set `ANTHROPIC_API_KEY` and run `cos clarify --question "<underspecified topic>"`.

## Out of scope (later)
Real LangGraph `interrupt()` pause/resume + auto mode (P3); other real brains + Albert simulator (P2b); real research workers (P4); synthesis/memo (P5); real external Albert skill (P6).
