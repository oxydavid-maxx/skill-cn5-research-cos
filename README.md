# skill-cn5-research-cos — User Manual

**CN5 Chief-of-Staff (COS) Research Agent / BU Research Cockpit.**

A continuous, audit-driven, human-steered research cockpit that behaves like a
strong chief-of-staff. It repeatedly researches a question, audits the answer from
**Albert's** (BU-head) perspective, challenges it, updates living artifacts, and
decides whether to **continue / branch / re-rank / pull-human / push-human /
synthesize** — until the work is ready for leadership-level challenge and decision.

> The evolving research *state* is the product — not a one-shot report. This is a
> cockpit you steer, not a bot you fire-and-forget.

---

## 1. What the cockpit is

- **Continuous + audit-driven.** Each iteration: research → skeptic counter →
  Albert audit → update artifacts → score readiness → decide. It stops only for a
  correct reason (research exhausted + readiness met, or a saturated frontier), and
  it documents *why* it stopped.
- **Human-steered, not human-blocked.** When it needs you, it does NOT freeze the
  whole run. Low-risk decisions apply a safe default; high-risk ones pause and wait
  for you (resumable); and an unverifiable critical claim emails you and *continues*
  (see §5).
- **Honest by construction.** A claim that cannot be citation-verified is never
  presented as fact. It is either dropped (non-critical) or surfaced as
  "needs human supplement" (critical) — never fabricated.

---

## 1.5 The full research flow

> Status tags: **[now]** = built · **[P8]** = designed in
> [`docs/spec/2026-06-04-phase8-socratic-orchestration-quality-design.md`](docs/spec/2026-06-04-phase8-socratic-orchestration-quality-design.md),
> not yet implemented · **[NET-NEW]** = our strengthening beyond typical SOTA
> (ODR / GPT-Researcher / Anthropic / WebWeaver / WebDART), honestly labelled.

```
 INTAKE
   │
   ▼
 H0 — SOCRATIC CLARIFICATION   [P8 multi-round; now: cos clarify multi-turn]
   · the cockpit ASKS, the human ANSWERS — until all 4 are pinned:
       purpose / decision-anchor · scope in-out · success-form · constraints (+ existing material)
   · AFK → PAUSE (opt-in: --assume-brief / best-effort to run on stated assumptions)
   ▼
 WRITE BRIEF   (locked by the dialogue: brief + decision-criterion + success-form)
   │
   ▼
┌── OUTER ORCHESTRATION LOOP (reused every cycle; loop head = orchestrator) ──────────┐
│ ① PLAN / DECOMPOSE   [P8]   build/update the task grid: vendor × spec-group,         │
│    each cell = a report row + {objective, output-format, tools, boundaries};         │
│    input = prior results + prior Albert challenges + coverage gaps  (adaptive)       │
│ ② REFLECT + AUDIT                                                                    │
│    (a) self-reflect: which cells next?                       [P8]                    │
│    (b) Albert plan-audit (flash; skipped if plan unchanged)  [P8 · NET-NEW]          │
│    (c) H7 human plan-approval (first cycle + major re-plan)  [P8]                    │
│ ③ DISPATCH — supervisor picks top-K cells → parallel sub-agents (own context): [now] │
│       research (web / internal-doc) → reflect gaps → source-critic → compress        │
│ ④ COLLECT + skeptic counter                                  [now]                   │
│ ⑤ AUDIT RESULTS — Albert (quality / drift) → challenges feed next ① [now · NET-NEW] │
│ ⑥ READINESS / DECIDE                                         [now; P8 loops to ①]    │
│    ├ converged (grid covered + Albert satisfied) ───────────► exit → synthesize      │
│    ├ cap hit (8h / cost) ───────────────────────────────────► exit (degraded-honest)│
│    ├ H3 needs internal data ──► HumanTask, continue adjacent  [now, non-blocking]    │
│    ├ critical claim unverifiable ──► supplement email (once/run) + continue [now]    │
│    ├ H1 / H2 / H5 high-risk or all-blocked ─────────────────► PAUSE + email [now]    │
│    └ else ──────────────────────────────────────────────────► re-plan (back to ①)   │
└─────────────────────────────────────────────────────────────────────────────────────┘
   │   ◄── H4 — `cos steer <run>` : redirect / drop material, ANYTIME, non-blocking → next cycle
   ▼
 H6 — FINAL REVIEW   (confirm / revise before synthesize)     [now]
   ▼
 SYNTHESIZE   (section-aware: each cell → a report row; findings-first)   [P8: Opus]
   ▼
 CITE   (verbatim ≥0.85 / flatten-to-primary; unverified-critical → supplement, never faked)  [now]
   ▼
 DELIVER — findings-first cited report  (one email)
```

