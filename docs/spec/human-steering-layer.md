# Human Steering Layer (Human-in-the-Loop)

> User directive 2026-06-01. Elevates HITL from scattered spec points (§8.1, §9, §13, `steering_events`) to a **first-class layer** that sits ABOVE the AI loop. The AI loop runs autonomously, but the moment it touches **direction, decision, BU preference, restricted/internal data, or source judgment**, it must enter the Human Steering Layer.

## HITL is NOT "review the final report." It lives in 7 places:

1. **Before start** — set mission / default priority (Preflight Gate)
2. **During research** — pull direction when branches diverge
3. **During research** — pull decision when BU preference / Albert decision criterion is required
4. **During research** — push human task when data / document / owner input is missing
5. **After each iteration** — review iteration summary
6. **Any time** — allow ad-hoc steering (human interrupt)
7. **Before end** — confirm whether it is OK to synthesize

## The 6 gates in detail

### 1. Preflight Gate — ask the few key questions before auto mode
Not a questionnaire — only the questions that materially change overnight auto mode. Example:
> This run's main goal is: A. make Albert unable to easily challenge / B. support BU decision / C. surface pending questions & blockers / D. produce executive memo.
> AI recommends: A + B + C. If no reply, default to A + B + C.

This is the first human gate.

### 2. Direction Pull — pull the human when directions diverge mid-research
If multiple directions appear, AI must not fake knowing BU preference. Example:
> Three high-value directions now: A. technical feasibility / B. ROI / cost saving / C. competitor benchmark.
> Albert Thought Agent judges B + C are more likely to be challenged than A.
> Recommend next round = B + C. You: (1) accept, (2) switch to A, (3) open new branch covering A/B/C in parallel.

### 3. Decision Pull — stop when an external decision is needed
Some questions research cannot decide. Example:
> Cannot determine which criterion to evaluate this proposal: A. cost saving / B. speed / C. competitive pressure / D. risk reduction.
> This affects all downstream research priority. Need Albert / BU owner to choose the decision criterion.

This is a call for external decision.

### 4. Help Push — assign a human task to fetch data / download docs / provide internal info
Not asking direction — AI assigns a human task. Example:
> Human Task: download Competitor X enterprise datasheet.
> Why: public web has only marketing claims; cannot confirm the feature truly exists.
> Blocking: Albert may ask "does the competitor already have it?"
> Can continue without it: yes, but competitor-comparison confidence stays medium-low.

This is push human / call for help.

### 5. Review Gate — give the human a review after each iteration
Each round (research → Albert audit → source critique → artifact update) produces a SHORT iteration summary (not a long report):
- What was added this round?
- Where will Albert challenge?
- What is missing now?
- What is recommended next round?
- What does the human need to do?

Then a decision menu:
> A. Continue current branch / B. Branch into competitor benchmark / C. Re-rank toward ROI / D. Pause and wait for human data / E. Synthesize current findings.

This is the human review loop.

### 6. Ad-hoc Steering — human can interrupt and redirect at any time
The human may say mid-run: *"Actually Albert cares about cost saving, not the technology."* The system must NOT re-run everything; it should:
1. Record a steering event (`steering_events`)
2. Re-rank existing evidence
3. Open a cost-saving branch
4. Keep the original technical branch
5. Recompute the readiness score

This is human interrupt / steering event.

## Corrected mental model

```
                 Human Steering Layer
        ┌──────────────────────────────────┐
        │ preflight / pull direction        │
        │ call decision / push human task   │
        │ review / ad-hoc steering          │
        └──────────────────────────────────┘
                         ↓
Issue Map → Research → Albert Audit → Update Artifacts
    ↑                                         ↓
    └────────── Chief-of-Staff Decision ──────┘
```

## Full flow

```
Meeting question in
↓
Preflight Human Gate
↓
AI builds Issue Map / Challenge Map / Readiness Board
↓
AI Research Loop:
    Research
    → Albert Thought Audit
    → Source / Skeptic Check
    → Update Artifacts
    → Readiness Scoring
    → Chief-of-Staff Decision
        ├─ continue research        → back to Research Loop
        ├─ branch / rerank          → back to Issue Map
        ├─ pull human direction     → wait for steering → back to Issue Map
        ├─ call external decision   → wait for Albert / BU owner → back to Issue Map
        ├─ push human task          → human supplies doc / data → back to Evidence Map
        ├─ pause                    → wait for required input
        └─ synthesize / stop
```

## One line

**The AI loop can run by itself, but whenever it hits direction, decision, BU preference, permissioned data, internal data, or source judgment, it must enter the Human Steering Layer.**

## Build mapping (which phase implements which gate)

- Gates 1 (Preflight), 5 (Review menu) → P3 (auto mode + iteration summary) and partially P1 (deterministic decision menu rendering).
- Gates 2 (Direction Pull), 3 (Decision Pull) → P1 deterministic `pull_human` node (stub messages) → richer in P2/P3.
- Gate 4 (Help Push) → P1 deterministic `push_human` node + `HumanTask` generation → P3 full.
- Gate 6 (Ad-hoc Steering) → `steering_events` data model in P1; live interrupt handling in P3 (interrupt/resume HITL).
