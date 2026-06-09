# P10a — Gate Wiring + Flow-Card Living Doc Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the three already-built-but-unwired deterministic gates (`grade_source`, `triangulate`, `public_exhausted`) into the research/classify flow via a structured `FieldObservation` layer, give `classify_cell` a 5th state (`open`), and keep the flow-card doc in sync.

**Architecture:** The LLM gains a structured-output channel (`observations`: field→value); deterministic code grades sources, triangulates per field, proves exhaustion, and classifies. `claims` (free-text narrative) is untouched. The exhaustion loop stamps `bundle.public_exhausted`; classification reads it so `na` is code-provable.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, Claude Agent SDK, pytest. Windows runner: `PYTHONPATH=src py -3 -m pytest`. Single test: `PYTHONPATH=src py -3 -m pytest tests/test_x.py::test_y -v`.

**Spec:** `docs/superpowers/specs/2026-06-08-p10a-gate-wiring-and-flow-cards-design.md`. **Invariant:** LLM extracts structured observations; code decides (grade/triangulate/exhaust/classify). **Build order:** model (1) → classify 5-state (2) → synthesize_cell (3) → extraction observations (4) → loop modalities+stamp (5) → graph wiring (6) → doc sync + regression (7).

---

### Task 1: FieldObservation model + EvidenceBundle fields

**Files:**
- Modify: `src/cn5_research_cos/models.py` (add `FieldObservation` near `Claim` ~214; add 2 fields to `EvidenceBundle` ~241)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_models.py`:

```python
def test_field_observation_and_bundle_obs_fields():
    from cn5_research_cos.models import FieldObservation, EvidenceBundle
    o = FieldObservation(field="packet_buffer", value="128 kB", source_ref="S1",
                         quote="packet buffer is 128 kB", confidence=5)
    assert o.field == "packet_buffer" and o.value == "128 kB" and o.source_ref == "S1"
    b = EvidenceBundle(query="q")
    assert b.observations == [] and b.public_exhausted is False
    b2 = EvidenceBundle(query="q", observations=[o], public_exhausted=True)
    assert EvidenceBundle.model_validate_json(b2.model_dump_json()) == b2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_models.py::test_field_observation_and_bundle_obs_fields -v`
Expected: FAIL (`ImportError: cannot import name 'FieldObservation'`).

- [ ] **Step 3: Write minimal implementation** — in `src/cn5_research_cos/models.py`, add after the `Claim` class:

```python
class FieldObservation(BaseModel):
    """P10a — a structured (field -> value) extraction the deterministic gates consume.
    The LLM emits these; code grades/triangulates/classifies over them."""
    field: str                       # MUST be one of the owning cell's success_criteria
    value: str                       # the extracted value, e.g. "128 kB", "4096"
    source_ref: str = ""             # Source.id this value came from
    quote: str = ""                  # verbatim span supporting the value
    confidence: int = Field(default=0, ge=0, le=5)
```

Then add to `EvidenceBundle` (after the `coverage_gaps` field):

```python
    # P10a: structured (field -> value) observations for the deterministic gates
    # (grade/triangulate/classify). Default empty so all P1-P9 bundles round-trip.
    observations: list[FieldObservation] = Field(default_factory=list)
    # P10a: the exhaustion loop stamps whether the cell's public modalities were
    # genuinely exhausted (so classification can prove `na`, never guess it).
    public_exhausted: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_models.py -q`
Expected: PASS (all model tests green).

- [ ] **Step 5: Commit**

```bash
git add src/cn5_research_cos/models.py tests/test_models.py
git commit -m "feat(p10a): FieldObservation model + EvidenceBundle observations/public_exhausted"
```

---

### Task 2: classify_cell 5-state (add `open` + `public_exhausted`)

**Files:**
- Modify: `src/cn5_research_cos/decision/cell_exhaustion.py` (`classify_cell` ~402)
- Test: `tests/test_cell_exhaustion.py`

- [ ] **Step 1: Write the failing test** — REPLACE the obsolete classify tests and ADD new tests in `tests/test_cell_exhaustion.py`. DELETE `test_classify_covered`, `test_classify_needs_internal_when_gated`, and `test_classify_na_public_exhausted` (they call `classify_cell` without `public_exhausted`), then add:

```python
def test_classify_na_only_when_exhausted():
    # empty + exhausted -> na ; empty + NOT exhausted -> open (keep researching)
    assert ce.classify_cell(_cell(), filled=set(), gated_detected=False,
                            public_exhausted=True) == CellStatus.na
    assert ce.classify_cell(_cell(), filled=set(), gated_detected=False,
                            public_exhausted=False) == CellStatus.open


