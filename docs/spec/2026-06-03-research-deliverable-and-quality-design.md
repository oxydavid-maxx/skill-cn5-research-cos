# Spec — research-findings deliverable + quality engine (reference store, hard cap, real-Albert fix)

> 2026-06-03. User correction: `skill-cn5-research-cos` is a RESEARCH COS — it DOES the research and DELIVERS the findings (a cited report / the artifact the question asks for, like GPT Researcher / Open Deep Research). Albert is the AUDITOR (quality/direction, during the loop). HITL fires only for genuine gaps. The §22 decision-memo over-led with questions; the deliverable must lead with FINDINGS. Quality = the loop (iteration + audit + reference + steering); the deliverable must faithfully present it, and the loop must actually run well.

## A. Findings-first deliverable
- `brains/synthesis.py::RealSynthesizer.write_sections`: primary output = the findings/report ANSWERING the question, synthesized from `state.evidence` — cited `[S-…]`, in the form the question asks (table / comparison / analysis), **N/A where no evidence, NEVER guess**. The decision/audit content (Albert challenge map / blocking / required-human-decisions / readiness) becomes a TRAILING "audit & readiness" section.
- `synthesis/memo.py::assemble_memo`: the assembled deliverable LEADS with the findings; the decision/Albert sections become the supporting tail. Keep the emission gates (degraded-audit / citation) + once-per-run HITL-notify.
- Reuse the GPTR/ODR report-synthesis pattern (gap-audit Bucket B). The four pillars each show: iteration→accumulated findings; audit→residual Albert challenges (tail); reference→`[S-…]` citations; steering→required-human-decisions (tail).

## B. Unified per-TOPIC reference material store
Today: per-RUN `runs/<run_id>/reference/`, only human attachments land there; AI web sources live only in transient `state.evidence`; human text answers go to steering_events. Change:
- **Per-topic reference folder** keyed by a topic slug (persistent across runs → re-runs ACCUMULATE; the run's `base_dir` becomes the topic store).
- **AI saves its collected sources** there (fetched source title/url + the key excerpt as a small `.md`/note) so research material is durable + auditable, not just transient state.
- **Human contributes to the SAME folder**: attachments (multi-format intake already exists) AND text answers (a `cos steer` answer is also written as a dated note file in the topic reference store).
- Citations resolve to this store; Albert audits its coverage; iteration accumulates into it; human steering = human adds missing material to it.
- (If this is too large for one pass, ship A + C + D first and land B as a focused follow-up — but record it.)

## C. Hard run cap (don't blow up — esp. with real Albert)
Today: `max_iterations` + branch-budget decay + supervisor top-K bound iterations; only a SOFT budget warning, NO hard cost/time cap. With real Albert (5–20 min/audit) blow-up risk is real. Add:
- `run_loop`/`run_auto` accept `max_cost_usd` and `max_wall_s` (env `CN5_COS_MAX_COST_USD` / `CN5_COS_MAX_WALL_S`). When `metrics.total_usd` ≥ cap OR wall ≥ cap → **hard-stop the loop after the current node, emit the current findings** (degraded-but-honest), record the reason. Deterministic; tested.

## D. Fix the P6 real-Albert crash (part of "quality" — real audit must work)
The dogfood `--albert real` crashes with `'str' object has no attribute 'get'` at/around `albert_audit` (loop dies → thin research). Evidence gathered (2026-06-03): the saved checkpoint `runs/dogfood-real-switchpk/checkpoint.db` shows `snap.next == ('albert_audit',)` and the GraphState has NO `albert` key (so `run_auto` may not thread `albert` into the init GraphState → `_brains` line ~154 defaults to "sim"; yet a direct node call ran real Albert >120s). Contract/`_to_audit`/`build_albert_input`/post-audit all pass OFFLINE on the real flash+full Albert outputs. So: get the ACTUAL traceback (a `--albert real --max-iterations 1` run with the driver printing `traceback.format_exc()`, OR resume the checkpoint with a generous timeout), fix the root cause (likely: an UNGUARDED `.get` on a string somewhere in the real-Albert invocation path that only the real subprocess output triggers — e.g. `_parse_json_out` / sentinel-vs-deep auditor / the `run_auto` albert-threading gap), add a regression test on the REAL-Albert path (mock the subprocess with a REAL captured `albert_challenge.json`), and ensure `run_auto` threads `albert` into the GraphState so `--albert real` is honored.

## Tests / DoD
- **A:** a state with cited evidence → the assembled deliverable LEADS with findings (the answer / requested artifact from the evidence, cited `[S-…]`), decision/Albert as the tail. Mock LLM.
- **C:** a loop that exceeds `max_cost_usd`/`max_wall_s` hard-stops + emits current findings + records the reason (deterministic, fake metrics).
- **D:** the real-Albert path no longer crashes — a regression test feeds a captured real `albert_challenge.json` through the adapter + `node_albert_audit` (mock subprocess) → AuditResult consumed, loop continues; `run_auto(albert="real")` puts `albert` in the GraphState.
- **B (if shipped):** AI-collected source saved to the topic store; a `cos steer` answer written as a note there; scan picks up both human attachments and AI notes.
- **Regression:** P1–P6 stay green.
- **End-to-end:** re-run `topics/switch pk.txt` (`--albert real`, hard-capped) → deliver the FINDINGS report (filled §1/§2 tables, partial/N-A honest, cited) — a research report, not a questions dump. ONE email. ≤2 emails total. Cost-capped.

## Pipeline / guardrails (autonomous run)
spec → writing-plans → subagent-driven-development (TDD, P1–P6 green) → re-run the switch-PK research with a HARD cost cap (e.g. \$10) + bounded iterations → ONE findings email. Supervise: the once-per-run notify + the hard cap prevent email/token blow-up.
