# Phase 4b — adversarial convergence + source ranking + citation discipline (design)

> 2026-06-03. Decided via multi-round discussion (+ a real GitHub source deep-read of GPT Researcher / Open Deep Research, 2026-06-03 — which CORRECTED our one-line gap-audit summary; see "Source-grounded corrections" below). Builds on P2b (real brains, `AlbertChallenge`/`AuditResult`/`albert_challenge_map`), P3 (HITL gates + `risk.classify_pull`), P4a (internal-doc evidence). Parent: `docs/spec/phases-P2-P6-spec.md` (P4b). DoD: the audit loop **converges** (challenges carry forward + resolve) and claims are **citation-verified or escalated**; P1–P4a tests stay green. After P4b: run the **TC4 partial-reset baseline** (`docs/poc/tc4-partial-reset-reference.md`).

P4b has **three components**. They share one theme: the adversarial loop must carry state forward and converge, not throw away each round.

---

## Component 1 — Adversarial convergence engine (the "修")
**Problem (diagnosed, code-cited):** challenges persist in `albert_challenge_map` but the loop does NOT carry the dialogue forward → no convergence, prior rounds wasted. Three breakpoints:
- `artifacts/challenge_map.py:add` mints a NEW id every call → duplicates pile up, prior `status`/`current_answer` lost (no dedup/merge).
- `albert/simulator.py` builds the auditor prompt from `issue_map` only, NOT `albert_challenge_map` → Albert re-audits blind, can't mark resolved or avoid re-asking.
- `brains/real.py` researcher prompt uses issue title/status/confidence, NOT open challenges → next-round research doesn't target Albert's open questions.

**Fix (4 parts):**
1. **Challenge identity + merge** (`challenge_map.py`): `add`/`upsert` dedups against existing OPEN challenges by a stable key (deterministic: normalized-text + fuzzy `difflib` ≥ a threshold, OR the auditor referencing a prior `challenge_id`). A match UPDATES the existing challenge (status, `current_answer`, `evidence_refs`, `rounds_seen`) instead of minting a duplicate. New challenges get a new id. Pure, unit-tested.
2. **Feed prior open challenges INTO the auditor** (`simulator.py` input): the auditor receives the current OPEN challenges + their `current_answer`/`evidence_refs`, and is instructed to (a) mark answered ones `resolved`, (b) escalate still-unanswered ones, (c) NOT re-raise an existing open one verbatim — reference its id. Output schema already carries `current_answer`/`status`; this adds the prior-challenge INPUT so resolution is trackable.
3. **Feed open challenges INTO researcher/COS** (`real.py` researcher + the COS decision): next-round research is DIRECTED by open challenges — the COS prioritizes issues/sub-questions that ANSWER open challenges; the researcher prompt includes "Albert is challenging X (id …) — find evidence to answer it." Closes the loop: challenge → targeted research → answer → Albert re-checks → resolve.
4. **Convergence tracking** (`decision/` + readiness): a challenge moves `open → answered → resolved` (or `escalated_to_human`). Convergence signal = open-challenge count trends to 0 / all remaining are human-blocked. `readiness.albert_challenge_readiness` reflects resolved-vs-open ratio. The existing exhaustion/plateau + emission gate consume this (a memo can't emit with unresolved high-impact challenges).

**[COPY from ODR — verified in source]** append-by-default note/citation semantics (ODR `override_reducer`: default `operator.add`, explicit `{"type":"override"}` to replace) so challenges/notes/evidence are never SILENTLY dropped across rounds — only explicitly superseded.

---

## Component 2 — Two-altitude source ranking (no embedding)
**Source-grounded correction (GPTR real code):** the cheap filter is LangChain `EmbeddingsFilter` (cosine, threshold 0.35, chunk 1000/overlap 100, top-k 5) but it **short-circuits and SKIPS embeddings** when input is small (`< 8000` chars AND `<= max_results`). At our scale (one WebSearch/issue → a handful of sources) we are ALWAYS in the short-circuit regime, and we have no embedding key (subscription SDK). So we faithfully match GPTR's small-input behavior WITHOUT embeddings.
- **Cheap filter (`ranking/heuristic.py`, deterministic, always on):** URL dedup (flatten near-dup URLs), drop obvious junk, simple relevance (issue-keyword overlap) + recency/known-authority heuristic; cap top-k. Pure, unit-tested, no LLM, no dependency.
- **LLM curator (`ranking/curator.py`, opt-in, on survivors):** GPTR's **real** 5 dimensions — **Relevance / Credibility / Currency / Objectivity / Quantitative-Value** (CORRECTED from our summary's wrong "relevance/credibility/reliability"). It is a **filter, not a rewriter** ("don't rewrite/summarize/condense; return the same source-list shape"); **falls back to uncurated on parse failure** (GPTR `curator.py` behavior). Off by default (a flag), SMART-tier model when on.
- `[SKIP — framework-specific]` LangChain `EmbeddingsFilter`/`DocumentCompressorPipeline`/retriever wiring; reimplement the SHAPE, not their glue.

---

