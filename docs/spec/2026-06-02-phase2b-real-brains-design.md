# Phase 2b — Real LLM Brains + minimal real search + Albert simulator (design)

> 2026-06-02. Decided via multi-round discussion. Builds on P1 (loop, 33 tests) + P2a (SOT front-end + working `llm/sdk_client.py`). Parent: `docs/spec/phases-P2-P6-spec.md`.

## Goal
Swap the P1 loop's deterministic **stub brains** for **real cheap-LLM narrow nodes**, feed them **real (minimal) web search** data, and add a **cheap-LLM Albert simulator** wired to the (vendored) `skill-cn5-i-am-albert` contract. The loop topology + control stay exactly as P1. DoD = Acceptance **Test 3** (Albert generates the expected challenges) + P1's 33 tests still green (via `--llm mock`).

## Global architecture principle (applies to every brain)
Each LLM is a **narrow node with structured output** (`llm/sdk_client.call_structured`, cheap `haiku`); ALL control (loop, convergence, stop, routing, COS decision) stays **deterministic Python/LangGraph** (§14). No monolith prompt self-manages. `build_brains("real")` injects these at the existing hook; `build_brains("mock")` keeps the P1 stubs so the 33 deterministic tests stay green.

## The brains (real in P2b) — each a narrow node + structured schema
| Brain | Input → structured output | Notes |
|---|---|---|
| `issue_expander` | state → `IssueNode[]` | LLM decompose; **no grounding** (real grounding = P4) |
| `researcher` | (state, issue) → `EvidenceBundle` | **minimal real WebSearch** (SDK built-in `allowed_tools=["WebSearch"]`), ONE search per selected issue — no fan-out / no two-altitude ranking (those = P4) |
| `source_critic` | `EvidenceBundle` → annotated bundle | source quality/confidence per claim |
| `skeptic` | (state, bundle) → `counterarguments[]` | |
| `compress` | `EvidenceBundle` → cited summary | light; real compression depth = P4 |
| `scorer` | state → `ReadinessScore` | LLM-assisted readiness |
| `albert` (simulator) | state → `albert_challenge`-shaped dict | cheap LLM following the **vendored** `albert_challenge.schema.json`; mapped via vendored `to_audit_result` → `AuditResult` |
| `researcher` data, COS decision, loop control | — | COS decision + loop stay **deterministic** (P1) |

## sdk_client extension (minimal)
Add an `allow_websearch: bool` path to `llm/sdk_client` → `allowed_tools=["WebSearch"]` + `max_turns>=2` (tool cycle). WebSearch is a **built-in** tool (not MCP), so the P2a `--strict-mcp-config` + `mcp_servers={}` isolation does NOT block it. **Build-time verification:** confirm WebSearch actually runs in our isolated/nested env before relying on it (escape-mrc uses it; should work).

## Albert simulator + vendored contract (fork 1+2)
- **Vendor (copy) from `skill-cn5-i-am-albert`:** `schemas/albert_challenge.schema.json` + the `cockpit_contract.py::to_audit_result` mapping → into `src/cn5_research_cos/albert/` (e.g. `contract.py` + the schema). This freezes the contract in-repo; P2b tests don't depend on the external skill.
- **Simulator:** a cheap-LLM narrow node produces an `albert_challenge`-shaped dict (schema-valid); `to_audit_result(challenge)["audit_result"]` → our `AuditResult` (1:1), `["enrichment"]` → the A2 fields. Identical mapping the real skill uses → **P3/P6 swap to the real skill is seamless** (same contract). Register the seam as an R17 integration contract.

## Testing (F3 — cheap model live, opt-in)
- **Deterministic (default, no LLM):** P1's 33 stay green (`--llm mock`); each real brain has a structured-output contract test driven by a SCRIPTED fake (validates the node's schema wiring without an LLM); `to_audit_result` mapping unit-tested on vendored fixtures.
- **Live (opt-in `CN5_COS_LLM_TESTS=1`, reuse the working sdk_client):** **Test 3** — given a draft answer "human-in-loop needed", the Albert simulator returns challenges including the expected angles (why-not-ask-upfront / which-parts-truly-human / is-HITL-an-excuse / what-can-be-automated). researcher returns real sources from WebSearch. The loop runs `--llm real` end-to-end and converges/stops correctly.

## Out of scope (later phases)
Pluggable worker adapters (GPT-Researcher/ODR/paperwork) + supervisor parallel fan-out + two-altitude source ranking + docling (P4); real `interrupt()`/auto-mode (P3); synthesis/final memo (P5); the REAL external `skill-cn5-i-am-albert` (P6, swap the simulator for it at the same contract).

## DoD
Test 3 passes live; P1's 33 green; `--llm real` loop runs on real WebSearch data + cheap-LLM brains + Albert simulator and stops for a correct reason; structured-output + `to_audit_result` contracts validated; committed + pushed.