**HITL gates (human-in-the-loop) — H0–H6 unchanged, H7 new in P8:**

| Gate | Meaning | Where | Blocking |
|---|---|---|---|
| **H0** preflight / Socratic clarify | pin purpose·scope·success·constraints | front | yes |
| **H1** pull-direction | direction unclear → pull human (high-risk) | loop ⑥ | yes |
| **H2** call-decision | a decision needs the human | loop ⑥ | yes |
| **H3** push-human | needs internal data → HumanTask, continue | loop ⑥ | no |
| **H4** ad-hoc steering | `cos steer` → next cycle re-ranks / branches | anytime | no |
| **H5** call-help | hard blocker → interrupt (even in auto) | loop ⑥ | yes |
| **H6** final-review | confirm / revise before synthesize | exit | yes |
| **H7** plan-approval **[P8]** | OK the task-grid before expensive research | loop ②(c) | first cycle |

**Caps + model tier:** the loop runs up to **8h** wall (`CN5_COS_MAX_WALL_S`, P8 default 28800) and a cost cap (`CN5_COS_MAX_COST_USD`), and **does not stop early while a high-impact cell is still researchable**. Model tier **[P8]**: **Sonnet** researcher (PhD student) · **Opus** synthesis · Albert auditor **Opus** (professor) · haiku for mechanical micro-steps.

The heavy human steering is **up front (H0 Socratic)**; inside the loop the human is **always able to steer (H4) but is not interrogated every cycle** — the cockpit only reaches out on a genuine gap (H3 / supplement / H1·H2·H5). This avoids both inbox-flood and an 8-hour idle.

---

## 2. Setup

```bash
pip install -e ".[dev]"
PYTHONPATH=src py -3 -m pytest -q        # the test suite
```

**Internal-document research (optional but recommended).** The cockpit reads
internal PDFs/specs through the external **paperwork** plugin (gerrit
`cn5dd2/CN5DD2_common/plugins/paperwork`, v7+ docling-strict). Point the cockpit at
your checkout:

```bash
export CN5_PAPERWORK_HOME=/path/to/cn5dd2/CN5DD2_common/plugins/paperwork   # bash
$env:CN5_PAPERWORK_HOME = "D:\...\cn5dd2\CN5DD2_common\plugins\paperwork"     # PowerShell
```

If `CN5_PAPERWORK_HOME` is unset and no sibling checkout is found, internal-doc
research **degrades to web-only** with a visible warning — it never fabricates
internal evidence. Office documents (Word/PPT/Excel) are converted with **docling**
directly and do not require a paperwork home; only the PDF/HTML pipelines use it.

Runtime state lives under `runs/<run_id>/` (`state.json` snapshot + `checkpoint.db`
LangGraph checkpoint). Override the base dir with `CN5_COS_BASE_DIR`.

---

## 3. Running

### Step 1 — clarify the question into a brief (`cos clarify`)

Multi-turn clarification that converges your (possibly vague) topic into an
SOT brief:

```bash
cos clarify --question "AI 能否做隔夜 BU 研究，人類為何還要 in-the-loop" --run-id demo
# answer each clarifying question:
cos clarify --answer "目標是說服 leadership" --run-id demo
```

### Step 2 — run the loop (`cos run` / `cos run-auto`)

```bash
# interactive: pauses at a human-decision gate, prints the ask + how to resume
cos run --question "AI 能否做隔夜 BU 研究" --run-id demo --llm real

# overnight AUTO: low-risk gates auto-default, high-risk hard-stops (resumable)
cos run-auto --question "AI 能否做隔夜 BU 研究" --run-id demo --llm real \
  --default-priority "competitor"
```

### Step 3 — inspect (`cos show` / `cos brief`)

```bash
cos show demo --artifact all        # issue map + Albert challenges + board + readiness
cos brief demo                      # the SOT brief
cos validate demo                   # re-validate the saved state
```

---

## 4. Watching the debate live (P5b)

Both `cos run` and `cos run-auto` **stream the adversarial debate to your terminal
as it happens** (`--stream`, on by default). Each stage prints a short
human-readable block — and **Albert's full challenges are shown verbatim**, not
summarized — so you can watch the cockpit argue with itself and see how each round
resolves into an action. The stream is flushed and non-tty-safe, so it **survives a
pipe / redirect / background** (`cos run ... | tee run.log` works).

Turn it off with `--no-stream`.

---

## 5. The async-supplement flow (the key new section)

When the cockpit hits a **decision-critical claim it cannot citation-verify**, it
does **not** fabricate and does **not** stop the whole run. Instead it:

1. **records a HumanTask** (visible via `cos show <run_id>`),
2. **emails you** (via your Outlook) with exactly what is needed + copy-paste
   commands, and
