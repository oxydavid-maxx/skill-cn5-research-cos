# Optimization Plan — so far (P1 + P2a + P2b + skill-cn5-ask)

> 2026-06-02. After P2b merged (`02410b7`). Prioritized, actionable. Benchmark numbers appended after the live `--llm real` run completes.

## State of the build
- **P1** deterministic loop (33 tests). **P2a** SOT clarify front-end (live-verified: real 6-turn dialogue → SOTBrief). **P2b** real cheap-LLM brains + minimal WebSearch + Albert simulator (84 passed; live Test 3 verified; real WebSearch returns real sources). **`skill-cn5-ask`** reusable converge engine (26 tests, local-only). The `--llm real` loop works end-to-end via Claude subscription (no API key).

## P0 — correctness / robustness (fix soon)
1. **`skill-cn5-ask` saver leaks the sqlite connection.** `make_saver` opens `SqliteSaver(sqlite3.connect(...))` and never closes it → on Windows a `TemporaryDirectory` teardown raises `NotADirectoryError`, and the P2a live clarifier test goes flaky. **Fix:** make the saver a context manager / expose `close()`, and have `ClarifySession` close it; or use an in-process connection that's released. Owner: `skill-cn5-ask`.
2. **Push `skill-cn5-ask`.** It has no GitHub remote (local 7 commits). Create the empty repo → push, so P2a/P2b's dependency is reproducible (currently only `pip install -e` locally).
3. **Live path has no CI coverage.** Live tests are opt-in (`CN5_COS_LLM_TESTS=1`). Add a cheap nightly smoke (one Albert call + one WebSearch) so the subscription/SDK path doesn't silently rot. Keep default `pytest` fast/free.

## P1 — quality / UX
4. **SOT convergence is slow + signals flap.** The live demo took 6 turns; per-turn signal booleans fluctuated (0→2→3→2→4) because each turn re-judges from scratch and keeps finding gaps. **Fix options (pick 1–2):** (a) feed the LLM the PRIOR turn's signal state so it doesn't re-open settled signals (stabilize); (b) add a user-facing "夠清楚了，收斂" override so the human can stop it; (c) relax the rule (≥3 active for 1 round once all 4 have been seen). Keep the anti-premature spirit but make convergence reachable in ~3–4 turns.
5. **Reference-materials prompt at intake (user side-ask 2026-06-02).** At the START — based on the topic — the SOT front-end / preflight should explicitly ask the user to drop their **available internal docs/data into `reference/`** (datasheets, prior analyses, internal numbers) and record them in the SOT brief's `available_sources`. Grounds the research in what the user already has, not just web. Wires into the `paperwork` internal-document adapter + the `reference/pdf` + `reference/fragments` convention (C3). → land in P2a/P3 (the clarify/preflight) + P4 (the doc adapter).
6. **Albert simulator depth.** The cheap-haiku simulator produces good-shaped challenges but is shallower than the real `skill-cn5-i-am-albert` (its 12 bones + multi-vote). That's by design (P3/P6 swaps in the real skill at the frozen contract). Track the swap.

## P2 — cost / performance
7. **Per-iteration LLM-call fan-out is expensive.** Each iteration calls issue-expander + (researcher WebSearch ×N issues) + source-critic + skeptic + compress + scorer + Albert — many separate cheap-LLM calls, and WebSearch per issue dominates latency/cost. **Optimizations:** (a) **prompt caching** (the SDK supports it — cache the big system prompts across calls); (b) cap researcher fan-out / dedup queries; (c) batch the cheap critique brains where possible; (d) skip re-researching `answered` issues. (Quantify after benchmark.)
8. **Default model + token budget.** All brains use `haiku`. Confirm that's the right cost/quality point per brain (Albert may warrant a step up only in P6 real-skill).

## P3 — architecture / coverage (already phased, tracked)
9. **Grounded decomposition** (issue-expander on real data) → P4. **Two-altitude source ranking + citation discipline (verbatim ≥0.85) + paperwork adapter + docling** → P4. **interrupt()/auto-mode HITL** → P3. **Real external Albert skill** → P6. **Synthesis/final memo** → P5.

## P4 — ecosystem (not this repo, surfaced)
10. **R7 / R20 gate misfires** hit this session (R7 looped on legitimate commits; R20 didn't count 10+ websearches). The personal-wiki already documents fixes ("Watched-Command Position Matching", "Tool-Input Field Shape", "Research-Gate Durable Log"). For the ecosystem owner to land.

## Benchmark (live `--llm real` end-to-end) — DONE 2026-06-02

First full live `--llm real` run. Question: "評估我們 BU 是否應該自建一個 AI 研究助手：市場現況、競品、可行性", `--max-iterations 2`, model `haiku`.

| Metric | Value |
|---|---|
| Wall-clock | **~29.5 min for 2 iterations (~15 min/iter)** — SLOW |
| Issues built | 9 (grew via Albert branch) |
| Evidence bundles / real sources / claims | 12 / **92 real web sources** / 101 claims |
| Albert challenges | 15 (genuinely sharp — e.g. "Build-vs-Buy-vs-Partner framing missing", "did the analysis drift from 'should we build?' to 'here's the market'?", "diagnostic not a recommendation") |
| Human blockers identified | ~9 challenges flagged `needs_*`/`blocked` |
| Readiness | Albert 3 / Decision 2 / Exhaustion 2 / Human 4 (should_continue=True) |
| Stop | hit max-iter cap; decision=branch (correctly wanted to continue) |
| End-to-end bugs | none (loop ran clean; real brains + WebSearch + Albert simulator + deterministic control all worked) |

**Verdict:** quality is good (real sources, sharp Albert critiques, human-blocker classification, readiness scoring all real). **The dominant problem is SPEED/COST:** ~15 min/iteration, driven by **WebSearch fan-out** — `RealResearcher` does one WebSearch per issue, and issues grow to 9, so ~9 searches/iter + the per-brain LLM calls. **92 sources / 101 claims in 2 iterations is over-collection.** This sharpens P2-#7:

- **Cap researcher fan-out** (e.g. only research the top-K highest-impact OPEN issues per iteration, not all 9).
- **Skip already-`answered` issues** (don't re-search).
- **Prompt caching** on the big per-brain system prompts (SDK supports it) — biggest cheap win across the many calls.
- **Parallelize the fan-out** (the brains are independent per issue) — wall-clock, not cost.
- **Instrument cost** — the CLI prints no `$`/token usage; add per-run cost/latency accounting so future benchmarks are quantitative.
- **Lower `max_turns`/cap WebSearch depth** per researcher call.

Target: an iteration should be ≤ a couple minutes, not 15.
