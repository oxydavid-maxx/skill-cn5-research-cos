# Chief-of-Staff Research Agent / BU Research Cockpit

> **Authoritative product specification — verbatim capture of the user-provided spec (Sections 0–30).**
> This is the ultimate source of truth for `skill-cn5-research-cos`. Captured 2026-06-01.
> Re-definition: *a continuous, iterative, audit-driven Chief-of-Staff Research Agent* — not a one-shot deep research bot, not a 2–3 shot pipeline.

---

## 0. Project Name

暫定：`bu-research-cockpit` (also: `chief-of-staff-research-agent`). Repo: `skill-cn5-research-cos`; package `cn5_research_cos`; CLI `cos`.

## 1. Product Goal

Build a BU-specific, continuously iterative research assistant that helps a strategy / PM / BU support person prepare for difficult meeting questions from Albert or BU leadership.

The system should not simply perform deep research once and generate a long report. It should continuously:

1. Expand the problem space
2. Maintain a Dynamic Issue Map
3. Research high-value branches
4. Audit its own research from Albert's perspective
5. Update challenge/readiness artifacts
6. Decide whether to continue, branch, re-rank, pull human, push human, or synthesize
7. Stop only when readiness criteria are met or remaining blockers are clearly human / internal-data / decision dependent

The system should behave like a strong chief-of-staff, not a passive assistant.

## 2. Core Philosophy

This project is not a linear workflow (Intake → Research → Summary → Memo). The correct mental model is a convergence loop:

```
Current Issue Map
→ AI research
→ Albert-style audit
→ multi-agent critique
→ artifact update
→ readiness scoring
→ continue / branch / re-rank / pull human / push human / synthesize
→ repeat until readiness target is reached
```

The final memo is not the product. The evolving research state is the product.

## 3. Main User

Primary user for MVP: Strategy staff / PM / meeting support person. This person uses the tool after a meeting or during preparation to answer questions that Albert / BU leadership may challenge.

Not primary MVP users: Albert directly; general employees; fully autonomous enterprise agent platform; generic research chatbot users.

## 4. Success Criteria

The system is successful when it can help the user reach these four readiness states.

### 4.1 Albert Challenge Readiness
Albert's likely challenges are mostly surfaced, organized, and assigned a status. Each challenge categorized as: Answered / Partially answered / Needs external research / Needs internal data / Needs BU judgment / Needs Albert decision / Needs source validation / Blocked. The goal is not that every challenge has a perfect answer; the goal is that the team knows what can be answered, what cannot, and why.

### 4.2 Decision Readiness
The research should support an actual BU decision. For every major finding, ask: Does this change the decision? Does it support doing it, not doing it, delaying it, piloting it, or asking for more data? What decision criterion is being used? Is the criterion explicit or assumed? If the research does not improve decision quality, the system should say so.

### 4.3 Research Exhaustion Readiness
The system should not stop prematurely. It can stop external research only when: major high-value branches have been explored; new sources are mostly repetitive; no new high-impact meta-question is found by the Albert auditor; continuing research would not materially change the decision; unresolved items are mostly internal data, human judgment, or decision blockers.

### 4.4 Human Bottleneck Clarity
The system should clearly identify when the blocker is no longer research. Examples: need competitor datasheet from a login-protected portal; need BU owner to provide internal usage data; need Albert to choose the decision criterion; need domain owner to validate an assumption; need human judgment on source credibility. The system must convert vague "we need more research" into specific human tasks.

## 5. Key Artifacts

The system maintains three living artifacts, continuously updated across iterations.

### 5.1 Dynamic Issue Map
Purpose: Exploration / Unknown unknown discovery / Problem-space expansion. The primary artifact for understanding the research space.

Each issue node should include:
`id, parent_id, title, description, issue_type, status, impact, confidence, evidence_refs, unknowns, counterarguments, human_blockers, next_actions, last_updated, last_audited`.

Possible issue types: `root_question, intent, technical_feasibility, roi, cost, competitor, risk, internal_data, human_judgment, decision_criterion, source_conflict, unknown_unknown`.

Status values: `open, researching, partially_answered, answered, blocked_by_human, blocked_by_internal_data, blocked_by_permission, blocked_by_decision, low_confidence, ready_for_synthesis`.

### 5.2 Albert Challenge Map
Purpose: Defense / Meeting preparation / Leadership challenge simulation. Answers: What would Albert challenge? Can we answer it? If not, why not?