def test_classify_partial_ignores_exhausted():
    assert ce.classify_cell(_cell(), filled={"packet_buffer"}, gated_detected=False,
                            public_exhausted=True) == CellStatus.partial


def test_classify_covered_and_blocked_with_new_param():
    assert ce.classify_cell(_cell(), filled={"packet_buffer", "vlan_table"},
                            gated_detected=False, public_exhausted=True) == CellStatus.covered
    assert ce.classify_cell(_cell(), filled={"packet_buffer"}, gated_detected=True,
                            public_exhausted=True) == CellStatus.blocked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_cell_exhaustion.py -v`
Expected: FAIL (`classify_cell() got an unexpected keyword argument 'public_exhausted'`).

- [ ] **Step 3: Write minimal implementation** — replace `classify_cell` in `src/cn5_research_cos/decision/cell_exhaustion.py`:

```python
def classify_cell(cell: TaskCell, *, filled: set[str], gated_detected: bool,
                  public_exhausted: bool) -> CellStatus:
    crit = set(cell.success_criteria)
    if crit and crit.issubset(filled):
        return CellStatus.covered
    if gated_detected and not crit.issubset(filled):
        return CellStatus.blocked        # = needs_internal (a gated source was code-detected)
    if filled:
        return CellStatus.partial
    if public_exhausted:
        return CellStatus.na             # public-exhausted, genuinely nothing (code-proven)
    return CellStatus.open               # NOT exhausted -> keep researching next round
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_cell_exhaustion.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cn5_research_cos/decision/cell_exhaustion.py tests/test_cell_exhaustion.py
git commit -m "feat(p10a): classify_cell 5-state (na requires public_exhausted; else open)"
```

---

### Task 3: synthesize_cell — wire grade_source + triangulate

**Files:**
- Create: `src/cn5_research_cos/decision/cell_synthesis.py`
- Test: `tests/test_cell_synthesis.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_cell_synthesis.py`:

```python
from cn5_research_cos.decision import cell_synthesis as cs
from cn5_research_cos.models import (TaskCell, EvidenceBundle, FieldObservation,
    Source, SourceType, SourceQuality)


def _cell():
    return TaskCell(id="NXP|f", vendor="NXP", spec_group="f", objective="o",
                    success_criteria=["packet_buffer", "vlan_table"])


def _bundle(obs, srcs):
    return EvidenceBundle(query="q", issue_id="NXP|f", observations=obs, sources=srcs)


def test_primary_observation_fills_field():
    s = Source(id="S1", title="DS", url="https://nxp.com/x.pdf",
               source_type=SourceType.primary, quality=SourceQuality.high)
    o = FieldObservation(field="packet_buffer", value="128 kB", source_ref="S1")
    syn = cs.synthesize_cell(_cell(), [_bundle([o], [s])])
    assert "packet_buffer" in syn.filled and syn.chosen["packet_buffer"] == "128 kB"


def test_incorrect_source_observation_dropped():
    s = Source(id="S2", title="blog", url="http://b", source_type=SourceType.marketing,
               quality=SourceQuality.low)   # grade_source -> "incorrect"
    o = FieldObservation(field="packet_buffer", value="999 kB", source_ref="S2")
    syn = cs.synthesize_cell(_cell(), [_bundle([o], [s])])
    assert "packet_buffer" not in syn.filled   # junk does not fill


def test_contradiction_resolved_by_primary():
    s_blog = Source(id="B", title="b", url="http://b", source_type=SourceType.secondary,
                    quality=SourceQuality.medium)
    s_ds = Source(id="DS", title="ds", url="https://nxp.com/x.pdf",
                  source_type=SourceType.primary, quality=SourceQuality.high)
    obs = [FieldObservation(field="vlan_table", value="1024", source_ref="B"),
           FieldObservation(field="vlan_table", value="4096", source_ref="DS")]
    syn = cs.synthesize_cell(_cell(), [_bundle(obs, [s_blog, s_ds])])
    assert syn.chosen["vlan_table"] == "4096" and "vlan_table" in syn.contradictions


