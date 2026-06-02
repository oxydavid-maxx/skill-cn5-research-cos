# P2 Acceleration — implementation spec

> 2026-06-02. Design = `docs/spec/2026-06-02-optimization-plan.md` (ULTIMATE P2 acceleration plan). This is the actionable spec for the FIRST acceleration increment. Goal: the `--llm real` loop iteration drops from **~15 min → ≤ a couple minutes**, and a run prints a **cost ($) + latency** number.

## Root cause
SDK `query()` has ~12s startup PER CALL (no hot reuse, [issue #34]). Our `llm/sdk_client` does `query()` per brain → re-spawns `claude` every call → ~3 min spawn overhead/iter before any work.

## Scope of THIS increment (defer session-pool parallelism to a follow-up)
1. **Persistent `ClaudeSession`** (port from `skill-ai-escape-mrc/ai_escape_mrc/sdk_client.py:355`).
2. **Cost + latency instrumentation.**
3. **Cap researcher fan-out + skip answered + bound WebSearch turns.**
4. **Prompt caching** (`cache_control` on static system prompts).
(Session-pool `asyncio.gather` parallelism = next increment, after this is verified — it interacts with the persistent session and needs concurrency/rate-limit care.)

## Design

### 1. Persistent session (`llm/sdk_client.py`)
Add a `ClaudeSession` class mirroring escape-mrc: connect ONE `ClaudeSDKClient` (with our isolation: `mcp_servers={}`, `extra_args={"strict-mcp-config":None}`, `_SDK_ENV`, no-console patch, `setting_sources=None`, `output_format` schema, optional `allowed_tools=["WebSearch"]`), run many turns via `.ask(user, schema=...)` → `client.query()` + `client.receive_response()`; reconnect-on-transport-error; context-manager (`__enter__/__exit__` connect/disconnect). `call_structured`/`call_structured_websearch` stay as the one-shot convenience API (back-compat); brains that issue several calls in a run use a shared session.
- **Wiring:** `run_loop`/`build_brains("real")` open ONE session per run (or one per tool-class: a no-tool session for the LLM brains + a WebSearch session for the researcher) and pass it to the brains. Brains call `session.ask(...)` instead of `call_structured(...)`. Spawn cost paid once, not per call.

### 2. Cost + latency instrumentation
`_collect` already aggregates messages — also capture `ResultMessage.total_cost_usd` + `usage` + per-call wall-clock. Accumulate per-run into a small `RunMetrics` (total $, total calls, per-brain count, wall-clock). `cos run` prints a one-line cost/latency summary at the end. (So the next benchmark is quantitative.)

### 3. Cap fan-out + skip answered (`graph.py` supervisor / researcher)
- Supervisor selects only the **top-K (=3) highest-`impact` OPEN issues** per iteration (env `CN5_COS_MAX_RESEARCH_PER_ITER`), not all.
- **Skip `answered` issues** (never re-research).
- **Dedup** identical search queries within a run (a small seen-set).
- **Bound WebSearch** to `max_turns≈4` per researcher call (already) + cap to ONE search per issue.

### 4. Prompt caching
Mark each brain's large STATIC system prompt with Anthropic `cache_control` (ephemeral) so repeated calls cache-hit. Verify the SDK passes it through (`ClaudeAgentOptions` / system_prompt). Keep system prompts byte-identical across calls so they cache.

## DoD / verification
- All existing tests stay green (84 passed; P1's 33; P2a). New deterministic tests: `ClaudeSession` lifecycle (mock the SDK client — connect/ask/reconnect/disconnect) without a real LLM; `RunMetrics` accumulation; supervisor cap selects ≤K issues + skips answered.
- **Re-benchmark** the SAME question/`--max-iterations 2` live: assert wall-clock **materially lower** (target ≤ ~a few min/iter vs 15) AND a cost/latency line is printed. Paste the before/after numbers.
- Committed + pushed.

## Out of scope (next increments)
Session-pool `asyncio.gather` parallelism (Tier 2 of the ultimate plan); agentic plan caching / semantic search caching / model cascade (Tier 6).
