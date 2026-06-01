# skill-cn5-research-cos

**CN5 Chief-of-Staff (COS) Research Agent / BU Research Cockpit.**

A continuous, audit-driven, human-steered research cockpit that behaves like a strong chief-of-staff. It repeatedly researches, audits (from "Albert"'s perspective), challenges, updates living artifacts, and decides whether to **continue / branch / re-rank / pull-human / push-human / synthesize** — until the team is ready for leadership-level (Albert) challenge and decision-making.

> The evolving research *state* is the product — not a final report.

## Status

🟢 **P1 complete — deterministic spine + LangGraph loop.** The full research
convergence loop runs end-to-end with **zero LLM, zero cost**: every "brain" is a
deterministic stub behind a stable Protocol/injection seam. The loop iterates →
audits (Albert role) → updates living artifacts → scores readiness → decides, and
**stops for an explicit, correct reason** (terminal_stop / synthesize), never
prematurely and never endlessly. Crashed runs resume from the LangGraph SqliteSaver
checkpoint. P2–P6 fill in real brains at the same seam.

### Quickstart

```bash
pip install -e ".[dev]"
pytest -v                       # 33 passing

cos init  --question "AI 能否做隔夜 BU 研究" --run-id demo
cos run   --question "AI 能否做隔夜 BU 研究，人類為何還要 in-the-loop"
cos show  demo --artifact all
cos validate demo
```

`cos run` streams a Chinese per-iteration summary (本輪新增 / Albert 會挑戰 / 已答 /
pending / 需要人 / 下一輪建議 + 四項 readiness 分數), then prints the stop reason and the
four readiness scores. Runtime state lives in `runs/<run_id>/` (`state.json` snapshot
+ `checkpoint.db` LangGraph checkpoint). Override the base dir with `CN5_COS_BASE_DIR`.

The implementation backbone is decomposed into 6 phases (P1 all-stub deterministic
loop → P6 hardening); each phase is the same loop, runnable and independently
verifiable, just progressively more real.

## Docs (source of truth)

- [`docs/spec/PRODUCT-SPEC.md`](docs/spec/PRODUCT-SPEC.md) — the authoritative product specification (Sections 0–30), verbatim.
- [`docs/superpowers/plans/2026-06-01-master-backbone.md`](docs/superpowers/plans/2026-06-01-master-backbone.md) — functional-spec capture (Part A) + 6-phase execution backbone (Part B) + open decisions / working protocol (Part C). Includes the **Human Steering Layer** (HITL) model.
- [`docs/superpowers/specs/2026-06-01-phase1-deterministic-spine-design.md`](docs/superpowers/specs/2026-06-01-phase1-deterministic-spine-design.md) — early P1 design draft.

## Key architecture facts

- **Package:** `cn5_research_cos` · **CLI:** `cos`.
- **LLM backend (later phases):** Claude Agent SDK, behind a mock + injection hook (P1 runs deterministic mocks; real brains swap in at the same seam).
- **"Albert" reviewer is an EXTERNAL skill** — [`skill-cn5-i-am-albert`](https://github.com/oxydavid-maxx/skill-cn5-i-am-albert) — which this cockpit *consumes* (does not build). The audit node is a client/adapter over that skill's evolving interface.