def test_field_outside_criteria_ignored():
    s = Source(id="S1", title="DS", url="https://nxp.com/x.pdf",
               source_type=SourceType.primary, quality=SourceQuality.high)
    o = FieldObservation(field="not_a_criterion", value="x", source_ref="S1")
    syn = cs.synthesize_cell(_cell(), [_bundle([o], [s])])
    assert syn.filled == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_cell_synthesis.py -v`
Expected: FAIL (`ModuleNotFoundError: cn5_research_cos.decision.cell_synthesis`).

- [ ] **Step 3: Write minimal implementation** — create `src/cn5_research_cos/decision/cell_synthesis.py`:

```python
"""P10a §C — per-cell synthesis: wires the deterministic gates grade_source (CRAG)
+ triangulate over the LLM's structured FieldObservations. No LLM here — code decides
which fields are FILLED, the winning value, and where sources contradict."""
from __future__ import annotations
from dataclasses import dataclass, field as _field

from ..models import EvidenceBundle, Source, TaskCell
from .retrieval_grade import grade_source
from .triangulation import triangulate


@dataclass
class CellSynthesis:
    filled: set[str] = _field(default_factory=set)        # fields with an accepted value
    chosen: dict[str, str] = _field(default_factory=dict) # field -> winning value
    contradictions: set[str] = _field(default_factory=set)
    weak: set[str] = _field(default_factory=set)          # only weakly_sourced


def synthesize_cell(cell: TaskCell, bundles: list[EvidenceBundle]) -> CellSynthesis:
    crit = set(cell.success_criteria)
    src_by_id: dict[str, Source] = {}
    for b in bundles:
        for s in b.sources:
            src_by_id[s.id] = s
    per_field: dict[str, list[tuple[str, Source]]] = {}
    for b in bundles:
        for o in b.observations:
            if o.field not in crit:
                continue                          # LLM cannot invent fields
            src = src_by_id.get(o.source_ref)
            if src is None:
                continue
            if grade_source(src) == "incorrect":  # CRAG: junk does not fill
                continue
            per_field.setdefault(o.field, []).append((o.value, src))
    syn = CellSynthesis()
    for fld, obs in per_field.items():
        tri = triangulate(obs)
        if tri.status in ("corroborated", "weakly_sourced"):
            syn.filled.add(fld)
            syn.chosen[fld] = tri.value
            if tri.status == "weakly_sourced":
                syn.weak.add(fld)
        if tri.contradiction:
            syn.contradictions.add(fld)
    return syn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_cell_synthesis.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cn5_research_cos/decision/cell_synthesis.py tests/test_cell_synthesis.py
git commit -m "feat(p10a): synthesize_cell wires grade_source + triangulate over observations"
```

---

### Task 4: Extraction emits structured observations (LLM extracts)

**Files:**
- Modify: `src/cn5_research_cos/brains/real.py` (`_RESEARCH_SCHEMA` ~96, `_RESEARCH_SYSTEM` ~145, `_user_prompt` ~179, `_build_bundle` ~193, `_EXTRACT_SCHEMA`+`_EXTRACT_SYSTEM`, `_extract_from_text`)
- Test: `tests/test_observations_extraction.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_observations_extraction.py`:

```python
import cn5_research_cos.brains.real as real
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell)


def test_build_bundle_maps_observations_filtering_unknown_fields():
    raw = {
        "sources": [{"title": "DS", "url": "https://nxp.com/x.pdf",
                     "source_type": "primary", "quality": "high"}],
        "claims": [],
        "observations": [
            {"field": "packet_buffer", "value": "128 kB", "quote": "...", "confidence": 5, "source_indices": [0]},
            {"field": "not_a_criterion", "value": "x", "source_indices": [0]},
        ],
    }
    b = real.RealResearcher._build_bundle(raw, "t", "NXP|f", ["packet_buffer", "vlan_table"])
    assert len(b.observations) == 1
    o = b.observations[0]
    assert o.field == "packet_buffer" and o.value == "128 kB" and o.source_ref == "S-NXP|f-0"


