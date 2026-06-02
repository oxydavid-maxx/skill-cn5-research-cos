# Phase 3 — real interrupt() HITL + auto mode (design)

> 2026-06-02. Decided via multi-round discussion (forks 1-2). Builds on P1 (loop + SqliteSaver), P2a (SOT brief / clarify), P2b (real brains). Parent: `docs/spec/phases-P2-P6-spec.md` (P3). DoD = Acceptance **Test 2** (human blocker) + **Test 5** (auto mode) + interrupt/resume round-trip; P1's tests stay green.

## Core decisions
- **HITL = exit-and-resume via real LangGraph `interrupt()`** (NOT blocking stdin). A gate pauses the loop mid-run (state frozen in the SqliteSaver checkpoint), the CLI prints the ask + AI recommendation + default and EXITS; the human runs `cos resume <run_id> --answer/--choice ...` → `Command(resume=...)` continues from the exact checkpoint. Async: the human answers on their own schedule; fits overnight.
- **auto mode safety: low-risk → default-action (don't stop); high-risk → hard-stop (interrupt + wait).** Never burns overnight on a wrong high-impact direction. Backed by the SOT brief (north-star) + per-iteration Albert `research_drift_risk`.

## The gates (Human Steering Layer H0–H6)
| Gate | Mechanism |
|---|---|
| **H1 pull-direction / H2 call-decision / H5 call-help** | a `human_pull` node calls `interrupt(payload)` where payload = `{context, why, options[A/B/C], ai_recommendation, impact_per_option, default_if_no_response}` (§9.1 / §8.4 help-call format). Interactive: pause+exit; auto: apply `default` if low-risk, else interrupt (hard-stop). |
| **H3 push-human** | `human_push` node (NON-blocking): create a `HumanTask` (§9.2 fields), mark the issue `blocked_by_*`, and CONTINUE adjacent non-blocked branches. No interrupt. (**Test 2**.) |
| **H4 ad-hoc steering** | `cos steer <run_id> "..."` appends a `steering_event` to the checkpointed state; the next `cos run --resume` / next iteration's COS re-ranks / branches on it (records the event, recomputes readiness). |
| **H0 preflight** | at interactive run start, populate the §8.1 fields (`likely_albert_concern, output_purpose, known_constraints, forbidden_directions, available_sources, internal_documents_available, default_research_priority, fallback_behavior_if_human_unavailable`) — minimal high-leverage questions only (may reuse the P2a SOT brief where it already answers them). |
| **H6 final-review** | a seam: a `human_review` gate before `synthesis`/final memo. The memo body is P5; in P3 H6 is the interrupt point (confirm/revise) wired but the memo it gates is stubbed. |

## Risk classification (deterministic — drives auto's stop-vs-default)
`decision/risk.py` → `classify_pull(state, decision) -> "low" | "high"`. **high** when: decision_criterion unknown AND all high-`impact` OPEN issues depend on it; OR the Albert audit `premature_end_risk`/`research_drift_risk` is high; OR multiple high-impact intents exist with no safe default. Else **low**. (Pure, unit-tested.) Auto mode: high → `interrupt` (hard-stop); low → apply `default_if_no_response` + record a `steering_event(auto-default)`.

## §8.4 blocker handling (auto)
- **soft** (incomplete source / one claim lacks a 2nd source) → lower confidence, find substitute, continue.
- **medium** (restricted doc / internal data / source conflict) → H3 HumanTask + continue adjacent.
- **hard** (criterion unknown & all paths depend / all evidence needs internal data) → H5 call-help → interrupt (even in auto).

## CLI
- `cos run --question ... [--run-id]` — interactive: runs until a gate `interrupt()`s; prints the ask + exits with the run paused.
- `cos resume <run_id> --answer "..."` (or `--choice A`) — `Command(resume=...)` continues from the checkpoint.
- `cos steer <run_id> "..."` — inject an ad-hoc steering event (H4).
- `cos run-auto --question ... [--max-iterations N] [--default-priority ...]` — overnight: low-risk auto-defaults, high-risk hard-stop; prints per-iteration summary; on a hard-stop, pauses (resumable) and prints why; on completion prints the final state + stop reason (§8.3/§9.4).

## Wiring
- The loop graph gains the gate nodes; `cos_decision` routes to `human_pull`/`human_push`/`human_review` per its decision; the gate node `interrupt()`s (interactive / auto-high) or applies the default (auto-low). The existing SqliteSaver checkpoint enables resume. The deterministic stub brains (`--llm mock`) keep P1's tests green (the gates are exercised deterministically with scripted resume values).

## Tests / DoD
- **Deterministic (no LLM):** a gate `interrupt()`s and `Command(resume=...)` continues from the checkpoint (mock graph); `classify_pull` low/high on hand-built states; **Test 2** — internal-data need → `human_push` creates a HumanTask + the loop continues an adjacent issue (not blocked); auto-mode low-risk applies the default + records a steering event; auto-mode high-risk hard-stops; `cos steer` injects a steering event that re-ranks next iteration; **Test 5** — `run-auto` over the stub loop runs multiple iterations, Albert audit each, readiness updated, final state explains the stop reason.
- **Live (opt-in `CN5_COS_LLM_TESTS=1`):** one `run-auto --llm real --max-iterations 2` reaches a sensible stop (or hard-stop) with the real brains; one interactive `interrupt → cos resume` round-trip.
- Committed + pushed.

## Out of scope
Final memo body (P5, H6 gates it); real research worker adapters / paperwork / docling (P4); the real external Albert skill (P6). Migrating the P2a clarify from turn-based to interrupt() is a later cleanup (P2a stays as-is).
