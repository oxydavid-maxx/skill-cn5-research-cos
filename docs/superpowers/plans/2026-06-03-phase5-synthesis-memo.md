# Phase 5 — Synthesis + §22 Decision-Memo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the terminal node produces a gated §22 decision-memo, wiring in the P4b citation modules (built but unwired) and web source-text excerpt capture.

**Architecture:** an LLM `Synthesizer` brain writes per-section prose; deterministic Python owns the section SET, blocker labeling, citation wiring (P4b `citation/verify|policy|flatten`), and the four emission gates + H6. Mirrors the existing brain/Protocol/stub/`build_brains` pattern.

**Tech Stack:** Python 3.11, Pydantic v2, LangGraph, Claude Agent SDK (`call_structured`, model=`haiku`), Typer, pytest. `py -3` on Windows.

**Spec:** `docs/spec/2026-06-03-phase5-synthesis-memo-design.md`. **Read these existing files before starting:** `models.py` (`AlbertChallenge`/`albert_challenge_map`, `EvidenceBundle`, `Claim`, `Source`, `ResearchState`, `ReadinessScore`), `brains/interfaces.py` (Protocols), `brains/real.py` (`RealResearcher` schema + `RealSynthesizer`-less today), `brains/stubs.py` (`build_brains`), `citation/verify.py` + `citation/policy.py` (P4b, already built — `verify`, `gate_emission`/policy fns, `flatten_to_primary`), `decision/convergence.py` (`gate_emission`), `graph.py` (terminal/synthesize node + `node_readiness_scoring` + the H6 `human_review` gate from P3), `llm/metrics.py` (`RunMetrics.summary_line`), `cli.py` (`run`/`run_auto_cmd`).

**Invariant:** P1–P4b (265 tests) STAY GREEN after every task. Run `py -3 -m pytest -q` at each task end. Deterministic tests mock the LLM; live tests opt-in via `CN5_COS_LLM_TESTS=1`.

---

### Task 1: Memo data models + Source excerpt field

**Files:**
- Modify: `src/cn5_research_cos/models.py`
- Test: `tests/test_memo_models.py`

- [ ] **Step 1: Write the failing test** (`tests/test_memo_models.py`)
```python
from cn5_research_cos.models import Memo, MemoSection, BlockerType, Source

def test_blocker_type_has_six_kinds():
    vals = {b.value for b in BlockerType}
    assert vals == {"research", "internal_data", "permission",
                    "human_judgment", "bu_preference", "albert_decision"}

def test_memo_has_nine_sections_by_key():
    m = Memo(sections=[MemoSection(key="executive_answer", title="...", body="x")])
    assert m.sections[0].key == "executive_answer"
    assert m.section_keys() == ["executive_answer"]

def test_source_carries_excerpt_default_empty():
    s = Source(id="S-1", title="t", url="u", origin="web")
    assert s.excerpt == ""
```

- [ ] **Step 2: Run to verify it fails** — `py -3 -m pytest tests/test_memo_models.py -v` → FAIL (Memo/MemoSection/BlockerType undefined).

- [ ] **Step 3: Implement** in `models.py` (place near `AuditResult`):
```python
class BlockerType(str, Enum):
    research = "research"
    internal_data = "internal_data"
    permission = "permission"
    human_judgment = "human_judgment"
    bu_preference = "bu_preference"
    albert_decision = "albert_decision"

class MemoSection(BaseModel):
    key: str
    title: str
    body: str = ""

class Memo(BaseModel):
    sections: list[MemoSection] = Field(default_factory=list)
    emitted: bool = False
    refused_reason: str | None = None
    def section_keys(self) -> list[str]:
        return [s.key for s in self.sections]
```
Add to `Source` (find the class): `excerpt: str = ""  # web: surrounding text for verbatim verify; internal: paperwork fragment quote`.

- [ ] **Step 4: Run** — `py -3 -m pytest tests/test_memo_models.py -v` → PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(p5): memo models + Source.excerpt"`

---

### Task 2: Web source-text excerpt capture (unblocks web citation verify)

**Files:**
- Modify: `src/cn5_research_cos/brains/real.py` (`RealResearcher` schema + `_build_bundle`)
- Test: `tests/test_researcher_excerpt.py`