def test_extract_from_text_returns_claims_and_observations(monkeypatch):
    def fake_struct(system, user, schema, **kw):
        return {"claims": [{"claim": "pb 128", "quote": "packet buffer 128 kB", "confidence": 5}],
                "observations": [{"field": "packet_buffer", "value": "128 kB", "quote": "packet buffer 128 kB", "confidence": 5}]}
    monkeypatch.setattr(real.sdk_client, "call_structured", fake_struct)
    claims, obs = real.RealResearcher._extract_from_text("doc text", "S-1", ["packet_buffer"])
    assert claims and claims[0].source_refs == ["S-1"]
    assert obs and obs[0].field == "packet_buffer" and obs[0].source_ref == "S-1"


def test_cell_criteria_lookup():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|f"] = TaskCell(id="NXP|f", vendor="NXP", spec_group="f",
        objective="o", success_criteria=["packet_buffer"])
    assert real.RealResearcher._cell_criteria(rs, "NXP|f") == ["packet_buffer"]
    assert real.RealResearcher._cell_criteria(rs, "missing") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_observations_extraction.py -v`
Expected: FAIL (`_build_bundle` takes 3 positional args, no `_cell_criteria`).

- [ ] **Step 3: Write minimal implementation** in `src/cn5_research_cos/brains/real.py`:

(a) Add `FieldObservation` to the models import:
```python
from ..models import (Claim, EvidenceBundle, FieldObservation, IssueNode,
                      IssueStatus, IssueType, ReadinessScore, ResearchState,
                      Source, SourceQuality, SourceType)
```

(b) Add an `observations` array to `_RESEARCH_SCHEMA` (inside the top-level `properties`, alongside `claims`):
```python
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                    "quote": {"type": "string"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 5},
                    "source_indices": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["field", "value"],
                "additionalProperties": False,
            },
        },
```

(c) Append to `_RESEARCH_SYSTEM` (before "Return STRICT JSON"):
```
"ALSO emit `observations`: for each TARGET FIELD you can fill from the results, one "
"{field, value, quote, confidence, source_indices} — `field` MUST be one of the "
"target fields given in the prompt; `value` is the concrete value (e.g. '128 kB', "
"'4096'); `quote` is the verbatim span. Omit a field you cannot find — NEVER write N/A. "
```

(d) Add a static helper after `_open_challenges_for_issue`:
```python
    @staticmethod
    def _cell_criteria(state: ResearchState, issue_id: str) -> list[str]:
        """The owning cell's success_criteria (target fields), or [] if no grid/cell."""
        grid = getattr(state, "task_grid", None)
        if grid is None:
            return []
        cell = grid.cells.get(issue_id)
        return list(cell.success_criteria) if cell else []
```

In `_user_prompt`, compute and inject the target fields. Add near the top of the method:
```python
        criteria = RealResearcher._cell_criteria(state, issue_id)
        fields = ("\nTARGET FIELDS to fill (emit observations for these): "
                  + ", ".join(criteria) + "\n") if criteria else ""
```
and insert `f"{fields}"` into the returned `user` string immediately before the
`"Run ONE WebSearch..."` sentence.

(e) Change `_build_bundle` signature:
```python
    @staticmethod
    def _build_bundle(raw: dict, title: str, issue_id: str,
                      criteria: list[str] | None = None) -> EvidenceBundle:
```
At the end of `_build_bundle`, before `return EvidenceBundle(...)`, build observations:
```python
        crit = set(criteria or [])
        observations: list[FieldObservation] = []
        for o in raw.get("observations", []):
            if o.get("field") not in crit:
                continue
            idxs = o.get("source_indices", [])
            sref = sources[idxs[0]].id if (idxs and isinstance(idxs[0], int)
                                           and 0 <= idxs[0] < len(sources)) else ""
            observations.append(FieldObservation(
                field=o["field"], value=o.get("value", ""), source_ref=sref,
                quote=o.get("quote", ""), confidence=int(o.get("confidence", 0))))
```
and add `observations=observations,` to the `EvidenceBundle(...)` constructor call.

(f) Add `observations` to `_EXTRACT_SCHEMA` (same shape as (b) but WITHOUT `source_indices`):
```python
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                    "quote": {"type": "string"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 5},
                },
                "required": ["field", "value"],
                "additionalProperties": False,
            },
        },
