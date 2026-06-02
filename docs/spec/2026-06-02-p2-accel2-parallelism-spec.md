# P2 Acceleration increment 2 — session-pool parallelism (spec)

> 2026-06-02. Builds on increment 1 (persistent `ClaudeSession` + `SessionPool` + cap-fan-out + cost instrumentation; benchmark 29.5→17 min). Goal: run the per-issue researcher fan-out CONCURRENTLY → target **~17 min → ~5–6 min / 2 iters**, safely under the subscription rate limit.

## Root cause this increment attacks
After increment 1, ~18 calls × ~60s each, run **SERIALLY**. The K researcher WebSearch calls per iteration are independent → run them concurrently.

## Design
1. **Async session path + multi-session pool (`llm/sdk_client.py`).**
   - The persistent session's turn is already async (`_session_turn` → `client.query()` + `client.receive_response()`). Expose an **`async ask_async(user, *, schema, brain)`** on `ClaudeSession`.
   - The `SessionPool` currently returns ONE session per `(model, tools, schema)` key. Add a **bounded multi-session pool**: up to `MAX_CONCURRENT` (env `CN5_COS_MAX_CONCURRENT`, default 3) live sessions PER KEY, acquired/released via an `asyncio.Semaphore`. Concurrent callers each get their own live `claude` session; releases return it for reuse (still amortizing spawn).
   - A sync `call_structured*` still works (acquires one, runs, releases).
2. **Concurrent researcher fan-out (`graph.py`).**
   - The research stage runs the K selected issues' researchers via **`asyncio.gather`** (one event loop, bounded by the `MAX_CONCURRENT` semaphore), not sequentially. Map results back into `state.evidence` deterministically (stable order by issue id). This replaces the serial per-issue loop.
   - The other (cheap, fast) brains can stay sequential for now — WebSearch is the slow part.
3. **Rate-limit safety.**
   - `MAX_CONCURRENT` cap (default 3) bounds parallel `claude` spawns.
   - On a `RateLimitEvent` / 429-style transport error, the existing tenacity retry (exponential backoff) applies; ensure the pool releases the session on failure so a stuck session never deadlocks the semaphore.
   - Never exceed `MAX_CONCURRENT` concurrent sessions per key (assert in tests).

## DoD / verification
- All existing tests stay green (108). New **deterministic** tests (mock the SDK client, NO real LLM): `ask_async` runs a turn; the multi-session pool caps at `MAX_CONCURRENT` (assert never more than N concurrent live sessions via a counting fake); the research stage dispatches the K researchers concurrently (assert they overlap — e.g. a fake that records max-in-flight) and returns results in stable order; a session is released back even when a researcher raises.
- **Re-benchmark** the SAME question / `--max-iterations 2` live: wall-clock **materially lower than 17 min** (target ~5–6 min) AND no rate-limit failure; cost roughly similar (parallelism cuts wall-clock, not token cost). Paste before/after.
- Committed + pushed.

## Out of scope
Parallelizing the cheap non-WebSearch brains (marginal); agentic plan / semantic caching; model cascade (Tier 6).