Each challenge should include:
`challenge, why_albert_would_ask, current_answer, status, confidence, evidence_refs, missing_info, blocking_owner, next_action, meeting_ready_response`.

This artifact is also the main output of the Albert Thought Agent.

### 5.3 Research Readiness Board
Purpose: Project management / Progress tracking / Stop-continue decisions.

Board columns: `Answered, Partially Answered, Needs External Research, Needs Internal Data, Needs BU Judgment, Needs Albert Decision, Needs Source Validation, Blocked, Ready for Memo`.

Each board item should link back to Issue Map nodes and Albert Challenge Map entries.

## 6. Agent Roles

The system should use multiple roles but avoid unnecessary agent theater. Agents are functional roles.

### 6.1 Chief-of-Staff Agent
The main orchestrator. Responsibilities: maintain overall research direction; decide whether to continue, branch, re-rank, pull human, push human, or synthesize; push back against bad human direction; prevent premature closure; prevent endless research; translate research state into actionable next steps; enforce readiness criteria.

Behavior: Strong, direct, decision-oriented. Does not flatter user. Does not hide uncertainty. Does not produce long reports to mask weak evidence.

Example behavior:
> I do not recommend continuing technical feasibility research. The current blocker is not feasibility; it is ROI and competitor benchmark. Continuing technical research will increase appendix length but not improve decision readiness. Recommended next move: re-rank toward cost impact and competitor evidence.

### 6.2 Researcher Agent
Responsibilities: research a specific issue branch; gather sources; extract claims; track citations; identify missing evidence; return structured evidence bundles. Researcher should not decide whether the whole project is done.

### 6.3 Albert Thought Agent
A first-class module. It may later become a separate project / independent issue.

Purpose: Audit the research from Albert's perspective. Simulate how Albert would challenge the current answer. Detect weak reasoning, premature closure, missing business framing, and unexplored challenge angles. This replaces the generic audit agent. The audit loop should not be generic QA; it should think like Albert.

Responsibilities: read the current Issue Map, Evidence Map, Stage Summary, and draft answer; ask "If I were Albert, what would I challenge?"; identify whether the current answer would survive a leadership meeting; detect vague claims, weak evidence, missing ROI, missing competitor comparison, missing owner, missing decision criterion; detect whether AI is using research volume to hide lack of decision clarity; generate Albert-style challenge questions; recommend whether to continue research, pull human, push human, or synthesize.

Albert Thought Agent outputs: `albert_challenges, weak_points, missing_business_context, missing_evidence, questions_albert_would_ask, premature_end_risk, research_drift_risk, recommended_next_probe, readiness_score_delta`.

Important: Albert Thought Agent should be skeptical but useful. It should not simply be negative. It should help the Chief-of-Staff Agent decide what to do next.

Example Albert audit:
> Current answer says "AI can do overnight research, but human steering is needed."
> Albert would challenge:
> 1. Why can't AI ask clarifying questions upfront and then run overnight?
> 2. What exactly requires human judgment?
> 3. Is this just an excuse to keep humans in the loop?
> 4. Which parts can be automated now?
> 5. What would a mature SOTA product do?
> 6. If the bottleneck is human, why build this at all?
> Weakness: The current answer explains why steering matters, but does not yet quantify what can be automated vs what requires BU judgment.
> Recommended next probe: Research existing autonomous deep research systems with HITL checkpoints and compare what they automate vs what they still require humans to decide.

### 6.4 Skeptic / Counterargument Agent
Responsibilities: find alternative explanations; challenge the current conclusion; search for evidence against the emerging answer; identify cases where the answer may be overfit to the user's existing belief. Not Albert-specific; challenges from a general reasoning perspective.

### 6.5 Source Critic Agent
Responsibilities: evaluate source quality; detect SEO / marketing / low-quality sources; flag unsupported claims; compare primary vs secondary sources; track source confidence.

### 6.6 Synthesis Agent
Responsibilities: update artifacts; produce concise summaries; convert evidence into executive language; maintain Chinese output format; generate meeting-ready wording.

## 7. Core Loop

The system should run iterative cycles. Each cycle has this shape:

1. Select highest-value issue branch
2. Research branch or re-rank existing evidence
3. Normalize findings into evidence bundles
4. Update Dynamic Issue Map
5. Run Albert Thought Agent audit
6. Run source / counterargument critique if needed
7. Update Albert Challenge Map
8. Update Research Readiness Board
9. Score readiness
10. Decide next action