```
Append to `_EXTRACT_SYSTEM`: `"ALSO emit observations {field,value,quote,confidence} for the TARGET FIELDS listed; field MUST be one of them; omit unfound fields — never N/A."`

(g) Change `_extract_from_text` to take criteria and return `(claims, observations)`:
```python
    @staticmethod
    def _extract_from_text(text: str, source_id: str,
                           criteria: list[str] | None = None) -> tuple[list[Claim], list[FieldObservation]]:
        crit = set(criteria or [])
        flds = (" TARGET FIELDS: " + ", ".join(crit)) if crit else ""
        user = ("FETCHED DOCUMENT TEXT — extract grounded claims + verbatim quotes "
                "+ field observations for this sub-issue." + flds + "\n\n" + text[:20000])
        raw = sdk_client.call_structured(_EXTRACT_SYSTEM, user, _EXTRACT_SCHEMA)
        claims: list[Claim] = []
        for c in raw.get("claims", []):
            quote = (c.get("quote") or "").strip()
            claims.append(Claim(claim=c["claim"], source_refs=[source_id],
                                confidence=int(c.get("confidence", 0)), notes=quote))
        observations: list[FieldObservation] = []
        for o in raw.get("observations", []):
            if crit and o.get("field") not in crit:
                continue
            observations.append(FieldObservation(
                field=o["field"], value=o.get("value", ""), source_ref=source_id,
                quote=o.get("quote", ""), confidence=int(o.get("confidence", 0))))
        return claims, observations
```

(h) Update `research`/`research_async` to pass criteria to `_build_bundle` (BOTH methods), replacing `self._build_bundle(raw, title, issue_id)`:
```python
        criteria = self._cell_criteria(state, issue_id)
        bundle = self._build_bundle(raw, title, issue_id, criteria)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_observations_extraction.py tests/test_researcher_excerpt.py tests/test_real_brains.py -v`
Expected: PASS (existing researcher tests still green — `_build_bundle`'s 4th arg is optional; old callers pass 3 args).

- [ ] **Step 5: Commit**

```bash
git add src/cn5_research_cos/brains/real.py tests/test_observations_extraction.py
git commit -m "feat(p10a): extraction passes emit structured FieldObservations (target fields)"
```

---

### Task 5: Loop tracks modalities + stamps `public_exhausted`

**Files:**
- Modify: `src/cn5_research_cos/brains/real.py` (`_escalate` + `_escalate_async`; imports)
- Test: `tests/test_exhaustion_loop.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_exhaustion_loop.py`:

```python
def test_escalate_stamps_public_exhausted_true_when_drained(monkeypatch):
    import cn5_research_cos.brains.real as real
    from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell,
        EvidenceBundle, Source, SourceType, SourceQuality)
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|f"] = TaskCell(id="NXP|f", vendor="NXP", spec_group="f",
        objective="o", success_criteria=["packet_buffer"])
    src = Source(id="S-NXP|f-0", title="DS", url="https://nxp.com/x.pdf",
                 source_type=SourceType.primary, quality=SourceQuality.high)
    bundle = EvidenceBundle(query="q", issue_id="NXP|f", sources=[src])
    monkeypatch.setattr(real, "fetch_and_extract", lambda url, **kw: ("packet buffer 128 kB", "pymupdf4llm"), raising=False)
    monkeypatch.setattr(real.RealResearcher, "_extract_from_text",
        staticmethod(lambda text, sid, criteria=None: ([], [real.FieldObservation(field="packet_buffer", value="128 kB", source_ref=sid)])))
    out = real.RealResearcher()._escalate(bundle, rs)
    assert out.public_exhausted is True
    assert any(o.field == "packet_buffer" for o in out.observations)


def test_escalate_no_doc_url_is_vacuously_exhausted(monkeypatch):
    import cn5_research_cos.brains.real as real
    from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell,
        EvidenceBundle, Source, SourceType, SourceQuality)
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|f"] = TaskCell(id="NXP|f", vendor="NXP", spec_group="f",
        objective="o", success_criteria=["packet_buffer"])
    src = Source(id="S1", title="html", url="https://x.com/page.html",
                 source_type=SourceType.secondary, quality=SourceQuality.medium)
    bundle = EvidenceBundle(query="q", issue_id="NXP|f", sources=[src])
    out = real.RealResearcher()._escalate(bundle, rs)
    assert out.public_exhausted is True   # nothing fetchable -> fetch modality vacuously exhausted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_exhaustion_loop.py -v`