- [ ] **Step 1: Write the failing test** — mock `call_structured` to return a source carrying an `excerpt`; assert the built `EvidenceBundle`'s web `Source.excerpt` is populated and equals what `citation/verify` will read.
```python
from cn5_research_cos.brains.real import RealResearcher
from cn5_research_cos.models import ResearchState
from cn5_research_cos.brains import real as realmod

def test_web_source_carries_excerpt(monkeypatch):
    def fake(system, user, schema, **kw):
        return {"sources": [{"title": "t", "url": "http://x", "role": "secondary",
                             "excerpt": "The controller assigns a dynamic address."}],
                "claims": [{"text": "DAA assigns addresses", "source_ids": ["1"],
                            "quote": "assigns a dynamic address"}]}
    monkeypatch.setattr(realmod, "call_structured", fake)
    rs = ResearchState(run_id="r", original_question="q")
    # ... add an issue, call research, assert bundle.sources[0].excerpt non-empty + origin == "web"
```

- [ ] **Step 2: Run** → FAIL (schema has no excerpt; Source.excerpt empty).
- [ ] **Step 3: Implement** — in `RealResearcher`'s structured-output schema add `excerpt` to each source object (a relevant snippet, ~1-3 sentences around the quote, NOT the full page); in `_build_bundle` map `src["excerpt"]` → `Source(excerpt=..., origin="web")`. Keep the prompt instruction: "for each source include a short verbatim `excerpt` (the sentence(s) containing your quote)."
- [ ] **Step 4: Run** → PASS. Then `py -3 -m pytest -q` (full suite green).
- [ ] **Step 5: Commit** — `git commit -m "feat(p5): web researcher captures source excerpt for citation verify"`

---

### Task 3: Blocker type labeling (deterministic, 6 kinds)

**Files:**
- Create: `src/cn5_research_cos/synthesis/__init__.py`, `src/cn5_research_cos/synthesis/blockers.py`
- Test: `tests/test_blocker_labeling.py`

- [ ] **Step 1: Write the failing test** — hand-built states map to each of the 6 `BlockerType`s:
```python
from cn5_research_cos.synthesis.blockers import label_blockers
from cn5_research_cos.models import BlockerType
# issue blocked_by_internal_data -> internal_data; blocked_by_permission -> permission;
# blocked_by_human -> human_judgment; an albert challenge needs_bu_judgment -> bu_preference;
# needs_albert_decision -> albert_decision; an unaddressed open issue -> research.
def test_labels_all_six_kinds(...):
    labels = label_blockers(state)
    assert {l.blocker_type for l in labels} >= {BlockerType.internal_data, BlockerType.research, ...}
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `label_blockers(state) -> list[Blocker]` (pure): map `IssueStatus.blocked_by_*` → the matching `BlockerType`; map open `AlbertChallenge.status` (`needs_bu_judgment`→`bu_preference`, `needs_albert_decision`→`albert_decision`, `needs_internal_data`→`internal_data`) ; remaining open high-impact issues → `research`. Reuse the existing `IssueStatus`/`ChallengeStatus` enums. No LLM.
- [ ] **Step 4: Run** → PASS; `py -3 -m pytest -q` green.
- [ ] **Step 5: Commit** — `git commit -m "feat(p5): deterministic 6-kind blocker labeling"`

---

### Task 4: Synthesizer Protocol + mock stub + RealSynthesizer

**Files:**
- Modify: `src/cn5_research_cos/brains/interfaces.py` (add `Synthesizer` Protocol), `src/cn5_research_cos/brains/stubs.py` (mock + `build_brains` wiring)
- Create: `src/cn5_research_cos/brains/synthesis.py` (`RealSynthesizer`)
- Test: `tests/test_synthesizer.py`

- [ ] **Step 1: Write the failing test** — `build_brains(llm="mock")` exposes `.synthesizer`; the mock returns a deterministic per-section body dict; `RealSynthesizer` (mock `call_structured`) returns prose keyed by the 9 section keys.
```python
def test_build_brains_exposes_synthesizer():
    b = build_brains(llm="mock")
    out = b.synthesizer.write_sections(state)  # -> dict[str, str] keyed by section key
    assert "executive_answer" in out
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — `Synthesizer` Protocol: `write_sections(state: ResearchState) -> dict[str, str]` (section key → prose). Mirror the existing brain pattern (see `RealCompressor`/`RealScorer` in `brains/real.py` for `call_structured` + schema usage). `RealSynthesizer.write_sections` makes ONE `call_structured` (model=`haiku`) with a schema whose properties are the 9 section keys (executive_answer, albert_challenge_map, can_cannot_say, blocking, required_human_decisions, evidence_summary, risks_assumptions, recommended_next_action, appendix), instructed to write Chinese meeting-ready prose grounded in the state's evidence/challenges. Mock stub returns a fixed dict with all 9 keys. Wire `.synthesizer` into `build_brains` for both `mock` and `real`.
- [ ] **Step 4: Run** → PASS; `py -3 -m pytest -q` green.
- [ ] **Step 5: Commit** — `git commit -m "feat(p5): Synthesizer protocol + mock + RealSynthesizer"`