Possible next actions: `continue_research, branch, rerank, pull_human, push_human, synthesize, pause, terminal_stop`.

## 8. Auto Mode

The system must support an overnight-style auto mode. Auto mode does not mean fully reckless autonomy. It means: after enough initial clarification, the system can run multiple research/audit/update cycles without constant human input.

### 8.1 Auto Mode Pre-flight
Before entering auto mode, system must ensure it has: `original_question, meeting_context, target_audience, likely_albert_concern, output_purpose, known_constraints, forbidden_directions, available_sources, internal_documents_available_or_not, default_research_priority, fallback_behavior_if_human_unavailable`.

If these are missing, ask only the minimal high-leverage questions. Do not ask a long questionnaire. Use chief-of-staff style:
> I can run overnight, but two settings will materially change the direction:
> 1. Should I optimize for decision readiness or meeting defense?
> 2. If competitor/internal documents are inaccessible, should I mark them as blockers while continuing with public substitutes?
> Default recommendation: Optimize for meeting defense + decision readiness; continue with public substitutes while explicitly tracking blockers.

### 8.2 Auto Mode Allowed Actions
broad issue expansion; branch research; counterargument search; source quality review; Albert audit iteration; readiness scoring; artifact updates; draft synthesis; generate human task queue; continue non-blocked branches.

### 8.3 Auto Mode Forbidden Actions
pretend to have internal data it does not have; decide BU preference by itself; decide Albert's final decision criterion by itself; convert low-confidence public claims into strong conclusions; terminal-stop while high-impact ambiguity remains unresolved; hide blockers in prose.

### 8.4 Auto Mode Blocker Handling
- **Soft blocker** (a source is incomplete or one claim lacks a second source): mark confidence lower, find substitutes, continue.
- **Medium blocker** (competitor datasheet requires login; internal usage data unavailable; sources conflict): create human task, continue adjacent research branches.
- **Hard blocker** (decision criterion unknown and all high-value paths depend on it; all core evidence requires internal data; public data cannot support a meaningful conclusion): call help; pause main loop; produce minimum human input request.

Help call format:
> I need the following inputs to continue effectively:
> 1. Decision criterion: A. cost saving / B. competitive pressure / C. technical feasibility / D. risk reduction
> 2. Missing data: Please provide usage data or confirm it is unavailable.
> If no response, I will continue with default A+B and mark confidence as medium-low.

## 9. Stop Conditions

The system should distinguish four types of stopping.

### 9.1 Stop to Pull Human (not terminal)
Trigger when: multiple high-impact intents exist and AI cannot safely choose; next research budget has major tradeoff; BU preference is required; decision criterion is required; research direction may be drifting; Albert Thought Agent finds a challenge that needs human judgment.

Pull human format: `Context / Why I am asking / Options / AI recommendation / Impact of each option / Default if no response`.

### 9.2 Stop to Push Human (creates a human task)
Trigger when: need internal data; need access to restricted document; need competitor datasheet from portal; need source validation; need domain owner assumption validation; need Albert/BU decision criterion.

Push human task format: `task_title, owner, requested_input, why_needed, blocking_question, priority, can_continue_without_it, fallback_plan`.

### 9.3 Stop Research, Continue Synthesis
Trigger when: new sources repeat existing claims; Albert Thought Agent has no new high-impact challenge; Challenge Map is mostly classified; unresolved items are human/data/decision blockers; continuing research will not materially change decision.

Behavior: stop external research; move into synthesis; produce executive answer, readiness board, blockers, and appendix.

### 9.4 Terminal Stop
Allowed only when these are met: Albert Challenge Readiness ≥ target; Decision Readiness ≥ target; Research Exhaustion Readiness ≥ target; Human Bottleneck Clarity ≥ target.

Or: all unresolved high-impact questions are clearly assigned to human tasks, internal data tasks, or decision tasks, and AI has no high-value external research branch left.

## 10. Anti-Premature-End Guardrails

The system cannot terminal stop unless it has completed:
1. Broad issue expansion
2. Albert Thought Agent audit
3. Counterargument pass
4. Source confidence check
5. Pending question extraction
6. Human/data/decision blocker classification
7. At least one explicit explanation of why continuing research would or would not help

For auto mode, additionally require: more than one research/audit cycle; at least one adversarial challenge cycle; at least one branch or re-rank decision; final readiness scoring.

## 11. Anti-Endless-Research Guardrails