Expected: FAIL (`public_exhausted` stays default `False`; `_extract_from_text` arity).

- [ ] **Step 3: Write minimal implementation** — add to imports near the top of `real.py` (alongside the existing `from ..decision import cell_exhaustion`):
```python
from ..decision.cell_synthesis import synthesize_cell
```

Replace `_escalate` with:
```python
    def _escalate(self, bundle: EvidenceBundle, state: ResearchState) -> EvidenceBundle:
        """P10a — exhaust the FETCH modality, accumulate observations, then stamp
        bundle.public_exhausted (so classification can PROVE na)."""
        cell = state.task_grid.cells.get(bundle.issue_id) if getattr(state, "task_grid", None) else None
        criteria = list(cell.success_criteria) if cell else []
        fetched: set[str] = set()
        modalities = {"search"}
        rounds_no_new = 0
        max_rounds = self._max_rounds()
        for _ in range(max_rounds):
            todo = [s for s in bundle.sources if is_doc_url(s.url) and s.id not in fetched]
            if not todo:
                break
            new = False
            for s in todo:
                fetched.add(s.id)
                modalities.add("fetch")
                text, _backend = fetch_and_extract(s.url, base_dir="runs", run_id=state.run_id)
                if not text:
                    continue
                modalities.add("extract")
                s.excerpt = text[:2000]
                claims, obs = self._extract_from_text(text, s.id, criteria)
                for c in claims:
                    bundle.claims.append(c); new = True
                for o in obs:
                    bundle.observations.append(o); new = True
            if not new:
                rounds_no_new += 1
                break
            rounds_no_new = 0
        self._stamp_exhausted(bundle, cell, fetched, modalities, rounds_no_new)
        return bundle

    @staticmethod
    def _stamp_exhausted(bundle, cell, fetched, modalities, rounds_no_new) -> None:
        drained = not [s for s in bundle.sources if is_doc_url(s.url) and s.id not in fetched]
        if drained:
            modalities = modalities | {"fetch", "extract"}
        if cell is None:
            bundle.public_exhausted = drained
            return
        filled = synthesize_cell(cell, [bundle]).filled
        bundle.public_exhausted = cell_exhaustion.public_exhausted(
            cell, filled=filled, modalities_tried=modalities,
            all_modalities={"search", "fetch", "extract"}, rounds_no_new=rounds_no_new)
```

Replace `_escalate_async` with the same logic using `await asyncio.to_thread(...)` for the blocking calls:
```python
    async def _escalate_async(self, bundle: EvidenceBundle,
                              state: ResearchState) -> EvidenceBundle:
        cell = state.task_grid.cells.get(bundle.issue_id) if getattr(state, "task_grid", None) else None
        criteria = list(cell.success_criteria) if cell else []
        fetched: set[str] = set()
        modalities = {"search"}
        rounds_no_new = 0
        max_rounds = self._max_rounds()
        for _ in range(max_rounds):
            todo = [s for s in bundle.sources if is_doc_url(s.url) and s.id not in fetched]
            if not todo:
                break
            new = False
            for s in todo:
                fetched.add(s.id)
                modalities.add("fetch")
                text, _backend = await asyncio.to_thread(
                    fetch_and_extract, s.url, base_dir="runs", run_id=state.run_id)
                if not text:
                    continue
                modalities.add("extract")
                s.excerpt = text[:2000]
                claims, obs = await asyncio.to_thread(self._extract_from_text, text, s.id, criteria)
                for c in claims:
                    bundle.claims.append(c); new = True
                for o in obs:
                    bundle.observations.append(o); new = True
            if not new:
                rounds_no_new += 1
                break
            rounds_no_new = 0
        self._stamp_exhausted(bundle, cell, fetched, modalities, rounds_no_new)
        return bundle
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_exhaustion_loop.py tests/test_real_brains.py tests/test_fanout_concurrency.py -v`
Expected: PASS. NOTE: P9's `test_loop_escalates_to_fetch_then_stops` patches `_extract_from_text` returning a list of Claims — UPDATE that monkeypatch's fake to return a 2-tuple `([Claim(...)], [])`. Fix inline if it fails.