3. **CONTINUES** other branches. The §22 memo still emits; the unverified-critical
   item appears only in **"What We Cannot Say" / "Required Human Decisions"**,
   clearly flagged **"needs human supplement" (需人類補充)** — never as fact.

You supplement it **asynchronously**, whenever you like, in one of two ways:

### (a) Text answer

```bash
cos steer demo "我們的決策準則是成本，competitor X 已有此能力，優先研究 ROI"
```

### (b) Document drop — PDF / PPT / Word / Excel / HTML / Markdown

Drop the file into the run's reference folder, then tell the cockpit:

```bash
# 1) copy your file into:
#      runs/demo/reference/
#    (e.g. runs/demo/reference/competitor-datasheet.pdf)
# 2) then:
cos steer demo "added competitor-datasheet.pdf"
```

The next iteration **scans `runs/<run_id>/reference/`**, converts each new file by
type, and folds it into the evidence so the cockpit re-researches / re-verifies the
flagged item:

| You drop…              | Converted via                                  |
|------------------------|------------------------------------------------|
| `.pdf`                 | paperwork selective pipeline (outline → range → docling) |
| `.docx` `.pptx` `.xlsx`| **docling directly** (Word / PPT / Excel)      |
| `.html` `.htm`         | paperwork `html2md`                            |
| `.md` `.txt`           | read directly                                  |
| anything else          | recorded as a coverage gap + a visible warning (never silently dropped) |

Each file is processed **once** (dedup by name + modified-time), so re-scanning an
unchanged folder every iteration is free.

> v2 (planned): replying to the supplement email with the document attached will
> auto-ingest it into `runs/<run_id>/reference/` and auto-resume — no manual copy.

---

## 6. The §22 decision memo + the gates

At the terminal/synthesize seam the cockpit assembles the **§22 decision memo** — 9
sections written for a BU war-room:

1. Executive Answer · 2. Albert Challenge Map · 3. What We Can / Cannot Say ·
4. What Is Blocking Us · 5. Required Human Decisions / Inputs · 6. Evidence Summary
(cited) · 7. Risks & Assumptions · 8. Recommended Next Action · 9. Appendix.

The memo emits only when the **emission gates** pass. Two are *correctness* gates
(an explicit emit command can NEVER bypass them):

- **Degraded-audit gate** — the Albert audit must have genuinely run (not a
  degraded/mock pass).
- **Citation gate** — no unverified claim is presented **as fact**. (Unverified-
  critical items are moved to "What We Cannot Say / Required Human Decisions",
  flagged "needs human supplement" — so the memo can emit honestly while these are
  surfaced, never faked.)

Two are *completeness* gates (skipped on an explicit emit command, because the memo
itself documents the open items honestly):

- **Convergence gate** — no unresolved high-impact Albert challenge.
- **Readiness gate** — the readiness target is met.

A refused memo is still written (with a `NOT EMITTED — <reason>` banner) so you see
*why*.

---

## 7. Resuming a paused run

```bash
cos resume demo --choice A            # answer an A/B/C ask
cos resume demo --answer "..."        # free-text answer
cos run --resume --run-id demo        # continue from the LangGraph checkpoint
```

Crashed or paused runs resume from the SqliteSaver checkpoint — they never re-run
from scratch.

---

## Key architecture facts (for maintainers)

- **Package:** `cn5_research_cos` · **CLI:** `cos`.
- **LLM backend:** Claude Agent SDK behind a mock + injection seam (`--llm mock|real`).
  The deterministic core (confidence routing, reference scan/routing, email
  composition, gates) has **no LLM** — only the researcher/synthesizer are LLM.
- **"Albert" reviewer is an EXTERNAL skill** —
  [`skill-cn5-i-am-albert`](https://github.com/oxydavid-maxx/skill-cn5-i-am-albert)
  — which this cockpit *consumes* (does not build).
- **paperwork dependency:** gerrit `cn5dd2/CN5DD2_common/plugins/paperwork` (v7+
  `docling-strict`: `docling` is the only valid backend for citable PDF fragments).
  Set `CN5_PAPERWORK_HOME`; absent → web-only degrade with a visible warning.

## Docs (source of truth)

- [`docs/spec/PRODUCT-SPEC.md`](docs/spec/PRODUCT-SPEC.md) — the authoritative product specification.
- [`docs/superpowers/plans/2026-06-01-master-backbone.md`](docs/superpowers/plans/2026-06-01-master-backbone.md) — the 6-phase execution backbone + Human Steering Layer (HITL) model.
- `docs/spec/2026-06-03-phase5c-citation-honesty-async-supplement-design.md` — the citation-honesty + async-supplement design (this manual's §5).