## Component 3 — Citation discipline / anti-fabrication (our own design — verified NOT in GPTR/ODR)
**Source-grounded correction:** NEITHER GPTR NOR ODR does verbatim/fuzzy claim→source verification (both rely on prompt instruction only). So verbatim-≥0.85 AND flatten-to-primary are **OUR net-new design** — we will NOT present them as industry-standard.
- **Verbatim verify (`citation/verify.py`, deterministic, no LLM, no dep):** each claim already carries a verbatim quote (the researcher extracts it). Verify the quote appears in the cited source text via stdlib `difflib` ratio **≥ 0.85**. Pure, unit-tested at the 0.85 boundary (match / no-match / paraphrase).
- **Tiered failure policy (`citation/policy.py`, deterministic — the user's escalation rule):**
  1. Quote fails verify → mark the claim `unverified`; it is **never emitted as fact**.
  2. **Auto re-verify**: the loop re-researches that issue / seeks a corroborating PRIMARY source ("未驗證就去驗證").
  3. Still unverified **AND decision-critical** (high `impact` / linked to `decision_criterion` — reuse `risk.classify_pull` logic) → **escalate to HUMAN** via P3's gate (H1/H5 `human_pull` "verify or judge this claim", or H3 `human_push` verification task). ("請人來驗證或請人類下判斷").
  4. Still unverified **AND non-critical** → flag + lower confidence + record a coverage_gap; the **emission gate refuses a memo whose key claims are unverified** (decision #8).
- **Flatten-to-primary (`citation/policy.py`, our design):** a claim's citation must resolve to a PRIMARY `Source`, never a sibling worker's digest/compressed summary. Enforced at assembly: claims cite original `Source` ids, not another bundle's `compress` output.
- **[COPY from GPTR/ODR — verified]** retain RAW alongside COMPRESSED (compress for the writer, keep raw `notes` for verification/audit — ODR keeps `raw_notes` next to `compressed_research`); numbered-URL "assign each unique URL one number, end with `### Sources`, don't lose any sources" citation contract (ODR `compress_research` prompt).

---

## Modules
- `decision/convergence.py` (challenge open/answered/resolved tracking + convergence signal — pure), extend `artifacts/challenge_map.py` (merge/upsert), extend `albert/simulator.py` (prior-challenge input), extend `brains/real.py` (challenge-directed research prompt) + the COS decision (prioritize open challenges).
- `ranking/{heuristic,curator}.py`; wire ranking after research, before compress.
- `citation/{verify,policy}.py`; wire verify after research/critic; escalation routes into existing `decision` + P3 HITL gates; emission gate reads unverified-key-claims.

## Deterministic-vs-LLM split (§14)
- **Deterministic:** challenge merge/dedup, convergence tracking, heuristic filter, verbatim verify, criticality classification, escalation routing, flatten-to-primary, override-reducer semantics.
- **LLM (narrow):** the auditor (now sees prior challenges), the researcher (now challenge-directed), the curator (opt-in). All structured-output; control stays in Python.

## Out of scope
- B3 grounded decomposition (cheap search before issue-expand — real in GPTR `plan_research`, deferred; auto-reverify already gives grounding-like targeted search).
- Embedding-based ranking (matched GPTR's small-input skip → not needed at our scale).
- P5 synthesis/final memo (still stub; the TC4 baseline's polished deliverable needs P5).
- GPTR/ODR as installed research engines (rejected — nesting two research loops; we absorbed PATTERNS, not code).

## Tests / DoD
- **Convergence (deterministic, mock brains):** a challenge raised round N is MERGED (not duplicated) round N+1; an answered challenge → `resolved`; an open challenge is fed into the next researcher prompt + COS prioritization (assert the prompt/selection contains it); convergence signal drops as challenges resolve; a run where challenges keep resolving terminates with `open→0`, a run with an unanswerable critical challenge escalates to a human gate (not infinite loop).
- **Ranking (deterministic):** heuristic dedup/junk-drop/top-k on hand-built source lists; curator opt-in mocked (5 dims, filter-not-rewrite, fallback-to-uncurated on parse failure).
- **Citation (deterministic):** verbatim verify at the 0.85 boundary (match/no-match/paraphrase); tiered policy — unverified→reverify; critical-unverified→human gate; non-critical-unverified→flag + emission-gate refuses; flatten-to-primary rejects a claim citing a digest.
- **Regression:** P1–P4a (all current tests) STAY GREEN.
- **Live (opt-in `CN5_COS_LLM_TESTS=1`):** a short real run where Albert raises a challenge, the next round's research targets it, and it resolves (or escalates) — proving the loop converges end-to-end on real LLMs.
- Committed; push on user confirmation.

## Source-grounded corrections (honesty ledger — what the real GPTR/ODR code showed vs our prior summary)
1. Curator dims are **Relevance/Credibility/Currency/Objectivity/Quantitative-Value**, NOT "relevance/credibility/reliability." (GPTR `prompts.py::curate_sources`.)
2. **Verbatim/fuzzy claim verification is NOT in either repo** — both are prompt-only. Verbatim-≥0.85 is OUR design.
3. **Flatten-to-primary is NOT in either repo** — ODR is digest-of-digest. Ours.
4. GPTR's cheap filter **skips embeddings on small input** — justifies our no-embedding heuristic at our scale.
5. The portable IP is ODR's `override_reducer` (append-not-drop) + retain-raw-alongside-compressed + numbered-URL contract, and GPTR's curator prompt contract.
