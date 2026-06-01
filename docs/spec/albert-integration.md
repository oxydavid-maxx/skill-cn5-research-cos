# Albert Integration — external skill `skill-cn5-i-am-albert`

> User directive 2026-06-01. The "Albert Thought Agent" (spec §6.3, §20, §29) is NOT built in this repo.

## Boundary

- **Albert is a separate, independently-versioned skill:** `github.com/oxydavid-maxx/skill-cn5-i-am-albert` — a high-standard product/architecture war-room reviewer, grounded in real CN5 Gateway / PM war-room transcripts.
- **Local checkout (sibling dir):** `D:/D-claude/skill-cn5-i-am-albert/` (as of 2026-06-01: only `.git` + `docs/` — early/in-progress, no code yet).
- **Built/owned elsewhere.** Status as of 2026-06-01: **partial / in-progress, interface still changing.**
- **This cockpit only CONSUMES it.** Building/finishing the Albert skill is OUT OF SCOPE for `skill-cn5-research-cos`.

## How this cockpit uses it

- The `albert_thought_audit_node` is a **CLIENT / ADAPTER**, not an in-repo prompt.
- The cockpit defines **its own stable `Auditor` Protocol**; the adapter absorbs the external skill's interface churn.
- Until the external skill stabilizes, the cockpit runs a deterministic **mock Auditor**; the real skill binds later at the **injection hook** (`--llm mock|real` / factory DI) without touching the loop.
- The adapter maps the Albert skill's rubric output → our `AlbertChallenge[]` + readiness deltas.

## Albert's own contract (owned in the external repo, summarized for the adapter)

Albert's behavior is a high-pressure reviewer that does not praise / summarize, but forces **decision quality**. Its 12 "bones":

1. Force every vague term into a precise definition ("no spec" = no high-level / implementation / customer-requirement / winning spec?)
2. Ask "will it win?" of every feature (must-have / nice-to-have / overkill / competitor-parity; why we win; backup if customer won't buy)
3. Decompose product to first principles (application → service → latency/deterministic/safety/availability → compute placement)
4. Chase local-vs-central compute until it can't be dodged (command down vs signal up; actuator/BLDC controller)
5. Use latency / deterministic to bring fantasy back to reality (latency budget numbers, ADC→compute→PWM path, network-latency=0 justification)
6. Reverse-engineer competitor strategy (segment cut; tech/cost/customer/legacy; are we benchmarking last gen; next-gen roadmap)
7. Force a single owner (no 多頭馬車; who decides; what must be answered pre-feasibility; binding risk + fallback)
8. Separate internal central thesis from external framing (discovery/alignment/commitment/negotiation; what to tell vs only listen)
9. Converge war-room NOW (answerable by AI/public/internal know-how now vs truly needs customer; 30-point version now)
10. Ask spec + business + schedule together (cost impact; cut features for lowest price; feasibility ready for commercial offer)
11. Red-team the central thesis (where most likely wrong; market/tech/customer/cost/schedule/ecosystem; who is the contrarian)
12. Chase reproducible judgment, not one-off answers (what reusable judgment / checklist this leaves behind)

**Albert output format:** (1) the 3 most dangerous ambiguities → (2) 10 soul questions → (3) evidence that must be filled → (4) decision gate: what can/can't be decided now + who is responsible → (5) one-line verdict: 可推進 / 要補證據 / 方向錯 / 產品定義不完整.

## Open (resolve at P2/O-4 fine-tune)

- Invocation mechanism: Claude Agent SDK subagent? skill invocation? CLI? — TBD with the external skill's owner.
- Exact request JSON (§20 input) and response JSON (rubric output) — define as the integration contract (R17 seam).
- Adapter mapping: Albert rubric output → `AlbertChallenge[]` fields + readiness_score deltas.