- [ ] **Step 5: Commit**

```bash
git add src/cn5_research_cos/brains/real.py tests/test_exhaustion_loop.py
git commit -m "feat(p10a): loop tracks modalities + stamps bundle.public_exhausted"
```

---

### Task 6: classify_grid_cells uses synthesize_cell + exhaustion stamp

**Files:**
- Modify: `src/cn5_research_cos/graph.py` (`classify_grid_cells` ~518; decision import ~36)
- Test: `tests/test_cell_classify_wiring.py`

- [ ] **Step 1: Write the failing test** — REPLACE `tests/test_cell_classify_wiring.py` with:

```python
import cn5_research_cos.graph as g
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell, CellStatus,
    EvidenceBundle, FieldObservation, Source, SourceType, SourceQuality)


def _rs_with_cell():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|fabric"] = TaskCell(id="NXP|fabric", vendor="NXP",
        spec_group="fabric", objective="o", success_criteria=["packet_buffer"])
    return rs


def test_cell_covered_when_observation_fills_criterion():
    rs = _rs_with_cell()
    src = Source(id="S1", title="DS", url="https://nxp.com/x.pdf",
                 source_type=SourceType.primary, quality=SourceQuality.high)
    rs.evidence.append(EvidenceBundle(query="q", issue_id="NXP|fabric", sources=[src],
        observations=[FieldObservation(field="packet_buffer", value="128 kB", source_ref="S1")],
        public_exhausted=True))
    g.classify_grid_cells(rs)
    assert rs.task_grid.cells["NXP|fabric"].status == CellStatus.covered


def test_cell_open_when_empty_and_not_exhausted():
    rs = _rs_with_cell()
    src = Source(id="S1", title="x", url="https://x/p.html",
                 source_type=SourceType.secondary, quality=SourceQuality.medium)
    rs.evidence.append(EvidenceBundle(query="q", issue_id="NXP|fabric", sources=[src],
        observations=[], public_exhausted=False))
    g.classify_grid_cells(rs)
    assert rs.task_grid.cells["NXP|fabric"].status == CellStatus.open


def test_cell_na_when_empty_and_exhausted():
    rs = _rs_with_cell()
    src = Source(id="S1", title="x", url="https://x/p.html",
                 source_type=SourceType.secondary, quality=SourceQuality.medium)
    rs.evidence.append(EvidenceBundle(query="q", issue_id="NXP|fabric", sources=[src],
        observations=[], public_exhausted=True))
    g.classify_grid_cells(rs)
    assert rs.task_grid.cells["NXP|fabric"].status == CellStatus.na
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_cell_classify_wiring.py -v`
Expected: FAIL (old `classify_grid_cells` uses claim-substring + 3-arg `classify_cell`).

- [ ] **Step 3: Write minimal implementation** — in `src/cn5_research_cos/graph.py`:

(a) add `cell_synthesis` to the decision import line:
```python
from .decision import (anti_premature, branch_budget, cell_exhaustion,
                       cell_synthesis, convergence, exhaustion, gate, risk, run_cap)
```

(b) Replace the body of `classify_grid_cells` (KEEP the `_GATED_MARKERS`, `_norm_text`, `_gated_signal` helpers above it):
```python
def classify_grid_cells(rs: ResearchState) -> None:
    """P10a — deterministic per-cell status from the structured observations.
    synthesize_cell (grade + triangulate) computes `filled`; the loop's
    bundle.public_exhausted proves whether `na` is allowed. Cells with no evidence
    are left untouched (still open)."""
    grid = rs.task_grid
    if grid is None:
        return
    for cell in grid.cells.values():
        bundles = [b for b in rs.evidence if b.issue_id == cell.id]
        if not bundles:
            continue
        syn = cell_synthesis.synthesize_cell(cell, bundles)
        gated = any(_gated_signal(s) for b in bundles for s in b.sources)
        exhausted = any(b.public_exhausted for b in bundles)
        cell.status = cell_exhaustion.classify_cell(
            cell, filled=syn.filled, gated_detected=gated, public_exhausted=exhausted)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src py -3 -m pytest tests/test_cell_classify_wiring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cn5_research_cos/graph.py tests/test_cell_classify_wiring.py
git commit -m "feat(p10a): classify_grid_cells uses synthesize_cell + public_exhausted stamp"
```

