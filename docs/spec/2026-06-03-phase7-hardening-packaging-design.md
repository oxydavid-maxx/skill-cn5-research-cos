# Phase 7 — hardening + production-readiness + packaging (design)

> 2026-06-03. Boundary confirmed with user: P7 = everything after the real-Albert swap — async-supplement v2, the flash sentinel, hardening, performance, packaging, docs/monitoring. Builds on P6 (real Albert live). DoD: ship-ready — the cockpit survives real overnight runs, a colleague can use it end-to-end (incl. async document supplement by email reply), and the packaging question is resolved.

## Components

### 1. Async-supplement v2 — email reply + attachment auto-ingest (deferred from P5c)
Close the round-trip the user wanted (so coming back is not terminal-only):
- Reuse the proven Outlook-COM READ path (`daily_brief/sources/outlook_mail.py::get_unread_emails` pattern — mirror, don't cross-import): poll for unread replies whose subject/body carries a known `run_id`.
- Extract the reply: text body → a `cos steer`-equivalent injection; **attachments (PDF/PPT/Word/Excel/HTML) → save into `runs/<run_id>/reference/`** (the SAME ingest point as the v1 terminal path — Component already built in P5c).
- Then auto-resume the checkpointed run (`Command(resume=...)` / next iteration). The human REPLIES on email; the cockpit does the two steps (file→reference, trigger) automatically.
- Polling cadence + idempotency (don't re-ingest the same reply); fail-soft if Outlook unavailable (fall back to the v1 terminal instructions already in the notification email).

### 2. flash sentinel (LLM-only per-iteration Albert)
When the user adds `--flash` (LLM-only, ~secs) to the Albert skill: swap the per-iteration cheap sentinel from the haiku simulator → Albert `--flash` (Albert's real rubric, one LLM call). One-line change at the `audit_tier_for` per-iteration tier. Until then, the haiku sentinel stands (P6).

### 3. Hardening
- `--resume` robustness across ALL phases (LangGraph checkpoint resume after a mid-stage crash — the global "resume don't rerun" discipline); test crash-then-resume at each seam.
- Error recovery: a brain/subprocess (paperwork/Albert) failure degrades VISIBLY + records a gap, never silently corrupts state (extend the P4a/P5c degrade discipline).
- Guardrail hardening: §10 anti-premature + §11 anti-endless caps stress-tested on real long runs.
- The SqliteSaver "Deserializing unregistered type" warnings → register the models in `allowed_msgpack_modules` (clean the noise).

### 4. Performance / scale
- LangGraph **PostgresSaver** if SqliteSaver write-throughput bottlenecks under concurrency (per 2026 production guidance) — measure first (the cost/latency instrumentation from P5), swap only on evidence.
- Cross-run caching (deferred from P5c by evidence): cache WebSearch results / docling fragments for baseline RE-runs IF a measured cost pain appears (the TC4 baseline re-runs are the case). Guard freshness (silent-staleness).

### 5. Packaging + docs + monitoring (O-3)
- Decide: does the cockpit become an installed Claude Code skill (`skill-cn5-research-cos` SKILL.md + plugin), or stay a standalone CLI? Resolve O-3.
- Examples (worked runs), expand the USER MANUAL (P5c) with troubleshooting + the email-reply v2 flow.
- Reference-monitoring: re-audit when a cited source / internal doc changes (the §23 not-yet item, if in scope).

## Deterministic-vs-LLM
All deterministic except the (existing) brains + Albert. The email-read/ingest, caching, resume, packaging are plumbing.

## Tests / DoD
- **v2 email:** deterministic — a fake unread reply with an attachment → saved to `runs/<id>/reference/` + a resume triggered (mock the mail-read + win32com); idempotent; fail-soft. Live (opt-in) — a real reply round-trip if feasible.
- **Hardening:** crash-then-`--resume` at each seam restores state (not rerun-from-0); a brain/subprocess failure degrades visibly + records a gap (no silent corruption).
- **Perf:** a measured before/after if PostgresSaver/caching is adopted (evidence-gated; do NOT adopt speculatively).
- **Packaging:** the O-3 decision recorded; if skill-packaged, it installs + runs.
- **Regression:** P1–P6 stay green.
- Committed; push on user confirmation.

## Sequencing note
P7 items are independently shippable — do them by user priority (the user has emphasized: colleagues must be able to use it + see the debate + supplement async). Likely order: (1) v2 email round-trip + flash sentinel (UX completeness the user asked for) → (2) hardening + resume → (3) perf (evidence-gated) → (4) packaging.