The system should stop researching when: new evidence is repetitive; new findings do not change decision implications; unresolved items require human/internal data; Albert Thought Agent challenges are already covered; readiness score has plateaued; source quality is not improving.

Chief-of-Staff Agent should explicitly say:
> I recommend stopping external research. Continuing will add appendix volume but not improve decision readiness. The remaining blockers are human/internal-data/decision dependent.

## 12. Readiness Scoring

Maintain four scores from 0 to 5: `albert_challenge_readiness, decision_readiness, research_exhaustion_readiness, human_bottleneck_clarity`.

Example:
```json
{
  "albert_challenge_readiness": 4,
  "decision_readiness": 3,
  "research_exhaustion_readiness": 2,
  "human_bottleneck_clarity": 4,
  "should_continue": true,
  "reason": "Challenge space is mostly mapped, but decision implications and research exhaustion are not mature enough."
}
```

Target default: all four ≥ 4.

## 13. Human Interaction Style

The assistant should not ask open-ended questions unless absolutely necessary.

Bad: "What do you want to do next?"

Good:
> I see three possible next moves:
> A. Continue feasibility research
> B. Re-rank toward ROI and competitor benchmark
> C. Pause external research and request internal usage data
> Recommendation: Choose B now, and create a push-human task for C.
> Default if no response: Proceed with B.

## 14. Deterministic vs LLM Responsibilities

**Deterministic / Python-controlled** (not left to the LLM): state schema; iteration count; branch id; node status; readiness score storage; human task status; checkpointing; stop condition enforcement; review gate routing; artifact validation; source table format; audit log.

**LLM-controlled:** issue expansion; Albert challenge generation; research synthesis; evidence interpretation; counterargument generation; meeting-ready wording; decision implication explanation; human task wording; next-step recommendation.

## 15. Suggested Technical Architecture

Preferred: Python; Pydantic models; LangGraph-style state machine; pluggable research workers; structured JSON outputs; Markdown rendering for summaries; CLI-first or minimal web UI for MVP. Do not start with a full enterprise UI.

## 16. Research Worker Layer

Research worker should be replaceable. Possible implementations: stub researcher for local testing; GPT Researcher adapter; ODR-style worker; OpenAI Deep Research API adapter; internal RAG/search adapter; manual document ingestion adapter. The orchestrator should not depend on one research engine.

Research worker output schema:
```json
{
  "query": "...",
  "claims": [{ "claim": "...", "source_refs": ["..."], "confidence": "medium", "notes": "..." }],
  "sources": [{ "id": "...", "title": "...", "url": "...", "source_type": "primary|secondary|marketing|blog|paper|internal", "quality": "high|medium|low" }],
  "contradictions": [],
  "missing_evidence": [],
  "suggested_followups": []
}
```

## 17. Core Data Models

Use Pydantic.

```python
class IssueNode(BaseModel):
    id: str
    parent_id: str | None = None
    title: str
    description: str
    issue_type: str
    status: str
    impact: int
    confidence: int
    evidence_refs: list[str] = []
    unknowns: list[str] = []
    counterarguments: list[str] = []
    human_blockers: list[str] = []
    next_actions: list[str] = []
    last_updated: str | None = None
    last_audited: str | None = None


class AlbertChallenge(BaseModel):
    id: str
    challenge: str
    why_albert_would_ask: str
    current_answer: str | None = None
    status: str
    confidence: int
    evidence_refs: list[str] = []
    missing_info: list[str] = []
    blocking_owner: str | None = None
    next_action: str | None = None
    meeting_ready_response: str | None = None


class HumanTask(BaseModel):
    id: str
    task_title: str
    owner: str | None = None
    requested_input: str
    why_needed: str
    blocking_question: str
    priority: str
    can_continue_without_it: bool
    fallback_plan: str
    status: str = "open"


class ReadinessScore(BaseModel):
    albert_challenge_readiness: int
    decision_readiness: int
    research_exhaustion_readiness: int
    human_bottleneck_clarity: int
    should_continue: bool
    reason: str


class ResearchState(BaseModel):
    original_question: str
    meeting_context: str | None = None
    target_audience: str = "Albert / BU leadership"
    mode: str = "interactive"  # interactive | auto
    issue_map: list[IssueNode] = []
    albert_challenge_map: list[AlbertChallenge] = []
    readiness_board: dict[str, list[str]] = {}
    evidence: list[dict] = []
    human_tasks: list[HumanTask] = []
    branches: list[dict] = []
    steering_events: list[dict] = []
    readiness_score: ReadinessScore | None = None
    iteration_count: int = 0
    final_memo: str | None = None
```