---

### Task 7: Doc sync, full regression, live verification

**Files:**
- Modify (if drift): `docs/superpowers/specs/2026-06-08-p10a-gate-wiring-and-flow-cards-design.md`

- [ ] **Step 1: Card↔file sync check** — open the spec's §E cross-reference table; confirm every row's symbol/file matches the committed code from Tasks 1-6 (`synthesize_cell` → `decision/cell_synthesis.py`; `classify_cell` 5-state; `_stamp_exhausted` internal to `_escalate*`). Fix any drift inline.

- [ ] **Step 2: Targeted regression** — run the P10a-touched suites:

Run: `PYTHONPATH=src py -3 -m pytest tests/test_models.py tests/test_cell_exhaustion.py tests/test_cell_synthesis.py tests/test_observations_extraction.py tests/test_exhaustion_loop.py tests/test_cell_classify_wiring.py tests/test_real_brains.py tests/test_researcher_excerpt.py tests/test_fanout_concurrency.py tests/test_doc_extract.py tests/test_citation_notify_wiring.py tests/test_memo_assembly.py -q`
Expected: all PASS. Fix any P9 test that asserted classification under the old 3-arg `classify_cell` (update to pass `public_exhausted=`).

- [ ] **Step 3: Full deterministic suite** — confirm no wider breakage:

Run: `PYTHONPATH=src py -3 -m pytest -q -p no:cacheprovider -m "not llm" --ignore=tests/test_cli.py --ignore=tests/test_cli_hitl.py --ignore=tests/test_cli_sot.py --ignore=tests/test_cos_watch.py --ignore=tests/test_sot_clarifier.py --ignore=tests/test_loop_real.py --ignore=tests/test_loop_metrics.py`
Expected: all PASS (the 2 ignored loop tests spawn a real `claude` subprocess; the cli/sot tests need cn5_ask — both environment-dependent, not P10a).

- [ ] **Step 4: Live verification (opt-in, clean env — NOT nested)** — re-run the NXP SJA1105 focused driver (the P9 dogfood pattern: build a one-cell `ResearchState` with `success_criteria=["packet_buffer","vlan_table","queues","cbs","aec_q100"]`, call `RealResearcher().research`, print `bundle.observations` + classified status). Confirm: structured observations carry `field`/`value`/`source_ref` (e.g. vlan_table=4096); `bundle.public_exhausted` is stamped; `na` appears only on genuinely exhausted-empty cells.

- [ ] **Step 5: Commit any doc/test fixes**

```bash
git add docs/superpowers/specs/2026-06-08-p10a-gate-wiring-and-flow-cards-design.md tests/
git commit -m "test(p10a): full regression green; flow-card cross-ref synced"
```

---

## Self-review notes

- **Spec coverage:** §A→T1, §C(synthesize/grade/triangulate)→T3, §B(observations extraction)→T4, §D(loop stamp)→T5, §D(5-state classify)→T2, §D(classify_grid_cells)→T6, §E(card doc sync)→T7, §F(testing)→every task + T7. All spec sections mapped.
- **Invariant preserved:** the LLM only emits `observations`/`claims`; grade/triangulate/exhaust/classify are pure code (T2, T3, T5, T6).
- **Back-compat:** `observations` + `public_exhausted` default empty/false; `_build_bundle`'s criteria arg is optional. Intended behavioral breaks: `classify_cell`'s new required `public_exhausted` kwarg + `na`→`open` change (P9 tests updated in T2/T6/T7); `_extract_from_text`'s new 2-tuple return (P9 loop test fixed in T5 Step 4).
- **Type consistency:** `_extract_from_text` → `(list[Claim], list[FieldObservation])` (T4 defines, T5 consumes); `synthesize_cell` → `CellSynthesis` (T3 defines, T5+T6 consume `.filled`); `classify_cell(..., public_exhausted=)` (T2 defines, T6 calls); `_stamp_exhausted` (T5 defines + calls in both `_escalate`/`_escalate_async`).
- **Out of scope (per spec):** grade "ambiguous→refetch"; auto card generator; Gap B robust-retrieval (404 URLs) — deferred to P10b.
