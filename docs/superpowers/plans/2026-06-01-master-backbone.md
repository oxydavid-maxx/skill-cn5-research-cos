# skill-cn5-research-cos — MASTER SPEC + EXECUTION BACKBONE

> **Single durable source of truth** (anti-goldfish, for a 1M-token context that forgets across rounds).
> **Part A** = the FUNCTIONAL SPEC (what the skill concretely does — faithful capture of the user's full spec, Sections 0–30).
> **Part B** = the EXECUTION BACKBONE (how we build it, 6 phases).
> **Part C** = working protocol, open decisions, next step.
> Re-read this file at the start of every round. The user's original 1600-line spec is the ultimate authority; this is its organized capture. Once out of plan mode, the user's verbatim spec is also saved into the repo at `docs/spec/PRODUCT-SPEC.md`.

---

# PART A — FUNCTIONAL SPECIFICATION (what the skill does)

## A0. Identity & one-line definition (§0, §30)

- **Name / repo:** `skill-cn5-research-cos`. Package `cn5_research_cos`. CLI `cos`. (Spec working name: `bu-research-cockpit` / `chief-of-staff-research-agent`.)
- **What it is:** *A continuous, audit-driven, human-steered research cockpit that behaves like a strong chief-of-staff.* It repeatedly researches, audits, challenges, updates artifacts, and decides whether to **continue / branch / re-rank / pull-human / push-human / synthesize** — until the team is ready for Albert-level challenge and decision-making.
- **What it is NOT:** a one-shot deep-research bot; a 2–3 shot pipeline; a long-report generator; a passive assistant. **The evolving research state is the product, not the final memo.**

## A1. Product goal (§1)

Help a strategy / PM / BU-support person prepare for difficult meeting questions from **Albert / BU leadership**. It continuously: expand problem space → maintain Dynamic Issue Map → research high-value branches → audit from Albert's perspective → update challenge/readiness artifacts → decide next move → stop only when readiness criteria met OR remaining blockers are clearly human / internal-data / decision dependent.

## A2. Core philosophy — the convergence loop (§2)

NOT linear (Intake→Research→Summary→Memo). The model is a loop:
`Current Issue Map → AI research → Albert-style audit → multi-agent critique → artifact update → readiness scoring → (continue / branch / re-rank / pull-human / push-human / synthesize) → repeat until readiness target reached.`
The system behaves like a strong chief-of-staff, not a passive assistant.

## A3. Main user (§3)

- **MVP primary:** Strategy staff / PM / meeting-support person, preparing to answer Albert/BU challenges.
- **NOT MVP:** Albert directly; general employees; fully-autonomous enterprise agent platform; generic research chatbot users.

## A4. Success criteria — four readiness states (§4)

1. **Albert Challenge Readiness** — Albert's likely challenges are surfaced, organized, status-assigned. Each challenge categorized: `Answered / Partially answered / Needs external research / Needs internal data / Needs BU judgment / Needs Albert decision / Needs source validation / Blocked`. Goal: team knows what can/can't be answered and why — not that every challenge is perfectly answered.
2. **Decision Readiness** — research supports an actual BU decision. For every major finding ask: does this change the decision? does it support do / don't / delay / pilot / ask-more-data? what decision criterion is used? is it explicit or assumed? If research doesn't improve decision quality, say so.
3. **Research Exhaustion Readiness** — don't stop prematurely. Can stop external research only when: major high-value branches explored; new sources mostly repetitive; no new high-impact meta-question from Albert auditor; continuing wouldn't materially change the decision; unresolved items are mostly internal-data / human-judgment / decision blockers.
4. **Human Bottleneck Clarity** — clearly identify when the blocker is no longer research (e.g. competitor datasheet behind login; BU owner internal usage data; Albert decision criterion; domain-owner assumption validation; human judgment on source credibility). Convert vague "need more research" into **specific human tasks**.

## A5. The three living artifacts (§5) — continuously updated across iterations

### A5.1 Dynamic Issue Map — exploration / unknown-unknown discovery / problem-space expansion
Each issue node fields:
`id, parent_id, title, description, issue_type, status, impact, confidence, evidence_refs, unknowns, counterarguments, human_blockers, next_actions, last_updated, last_audited`.
**issue_type** ∈ `root_question, intent, technical_feasibility, roi, cost, competitor, risk, internal_data, human_judgment, decision_criterion, source_conflict, unknown_unknown`.
**status** ∈ `open, researching, partially_answered, answered, blocked_by_human, blocked_by_internal_data, blocked_by_permission, blocked_by_decision, low_confidence, ready_for_synthesis`.

### A5.2 Albert Challenge Map — defense / meeting prep / leadership challenge simulation
Answers: what would Albert challenge? can we answer it? if not, why not? Each challenge fields:
`challenge, why_albert_would_ask, current_answer, status, confidence, evidence_refs, missing_info, blocking_owner, next_action, meeting_ready_response`.
This is the main output of the Albert Thought Agent.

### A5.3 Research Readiness Board — PM / progress tracking / stop-continue decisions
Columns: `Answered, Partially Answered, Needs External Research, Needs Internal Data, Needs BU Judgment, Needs Albert Decision, Needs Source Validation, Blocked, Ready for Memo`. Each board item links back to Issue Map nodes + Albert Challenge entries. **(Our design: board is DERIVED from issue/challenge status, not stored separately.)**

## A6. Agent roles (§6) — functional roles, avoid agent theater

### A6.1 Chief-of-Staff Agent (main orchestrator)
Maintains research direction; decides continue/branch/re-rank/pull-human/push-human/synthesize; pushes back against bad human direction; prevents premature closure AND endless research; translates research state into actionable next steps; enforces readiness criteria.
**Behavior:** strong, direct, decision-oriented; does NOT flatter user; does NOT hide uncertainty; does NOT produce long reports to mask weak evidence.
*Example:* "I do not recommend continuing technical feasibility research. The blocker is not feasibility; it is ROI and competitor benchmark. Continuing technical research will increase appendix length but not improve decision readiness. Recommended: re-rank toward cost impact and competitor evidence."

### A6.2 Researcher Agent
Research a specific issue branch; gather sources; extract claims; track citations; identify missing evidence; return structured evidence bundles. Does NOT decide whether the whole project is done.

> **ARCHITECTURE (user directive 2026-06-01):** The Albert Thought Agent is NOT built in-repo. It is a **separate, independently-versioned skill** at `github.com/oxydavid-maxx/skill-cn5-i-am-albert` ("I am Albert" — a high-standard product/architecture war-room reviewer grounded in real CN5 Gateway war-room transcripts). This cockpit's `albert_thought_audit_node` is a **CLIENT/ADAPTER** that invokes that skill and maps its output into our `AlbertChallenge` model + readiness deltas. The seam between the two repos is an **integration contract** (watched by R17 closed-loop). Albert's own rubric (3 danger ambiguities → 10 soul questions → missing-evidence list → decision gate → one-line verdict: 可推進/要補證據/方向錯/產品定義不完整) plus its 12 "bones" (precise-definition, will-it-win, first-principles service decomposition, local-vs-central compute, latency/deterministic, competitor→strategy, owner/no-多頭馬車, internal-vs-external framing, war-room-converge-now, spec+business+schedule together, red-team the thesis, reproducible judgment) are owned and maintained in THAT repo, not here.

### A6.3 Albert Thought Agent (FIRST-CLASS module; EXTERNAL skill `skill-cn5-i-am-albert`, §29)
**Purpose:** audit research from Albert's perspective; simulate how Albert would challenge; detect weak reasoning, premature closure, missing business framing, unexplored challenge angles. NOT generic QA — thinks like Albert.
**Responsibilities:** read Issue Map / Evidence Map / Stage Summary / draft answer; ask "if I were Albert, what would I challenge?"; judge whether answer survives a leadership meeting; detect vague claims, weak evidence, missing ROI/competitor/owner/decision-criterion; detect whether AI is using research volume to hide lack of decision clarity; generate Albert-style challenge questions; recommend continue / pull-human / push-human / synthesize.
**Outputs:** `albert_challenges, weak_points, missing_business_context, missing_evidence, questions_albert_would_ask, premature_end_risk, research_drift_risk, recommended_next_probe, readiness_score_delta`.
**Important:** skeptical but USEFUL — not merely negative; helps COS decide next move.
*Example audit:* answer says "AI can do overnight research but human steering needed." Albert would challenge: (1) why can't AI ask clarifying Qs upfront then run overnight? (2) what exactly requires human judgment? (3) is this an excuse to keep humans in loop? (4) which parts can be automated now? (5) what would a mature SOTA product do? (6) if bottleneck is human, why build this? Weakness: explains why steering matters but doesn't quantify automatable-vs-BU-judgment. Next probe: research existing autonomous deep-research systems w/ HITL checkpoints; compare what they automate vs still require humans to decide.

### A6.4 Skeptic / Counterargument Agent
Find alternative explanations; challenge current conclusion; search evidence AGAINST emerging answer; identify overfit to user's existing belief. General reasoning perspective (not Albert-specific).

### A6.5 Source Critic Agent
Evaluate source quality; detect SEO/marketing/low-quality; flag unsupported claims; compare primary vs secondary; track source confidence.

### A6.6 Synthesis Agent
Update artifacts; produce concise summaries; convert evidence into executive language; maintain Chinese output; generate meeting-ready wording.

## A7. Core loop (§7) + graph nodes (§18) + decision logic (§19)

**Cycle shape:** (1) select highest-value issue branch → (2) research branch or re-rank existing evidence → (3) normalize findings into evidence bundles → (4) update Issue Map → (5) run Albert Thought audit → (6) run source/counterargument critique if needed → (7) update Albert Challenge Map → (8) update Readiness Board → (9) score readiness → (10) decide next action.
**Next actions** ∈ `continue_research, branch, rerank, pull_human, push_human, synthesize, pause, terminal_stop`.
**MVP graph nodes (must LOOP, not run-once):** `intake_node, issue_expansion_node, research_planning_node, research_worker_node, evidence_normalizer_node, albert_thought_audit_node, counterargument_node, source_critic_node, artifact_update_node, readiness_scoring_node, chief_of_staff_decision_node, human_pull_node, human_push_node, synthesis_node, terminal_node`.
**COS decision output schema:** `{decision, reason, selected_issue_ids[], recommended_next_queries[], human_message, default_action_if_no_response}`.

## A8. Auto mode (§8) — overnight-style

Not reckless autonomy: after enough initial clarification, run multiple research/audit/update cycles without constant human input.
**A8.1 Pre-flight** needs: `original_question, meeting_context, target_audience, likely_albert_concern, output_purpose, known_constraints, forbidden_directions, available_sources, internal_documents_available_or_not, default_research_priority, fallback_behavior_if_human_unavailable`. If missing, ask ONLY minimal high-leverage questions (chief-of-staff style, not a long questionnaire).
**A8.2 Allowed:** broad issue expansion; branch research; counterargument search; source-quality review; Albert audit iteration; readiness scoring; artifact updates; draft synthesis; generate human task queue; continue non-blocked branches.
**A8.3 Forbidden:** pretend to have internal data it lacks; decide BU preference itself; decide Albert's final decision criterion itself; convert low-confidence public claims into strong conclusions; terminal-stop while high-impact ambiguity remains; hide blockers in prose.
**A8.4 Blocker handling:** *Soft* (incomplete source / one claim lacks 2nd source) → lower confidence, find substitutes, continue. *Medium* (competitor datasheet behind login / internal data unavailable / sources conflict) → create human task, continue adjacent branches. *Hard* (decision criterion unknown & all high-value paths depend on it / all core evidence needs internal data / public data can't support conclusion) → call help, pause main loop, produce minimum human input request.
**Help-call format:** numbered decision-criterion options (A cost / B competitive pressure / C feasibility / D risk) + missing-data request + "if no response, continue with default A+B, confidence medium-low".

## A9. Stop conditions (§9) — four distinct kinds

- **A9.1 Pull Human (NOT terminal):** when multiple high-impact intents & AI can't safely choose / next research budget has major tradeoff / BU preference required / decision criterion required / direction may be drifting / Albert audit finds a challenge needing human judgment. Format: `Context / Why asking / Options / AI recommendation / Impact of each / Default if no response`.
- **A9.2 Push Human (creates a human task):** when need internal data / restricted-doc access / competitor datasheet from portal / source validation / domain-owner assumption validation / Albert-BU decision criterion. Task fields: `task_title, owner, requested_input, why_needed, blocking_question, priority, can_continue_without_it, fallback_plan`.
- **A9.3 Stop Research, Continue Synthesis:** when new sources repeat / Albert audit has no new high-impact challenge / Challenge Map mostly classified / unresolved items are human-data-decision blockers / continuing won't materially change decision → stop external research, move to synthesis (executive answer, readiness board, blockers, appendix).
- **A9.4 Terminal Stop (allowed only when):** all four readiness ≥ target; OR all unresolved high-impact questions clearly assigned to human/internal-data/decision tasks AND no high-value external research branch left.

## A10. Anti-premature-end guardrails (§10)

Cannot terminal-stop until completed: (1) broad issue expansion; (2) Albert Thought audit; (3) counterargument pass; (4) source-confidence check; (5) pending-question extraction; (6) human/data/decision blocker classification; (7) ≥1 explicit explanation of why continuing research would/wouldn't help. **Auto mode also requires:** >1 research/audit cycle; ≥1 adversarial challenge cycle; ≥1 branch-or-rerank decision; final readiness scoring.

## A11. Anti-endless-research guardrails (§11)

Stop researching when: new evidence repetitive; new findings don't change decision implications; unresolved items need human/internal data; Albert challenges already covered; readiness score plateaued; source quality not improving. COS must explicitly say: "I recommend stopping external research. Continuing adds appendix volume but not decision readiness. Remaining blockers are human/internal-data/decision dependent."

## A12. Readiness scoring (§12)

Four scores 0–5: `albert_challenge_readiness, decision_readiness, research_exhaustion_readiness, human_bottleneck_clarity` + `should_continue` + `reason`. **Target default:** all four ≥ 4.

## A13. Human interaction style (§13)

Avoid open-ended questions unless necessary. BAD: "What do you want to do next?" GOOD: present A/B/C options + recommendation + "Default if no response: …".

## A14. Deterministic vs LLM responsibilities (§14)

- **Deterministic / Python:** state schema, iteration count, branch id, node status, readiness-score storage, human-task status, checkpointing, stop-condition enforcement, review-gate routing, artifact validation, source-table format, audit log.
- **LLM:** issue expansion, Albert challenge generation, research synthesis, evidence interpretation, counterargument generation, meeting-ready wording, decision-implication explanation, human-task wording, next-step recommendation.

## A15. Architecture (§15) + research worker layer (§16)

- **Preferred:** Python, Pydantic models, LangGraph-style state machine, pluggable research workers, structured JSON outputs, Markdown summaries, CLI-first / minimal web UI. Do NOT start with full enterprise UI.
- **Research worker is replaceable:** stub (local testing) / GPT Researcher adapter / ODR-style worker / OpenAI Deep Research API adapter / internal RAG-search adapter / manual document ingestion adapter. Orchestrator must not depend on one engine.
- **Worker output schema:** `{query, claims:[{claim, source_refs[], confidence, notes}], sources:[{id, title, url, source_type(primary|secondary|marketing|blog|paper|internal), quality(high|medium|low)}], contradictions[], missing_evidence[], suggested_followups[]}`.

## A16. Core data models (§17, Pydantic)

`IssueNode, AlbertChallenge, HumanTask, ReadinessScore, ResearchState` per spec field lists (see A5/A9/A12). `ResearchState` fields: `original_question, meeting_context, target_audience="Albert / BU leadership", mode="interactive"|"auto", issue_map[], albert_challenge_map[], readiness_board{}, evidence[], human_tasks[], branches[], steering_events[], readiness_score, iteration_count, final_memo`. **(Our additions: `run_id`, `created_at`, `updated_at`; Enums for status/type fields; `EvidenceBundle`, `Source`, `Claim` typed.)**

## A17. Albert Thought Agent prompt contract (§20)

**Input:** original question; meeting context; current issue map; current challenge map; evidence summary; current draft answer (if any); readiness scores; recent research actions.
**Output JSON:** `{albert_challenges:[{challenge, why_albert_would_ask, severity, current_answer_strength(weak|medium|strong), missing_info[], recommended_probe}], weak_points[], premature_end_risk(low|med|high), research_drift_risk(low|med|high), missing_business_context[], questions_albert_would_ask_next[], recommended_next_action(continue_research|branch|rerank|pull_human|push_human|synthesize), rationale}`.

## A18. Output language (§21) + final memo (§22)

- **Default language: Chinese.** Source titles, citations, technical names, quotes may stay English. Meeting-ready wording in Chinese unless user requests otherwise.
- **Final memo (only when synthesis selected)** sections: `Executive Answer / Albert Challenge Map / What We Can Say Now / What We Cannot Say Yet / What Is Blocking Us / Required Human Decisions / Inputs / Evidence Summary / Risks and Assumptions / Recommended Next Action / Appendix`. Memo must explicitly state blocker type: research / internal data / permission / human judgment / BU preference / Albert decision.

## A19. MVP scope (§23)

**Must include:** CLI/simple local interface; ResearchState model; Dynamic Issue Map; Albert Challenge Map; Readiness Board; iterative loop; Albert Thought audit; human-task generation; readiness scoring; stop/continue decision logic; Chinese stage/iteration summary; final memo generation.
**Can stub:** research worker; source retrieval; internal-document access; UI; auth; database.
**Not yet:** full enterprise permission system; Slack/Teams; meeting-transcript ingestion; complex web dashboard; multi-BU memory; full DeerFlow-style platform.

## A20. Acceptance tests (§25) — the behavioral contract

1. **Premature-stop prevention:** no competitor research yet + Albert audit finds competitor-benchmark challenge → must NOT terminal-stop; continue/branch to competitor benchmark.
2. **Human blocker clarity:** research needs internal usage data → create HumanTask; continue adjacent public research; mark confidence limitation.
3. **Albert audit challenge generation:** draft says human-in-loop needed → Albert challenges include: why can't AI ask upfront then run overnight? which parts truly require humans? is HITL an excuse? what can be automated now?
4. **Endless-research prevention:** 3 iterations produce no new high-impact issues + sources repetitive + human blockers remain → recommend synthesis + human-task queue.
5. **Auto mode:** auto mode w/ max iterations → multiple iterations; Albert audit each iteration; readiness scores updated; final state explains stop reason.

---

# PART B — EXECUTION BACKBONE (how we build it, 6 phases)

**Philosophy (agreed):** every phase is the SAME end-to-end loop, runnable & independently verifiable, just progressively more real. No horizontal layers connecting only at the end.

```
P1 all-stub loop → P2 real Albert+LLM brains → P3 human+auto → P4 real workers → P5 synthesis/memo → P6 Albert epic+hardening
```

**Cross-cutting design decisions:** (1) Enums not bare str; (2) persistence/run_id/checkpoint from P1 ("Resume, Don't Rerun"); (3) Readiness Board derived; (4) stable brain interfaces from P1 (Researcher/Auditor/Scorer/DecisionMaker/Worker); (5) deterministic loop engine, LLM only in brains (§14); (6) **LLM mocking + injection hook (user directive 2026-06-01):** every LLM/external-skill brain sits behind a Protocol interface with a deterministic **mock** implementation (canned, used in P1 + all tests) and a runtime **injection hook** (e.g. `--llm mock|real`, factory/DI) so the real Claude Agent SDK brain and the external `skill-cn5-i-am-albert` plug into the SAME seam later without touching the loop. P1 ships mocks behind the hook; P2 swaps implementations at the hook only.

| # | Phase | Loop fidelity | Verifiable DoD | Source |
|---|-------|---------------|----------------|--------|
| **P1** | All-stub deterministic loop | Full loop runs; every brain a deterministic stub; zero LLM | `pytest` green; `cos run` iterates/updates/scores/decides/stops; **Test 1 + Test 4** | M1,M2,M3 / A7,A10,A11 |
| **P2** | Real Albert (EXTERNAL skill) + LLM brains | `albert_audit` node wired to **`skill-cn5-i-am-albert`** via adapter; other brains → Claude Agent SDK | Loop runs; **Test 3**; Albert contract (O-4) green; structured-output contract | M4 / A6.3,A17 |
| **P3** | Human pull/push + auto mode | + human interaction + overnight HITL | **Test 2 + Test 5** | M5,M6 / A8,A9 |
| **P4** | Real research workers | research node gets real data | real research in loop; adapter hot-swap | M7 / A15 |
| **P5** | Synthesis + final memo | terminal node produces deliverable | memo at readiness; §22 format | M8 / A18 |
| **P6** | Albert epic + hardening | polish + Albert deepened | richer Albert; e2e hardened | A6.3,§29 |

**P1 detail (next to fine-tune):** bootstrap (git init→GitHub, pyproject `cn5_research_cos`, deps pydantic v2/typer/rich/pytest, .gitignore, README); `models.py` (Enums + all A16 models); `store.py` (new_run/save/load, round-trip, `runs/<run_id>/state.json`); `artifacts/` (issue_map/challenge_map/readiness_board-derived); `loop.py` (deterministic FSM, all A7 nodes — **O-1 picks tech**); `agents/` stubs (rule-based expansion, stub researcher, **stub Albert auditor**, deterministic scorer, deterministic COS decision w/ A10+A11 guardrails); CLI (`cos init/run/show/validate`, Chinese iteration summary); tests (models, artifacts, board, persistence, **Test 1 + Test 4**, loop iteration). **DoD:** pytest green; `cos run` visibly loops + stops for right reason; committed + pushed (resolves "git 是空的").

(P2–P6 detail captured in Part A sections they implement; each gets its own detailed plan via writing-plans when fine-tuned.)

---

# PART C — Working protocol, open decisions, next step

**OPEN decisions:**
- **O-1 Orchestration tech (resolve in P1 fine-tune):** LangGraph FSM (wiki mandate, built-in checkpoint/resume; extra dep + Claude Agent SDK nested-session caveat #573) vs hand-rolled Python FSM + JSON checkpoint (*leaning, for P1 zero-LLM*) vs pure Claude Agent SDK loop.
- **O-2 Albert timing + sourcing:** RESOLVED — Albert is an **EXTERNAL skill** (`skill-cn5-i-am-albert`). P1 = stub Albert client (canned). P2 = wire the real call to the external skill + write the mapping/adapter + define the integration contract (do NOT author an Albert prompt in-repo). The Albert rubric/bones are owned in the external repo.
- **O-4 Albert integration contract (NEW, resolve in P2 fine-tune):** STATUS — `skill-cn5-i-am-albert` is **partial / in-progress, interface still changing**. Therefore the cockpit defines ITS OWN stable `Auditor` Protocol + adapter; the adapter absorbs the external skill's churn; we run a **mock Auditor** until the external skill stabilizes, then bind it at the injection hook (decision #6). **SCOPE BOUNDARY (user 2026-06-01):** building/finishing `skill-cn5-i-am-albert` is OUT OF SCOPE for this program — it is owned/built elsewhere; this cockpit only CONSUMES it. Open: how does the cockpit invoke `skill-cn5-i-am-albert` (Claude Agent SDK subagent? skill invocation? CLI?), what exact JSON does it pass (§20 input) and receive (rubric output), and how does the adapter map rubric output → `AlbertChallenge[]` + readiness deltas? This seam is registered as an integration contract (R17).
- **O-3 Skill packaging:** does this repo become an installed Claude Code skill? Resolve before P6.

**Working protocol:**
- **Discuss-before-spec (→ global hook):** before writing/editing ANY spec doc, pull user + sufficient discussion + explicit go-ahead, THEN write. Wire as `~/.claude/` PreToolUse hard gate + feedback memory once out of plan mode. (User directive 2026-06-01.)
- **Per-phase cycle:** fine-tune skeleton w/ user → detailed spec (`docs/superpowers/specs/`) → user approves → writing-plans detailed plan (`docs/superpowers/plans/`) → subagent-driven-development → verify DoD → commit/push → next phase.
- **Repartition freely;** re-read this file every new round.

**Immediate next step — BATCH 0 (persistence/保命 only, NO P1 code), user-approved 2026-06-01:**
1. `git init` cockpit repo at `D:\D-claude\skill-cn5-research-cos\`, add remote → `github.com/oxydavid-maxx/skill-cn5-research-cos`, branch `main`.
2. Save into repo: user's verbatim §0–30 spec → `docs/spec/PRODUCT-SPEC.md`; this master backbone → `docs/superpowers/plans/2026-06-01-master-backbone.md`; an Albert-integration reference note (external skill `skill-cn5-i-am-albert`, consumed not built) → `docs/spec/albert-integration.md`; `.gitignore` (Python) + minimal `README.md`.
3. Commit + push to GitHub (resolves "git 是空的").
4. Wire global **discuss-before-spec** guard: `~/.claude/feedback_discuss_before_spec.md` + MEMORY pointer (+ gate rule) — auto-commits via existing `~/.claude` hook.
**NOT in BATCH 0:** any P1 code, models, loop, CLI. P1 build waits for the Ultraplan-refined plan to return + P1 fine-tune.
**Then later:** merge Ultraplan refinements; fine-tune P1 (resolve O-1, lock scope); P1 detailed spec for approval.