## 18. Main Graph Nodes

Initial MVP graph nodes: `intake_node, issue_expansion_node, research_planning_node, research_worker_node, evidence_normalizer_node, albert_thought_audit_node, counterargument_node, source_critic_node, artifact_update_node, readiness_scoring_node, chief_of_staff_decision_node, human_pull_node, human_push_node, synthesis_node, terminal_node`.

Important: The graph should loop. It should not run once and stop.

## 19. Chief-of-Staff Decision Logic

The decision node should output one of: `continue_research, branch, rerank, pull_human, push_human, synthesize, pause, terminal_stop`.

Decision output schema:
```json
{
  "decision": "continue_research",
  "reason": "...",
  "selected_issue_ids": ["..."],
  "recommended_next_queries": ["..."],
  "human_message": "...",
  "default_action_if_no_response": "..."
}
```

## 20. Albert Thought Agent Prompt Contract

The Albert Thought Agent should receive: original question; meeting context; current issue map; current challenge map; evidence summary; current draft answer if any; readiness scores; recent research actions.

It should output structured JSON:
```json
{
  "albert_challenges": [
    { "challenge": "...", "why_albert_would_ask": "...", "severity": "high", "current_answer_strength": "weak|medium|strong", "missing_info": ["..."], "recommended_probe": "..." }
  ],
  "weak_points": ["..."],
  "premature_end_risk": "low|medium|high",
  "research_drift_risk": "low|medium|high",
  "missing_business_context": ["..."],
  "questions_albert_would_ask_next": ["..."],
  "recommended_next_action": "continue_research|branch|rerank|pull_human|push_human|synthesize",
  "rationale": "..."
}
```

## 21. Output Language

Default output language: Chinese. However, source titles, citations, technical names, and quotes may remain English. Meeting-ready wording should be in Chinese unless user requests otherwise.

## 22. Final Memo Format

Only generate final memo when synthesis is selected. Structure:
```
# Executive Answer
# Albert Challenge Map
# What We Can Say Now
# What We Cannot Say Yet
# What Is Blocking Us
# Required Human Decisions / Inputs
# Evidence Summary
# Risks and Assumptions
# Recommended Next Action
# Appendix
```
The memo must explicitly say whether the blocker is: research / internal data / permission / human judgment / BU preference / Albert decision.

## 23. MVP Scope

**MVP must include:** CLI or simple local interface; ResearchState model; Dynamic Issue Map; Albert Challenge Map; Research Readiness Board; iterative loop; Albert Thought Agent audit; human task generation; readiness scoring; stop/continue decision logic; Chinese stage / iteration summary; final memo generation.

**MVP can use stubs for:** research worker; source retrieval; internal document access; UI; authentication; database.

**MVP should not include yet:** full enterprise permission system; Slack / Teams integration; meeting transcript ingestion; complex web dashboard; multi-BU memory; full DeerFlow-style agent platform.

## 24. Milestone Plan

- **M1 Project skeleton:** pyproject.toml, README.md, src/, tests/, examples/. Add Pydantic, Typer/Click, Rich, pytest. Optional later: LangGraph, FastAPI, SQLite/Postgres.
- **M2 State and artifacts:** ResearchState, IssueNode, AlbertChallenge, HumanTask, ReadinessScore, EvidenceBundle. Tests for serialization and validation.
- **M3 Manual loop prototype:** CLI `bu-research start --question "..."`. Prototype loop (issue expansion, fake research worker, Albert audit, artifact update, readiness scoring, decision). No real web research yet.
- **M4 Albert Thought Agent:** prompt-based Albert audit module. Input: current state. Output: Albert challenges, weaknesses, recommended next probes, premature end risk. Test fixtures.
- **M5 Human pull / push:** pull request generator; push human task generator; task board; default action if no human response.
- **M6 Auto mode:** `bu-research run-auto --question "..." --max-iterations 8`. Loop multiple times; run Albert audit each time; avoid premature stop; stop on readiness or hard blocker; print iteration summaries.
- **M7 Research worker adapters:** first adapter as stub; then one real adapter (GPT Researcher or ODR-style). Keep interface stable.
- **M8 Synthesis:** generate final memo only after readiness or explicit user command.

## 25. Acceptance Tests