---

### Task 5: Deterministic memo assembly (9 sections + blocker labels)

**Files:**
- Create: `src/cn5_research_cos/synthesis/memo.py`
- Test: `tests/test_memo_assembly.py`

- [ ] **Step 1: Write the failing test** — `assemble_memo(state, synthesizer)` returns a `Memo` with EXACTLY the 9 section keys in order; §4 (`blocking`) carries `label_blockers` output; §2 (`albert_challenge_map`) reflects `albert_challenge_map` statuses.
```python
from cn5_research_cos.synthesis.memo import assemble_memo, NINE_SECTION_KEYS
def test_memo_has_nine_sections_in_order(...):
    memo = assemble_memo(state, synthesizer)
    assert memo.section_keys() == NINE_SECTION_KEYS
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `NINE_SECTION_KEYS = [...]` (the 9 keys from Task 4) and `assemble_memo(state, synthesizer) -> Memo`: call `synthesizer.write_sections(state)`, build a `MemoSection` per key (title from a fixed map), attach `label_blockers(state)` into the `blocking` section body, annotate `albert_challenge_map` section from challenge statuses. Pure assembly (the only LLM is inside the synthesizer). Do NOT set `emitted=True` yet (gates do that, Task 7).
- [ ] **Step 4: Run** → PASS; `py -3 -m pytest -q` green.
- [ ] **Step 5: Commit** — `git commit -m "feat(p5): deterministic memo assembly (9 sections)"`

---

### Task 6: Wire P4b citation modules into memo assembly

**Files:**
- Modify: `src/cn5_research_cos/synthesis/memo.py` (apply `citation/verify` + `policy` + `flatten_to_primary` to memo claims)
- Test: `tests/test_memo_citation.py`

- [ ] **Step 1: Write the failing test** — a memo built from a web claim whose `excerpt` does NOT contain its quote → the claim is marked unverified by the now-wired `citation/verify`; a memo claim citing a digest source → `flatten_to_primary` re-points/drops it; an internal claim is carried (no difflib).
```python
def test_web_unverified_claim_flagged_in_memo(...): ...
def test_memo_claim_citing_digest_is_flattened(...): ...
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — in `assemble_memo`, before building the evidence_summary, run each claim through `citation.verify.verify(...)` (web origin → difflib≥0.85 against `Source.excerpt`; internal → carried) and `citation.policy` to classify unverified claims, and `citation.flatten_to_primary(...)` on memo claims. Use the EXISTING P4b functions — import from `citation/verify.py` and `citation/policy.py`; do not reimplement. Record unverified KEY claims on the Memo (a field, e.g. `memo.refused_reason` set later by the gate).
- [ ] **Step 4: Run** → PASS; `py -3 -m pytest -q` green.
- [ ] **Step 5: Commit** — `git commit -m "feat(p5): wire P4b citation verify/policy/flatten into memo (closes the P4b caveat)"`

---

### Task 7: Four emission gates + H6 wiring in the synthesize node

**Files:**
- Create: `src/cn5_research_cos/synthesis/gates.py`
- Modify: `src/cn5_research_cos/graph.py` (terminal/synthesize node)
- Test: `tests/test_emission_gates.py`