- **Test 1 — Premature stop prevention:** Given a question with no competitor research yet + Albert audit finds competitor benchmark challenge → System must not terminal stop; it should continue research or branch to competitor benchmark.
- **Test 2 — Human blocker clarity:** Given research requires internal usage data → System creates HumanTask; continues adjacent public research if possible; marks confidence limitation.
- **Test 3 — Albert audit challenge generation:** Given draft answer says human-in-loop is needed → Expected Albert challenges: Why can't AI ask questions upfront and run overnight? Which parts truly require humans? Is human-in-loop an excuse? What can be automated now?
- **Test 4 — Endless research prevention:** Given three iterations produce no new high-impact issues + sources repetitive + human blockers remain → System recommends synthesis and human task queue.
- **Test 5 — Auto mode:** Given auto mode with max iterations → multiple iterations; Albert audit each iteration; readiness scores updated; final state explains stop reason.

## 26. Claude Code Instructions

When implementing, do not build a simple one-shot research script. Build a loop-based research state machine. Implementation priorities: (1) State model correctness; (2) Artifact update loop; (3) Albert Thought Agent; (4) Readiness scoring; (5) Human task generation; (6) Auto mode iteration; (7) Research worker plug-in. Avoid overbuilding UI. Use clear, testable modules.

## 27. Initial Repo Structure

```
bu-research-cockpit/
├── README.md
├── pyproject.toml
├── examples/
│   └── albert_ai_research_question.yaml
├── src/
│   └── bu_research/
│       ├── __init__.py
│       ├── models.py
│       ├── cli.py
│       ├── state.py
│       ├── loop.py
│       ├── agents/
│       │   ├── chief_of_staff.py
│       │   ├── albert_thought.py
│       │   ├── researcher.py
│       │   ├── skeptic.py
│       │   ├── source_critic.py
│       │   └── synthesis.py
│       ├── workers/
│       │   ├── base.py
│       │   ├── stub_worker.py
│       │   └── gpt_researcher_worker.py
│       ├── artifacts/
│       │   ├── issue_map.py
│       │   ├── challenge_map.py
│       │   └── readiness_board.py
│       ├── prompts/
│       │   ├── albert_thought.md
│       │   ├── chief_of_staff.md
│       │   ├── issue_expansion.md
│       │   └── synthesis.md
│       └── render/
│           └── markdown.py
└── tests/
    ├── test_models.py
    ├── test_loop.py
    ├── test_albert_thought.py
    └── test_stop_conditions.py
```

> **Note (2026-06-01):** actual package will be `cn5_research_cos` (not `bu_research`); `albert_thought` agent becomes a CLIENT/ADAPTER to the EXTERNAL skill `skill-cn5-i-am-albert` (see `albert-integration.md` / master backbone), not an in-repo prompt.

## 28. First Claude Code Task

> Create a Python project named bu-research-cockpit. Implement the core data models and a CLI-driven iterative loop for a Chief-of-Staff Research Agent. The system should not be a one-shot research bot. It should maintain: (1) Dynamic Issue Map; (2) Albert Challenge Map; (3) Research Readiness Board; (4) Human Task Queue; (5) Readiness Scores. Implement a stub research worker first. Implement an Albert Thought Agent as an audit module that simulates Albert's likely challenges. Implement deterministic stop/continue decision logic based on readiness scores and blocker classification. Do not build a complex UI. Do not integrate real web search yet. Focus on state, iteration, audit, and artifact updates. Add tests for: premature stop prevention; human blocker task generation; Albert challenge generation; endless research prevention; auto mode iteration.

## 29. Important Design Note

Albert Thought Agent should be tracked as a separate epic: **Albert Thought Agent / Leadership Challenge Simulator**. Future versions may use: historical Albert questions; meeting notes; stated preferences; common challenge patterns; BU-specific decision style. But MVP should use a prompt-defined Albert simulator, not personalized training.

> **Update (2026-06-01):** this epic is realized as the SEPARATE repo/skill `skill-cn5-i-am-albert`, built/owned elsewhere; this cockpit consumes it.

## 30. Final Product Definition

The product is: *A continuous, audit-driven, human-steered research cockpit that behaves like a strong chief-of-staff. It repeatedly researches, audits, challenges, updates artifacts, and decides whether to continue, branch, re-rank, pull human, push human, or synthesize. Its goal is not to produce a long report. Its goal is to make the team ready for Albert-level challenge and decision-making.*