- [ ] **Step 1: Write the failing test** — each gate REFUSES independently: degraded/mock audit → `emitted=False` + reason; unresolved high-impact challenge → refused (reuse `convergence.gate_emission`); unverified KEY claim → refused; readiness below target AND no explicit command → refused; all gates pass + explicit command/readiness → `emitted=True`. The synthesize node leaves the run at the H6 `human_review` interrupt before "Done" (mirror the P3 H6 gate).
```python
from cn5_research_cos.synthesis.gates import check_emission
def test_degraded_audit_refuses(...): assert not check_emission(state, memo).emitted
def test_all_pass_emits_with_explicit_command(...): assert check_emission(state, memo, explicit=True).emitted
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `check_emission(state, memo, *, explicit=False) -> Memo` (pure): apply in order (1) degraded-audit (`state.last_audit` genuinely ran, not mock/degraded), (2) `convergence.gate_emission` (no unresolved high-impact challenge), (3) citation gate (no unverified KEY claim from Task 6), (4) readiness target met OR `explicit`. Set `memo.emitted`/`memo.refused_reason`. In `graph.py`'s synthesize node: build memo (Task 5/6), run `check_emission`, and if `enable_h6` route through the existing P3 `human_review` interrupt before terminal. Reuse `convergence.gate_emission` and the P3 H6 node — do not duplicate.
- [ ] **Step 4: Run** → PASS; `py -3 -m pytest -q` green.
- [ ] **Step 5: Commit** — `git commit -m "feat(p5): four emission gates + H6 in synthesize node"`

---

### Task 8: Soft budget warning (cumulative metrics, no hard cap)

**Files:**
- Modify: `src/cn5_research_cos/graph.py` (per-iteration metrics line) + `src/cn5_research_cos/cli.py` (print)
- Test: `tests/test_budget_warning.py`

- [ ] **Step 1: Write the failing test** — after each iteration the run exposes a cumulative `cost=$X / iter=Y / calls=Z` line from `RunMetrics.summary_line()`; assert the loop NEVER auto-stops on budget (research is not truncated).
```python
def test_budget_warning_emitted_not_capping(...):
    # metrics line present each iter; iteration_count still reaches max_iterations (no early budget stop)
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — surface `metrics.summary_line()` per iteration (log/print via the existing metrics threading from `run_loop`); the CLI prints it in `run`/`run_auto_cmd`. NO hard cap — purely informational (per spec Cost governance). Mirror the existing `metrics.summary_line()` usage.
- [ ] **Step 4: Run** → PASS; `py -3 -m pytest -q` green.
- [ ] **Step 5: Commit** — `git commit -m "feat(p5): soft budget warning (cumulative metrics, no hard cap)"`

---

### Task 9: Live memo test (opt-in) — end-to-end §22 memo

**Files:**
- Test: `tests/test_memo_live.py`

- [ ] **Step 1: Write the test** (opt-in `CN5_COS_LLM_TESTS=1`, skips cleanly otherwise): a short real run reaches readiness OR uses an explicit command, emits a `Memo` with all 9 §22 sections, a non-empty Albert Challenge Map, and cited evidence; assert `memo.emitted` and `len(memo.sections) == 9`.
- [ ] **Step 2: Run without opt-in** → SKIPPED (clean).
- [ ] **Step 3: (controller runs the live test, not the implementer)** — leave it skipping; the controller runs it post-implementation.
- [ ] **Step 4: Commit** — `git commit -m "test(p5): opt-in live §22 memo end-to-end"`

---

## Self-Review (run after writing)
- **Spec coverage:** ✅ excerpt capture (T2), synthesis brain/§22 9 sections (T4/T5), blocker labeling 6 kinds (T3), citation wiring (T6), 4 gates + H6 (T7), soft budget (T8), baseline run is post-merge (controller). Gap: the TC4 baseline end-to-end run is a CONTROLLER step after merge, not an implementer task — intentional.
- **Placeholder scan:** none — each task has concrete tests + implementation pointers to existing patterns (file refs) rather than vague "handle X".
- **Type consistency:** `Memo`/`MemoSection`/`BlockerType`/`Source.excerpt` (T1) used consistently in T3/T5/T6/T7; `Synthesizer.write_sections -> dict[str,str]` (T4) consumed by `assemble_memo` (T5); `NINE_SECTION_KEYS` single source of truth (T5).
