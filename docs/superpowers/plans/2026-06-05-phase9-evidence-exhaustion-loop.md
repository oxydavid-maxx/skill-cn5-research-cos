# Phase 9 — evidence-exhaustion sub-loop + multi-backend extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make per-cell research exhaustive — read primary content (page + PDF via a multi-backend extractor), grade/triangulate sources, and only classify a field `n/a`/`needs_internal` after deterministic code proves public modalities are exhausted (never a lazy LLM N/A).

**Architecture:** The exhaustion loop slots INSIDE `RealResearcher.research`/`research_async`, preserving the `(state, issue_id[, pool]) -> EvidenceBundle` contract the fan-out depends on. The LLM only EXTRACTS field-values from fetched content; the exhaustion (§A-f), triangulation (§D), grade (§E) and classification (§C-h) gates are deterministic code over that extraction.

**Tech Stack:** Python 3.11/3.12, Pydantic v2, LangGraph, Claude Agent SDK (WebSearch + WebFetch built-in tools), pytest. Windows: `py -3`, `PYTHONPATH=src`.

**Test invocation:** `PYTHONPATH=src py -3 -m pytest -q` (full); single: `PYTHONPATH=src py -3 -m pytest tests/test_x.py::test_y -v`.

**Spec:** `docs/spec/2026-06-05-phase9-evidence-exhaustion-loop-design.md`. **Status mapping (reuse existing CellStatus):** `na` = n/a(public-exhausted); `blocked` = needs_internal (its existing P8 meaning is "NDA/internal-only"). Build order: models/orchestrator (1-2) → extraction (3-4) → grade/triangulate/gate (5-7) → the loop (8) → wire classify+notify (9).

---

### Task 1: TaskCell success_criteria + expected_sources

**Files:** Modify `src/cn5_research_cos/models.py` (`TaskCell`, ~136-148). Test: `tests/test_models.py`.

- [ ] **Step 1: failing test** — add to `tests/test_models.py`:
```python
def test_taskcell_has_success_criteria_and_expected_sources():
    from cn5_research_cos.models import TaskCell, CellStatus
    c = TaskCell(id="NXP|fabric", vendor="NXP", spec_group="fabric", objective="o",
                 success_criteria=["packet_buffer", "vlan_table"],
                 expected_sources=["vendor datasheet PDF"])
    assert c.success_criteria == ["packet_buffer", "vlan_table"]
    assert c.expected_sources == ["vendor datasheet PDF"]
    # defaults
    d = TaskCell(id="x|y", vendor="x", spec_group="y", objective="o")
    assert d.success_criteria == [] and d.expected_sources == []
```
- [ ] **Step 2: verify FAIL** — `PYTHONPATH=src py -3 -m pytest tests/test_models.py::test_taskcell_has_success_criteria_and_expected_sources -v`
- [ ] **Step 3: implement** — in `TaskCell` add (after `boundaries`):
```python
    success_criteria: list[str] = Field(default_factory=list)   # target field names that must be filled to count as covered
    expected_sources: list[str] = Field(default_factory=list)   # e.g. ["vendor datasheet PDF"]
```
- [ ] **Step 4: verify PASS** — same pytest.
- [ ] **Step 5: regression** — `PYTHONPATH=src py -3 -m pytest tests/test_models.py tests/test_persistence.py -q` green.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/models.py tests/test_models.py && git commit -m "feat(p9): TaskCell success_criteria + expected_sources"` (trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`).

---

### Task 2: Orchestrator emits success_criteria + expected_sources

**Files:** Modify `src/cn5_research_cos/brains/orchestrator.py` (`_SCHEMA` ~95, `RealOrchestrator.plan` ~124, `MockOrchestrator.plan` ~79). Test: `tests/test_orchestrator_brain.py`.

- [ ] **Step 1: failing test**:
```python
def test_orchestrator_emits_success_criteria(monkeypatch):
    import cn5_research_cos.brains.orchestrator as orch
    from cn5_research_cos.models import ResearchState
    def fake(system, user, schema, **kw):
        return {"cells": [{"vendor":"NXP","spec_group":"fabric","objective":"o",
                           "success_criteria":["packet_buffer"],"expected_sources":["datasheet PDF"]}]}
    monkeypatch.setattr(orch, "call_structured", fake)
    g = orch.RealOrchestrator().plan(ResearchState(run_id="r", original_question="q"))
    cell = g.cells["NXP|fabric"]
    assert cell.success_criteria == ["packet_buffer"]
    assert cell.expected_sources == ["datasheet PDF"]
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** — in `_SCHEMA` add to each cell's `properties`: `"success_criteria": {"type":"array","items":{"type":"string"}}, "expected_sources": {"type":"array","items":{"type":"string"}}` (keep `required` as-is). In `RealOrchestrator.plan` `TaskCell(...)` construction add `success_criteria=c.get("success_criteria", []), expected_sources=c.get("expected_sources", [])`. In `MockOrchestrator.plan`'s seed cell add `success_criteria=["spec"], expected_sources=["vendor datasheet"]`. Add to `_SYSTEM` a line: "For each cell also give success_criteria (the target field names that must be filled) and expected_sources (e.g. 'vendor datasheet PDF')."
- [ ] **Step 4: verify PASS**.
- [ ] **Step 5: regression** — `PYTHONPATH=src py -3 -m pytest tests/test_orchestrator_brain.py tests/test_orchestrator_node.py -q` green.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/brains/orchestrator.py tests/test_orchestrator_brain.py && git commit -m "feat(p9): orchestrator emits success_criteria + expected_sources"`.

---

### Task 3: Multi-backend document extraction fallback chain (§B)

**Files:** Create `src/cn5_research_cos/brains/doc_extract.py`. Test: create `tests/test_doc_extract.py`.

- [ ] **Step 1: failing test**:
```python
from cn5_research_cos.brains import doc_extract

def test_fallback_docling_then_pymupdf(monkeypatch, tmp_path):
    p = tmp_path / "d.pdf"; p.write_bytes(b"%PDF-1.5 fake")
    calls = []
    monkeypatch.setattr(doc_extract, "_extract_docling", lambda path: (_ for _ in ()).throw(RuntimeError("OOM")))
    monkeypatch.setattr(doc_extract, "_extract_pymupdf4llm", lambda path: calls.append("pymupdf") or "MARKDOWN TEXT")
    text, backend = doc_extract.extract_doc(str(p))
    assert text == "MARKDOWN TEXT" and backend == "pymupdf4llm" and calls == ["pymupdf"]

def test_all_fail_returns_visible_gap(monkeypatch, tmp_path):
    p = tmp_path / "d.pdf"; p.write_bytes(b"%PDF")
    for fn in ("_extract_docling","_extract_pymupdf4llm","_extract_pypdf"):
        monkeypatch.setattr(doc_extract, fn, lambda path: (_ for _ in ()).throw(RuntimeError("x")))
    text, backend = doc_extract.extract_doc(str(p))
    assert text == "" and backend == "none"
```
- [ ] **Step 2: verify FAIL** (ImportError).
- [ ] **Step 3: implement** `src/cn5_research_cos/brains/doc_extract.py`:
```python
"""P9 §B — multi-backend document extraction with fallback. docling can OOM/parse-fail;
fall back to pymupdf4llm then pypdf. Fail-visible (returns ("","none")), never raises."""
from __future__ import annotations
import logging
logger = logging.getLogger("cn5_research_cos.doc_extract")

def _extract_docling(path: str) -> str:
    from docling.document_converter import DocumentConverter  # lazy
    res = DocumentConverter().convert(path)
    return res.document.export_to_markdown()

def _extract_pymupdf4llm(path: str) -> str:
    import pymupdf4llm  # lazy
    return pymupdf4llm.to_markdown(path)

def _extract_pypdf(path: str) -> str:
    import pypdf  # lazy
    r = pypdf.PdfReader(path)
    return "\n".join((pg.extract_text() or "") for pg in r.pages)

_CHAIN = (("docling", _extract_docling), ("pymupdf4llm", _extract_pymupdf4llm), ("pypdf", _extract_pypdf))

def extract_doc(path: str) -> tuple[str, str]:
    """Return (text, backend_used). Tries each backend; ("","none") if all fail (visible gap)."""
    for name, fn in _CHAIN:
        try:
            text = fn(path)
            if text and text.strip():
                return text, name
        except Exception as e:  # noqa: BLE001 - degrade to next backend, visibly
            logger.warning("doc_extract backend %s failed for %s: %s: %s", name, path, type(e).__name__, e)
    logger.error("doc_extract: ALL backends failed for %s (visible gap)", path)
    return "", "none"
```
NOTE: the test monkeypatches the private `_extract_*` names, so `extract_doc` must call them via module-level lookup (it does, via `_CHAIN` referencing the functions — to allow monkeypatch, build `_CHAIN` inside `extract_doc` from the current module globals). Adjust: inside `extract_doc`, do `chain = (("docling", _extract_docling), ...)` referencing the names at call time, OR look them up via `globals()`. Use `globals()[fnname]` to honor monkeypatch:
```python
def extract_doc(path: str) -> tuple[str, str]:
    for name, fnname in (("docling","_extract_docling"),("pymupdf4llm","_extract_pymupdf4llm"),("pypdf","_extract_pypdf")):
        try:
            text = globals()[fnname](path)
            if text and text.strip():
                return text, name
        except Exception as e:  # noqa: BLE001
            logger.warning("doc_extract %s failed for %s: %s: %s", name, path, type(e).__name__, e)
    logger.error("doc_extract: ALL backends failed for %s", path)
    return "", "none"
```
(Remove the module-level `_CHAIN`.)
- [ ] **Step 4: verify PASS** — `PYTHONPATH=src py -3 -m pytest tests/test_doc_extract.py -v`.
- [ ] **Step 5: regression** — full suite `PYTHONPATH=src py -3 -m pytest -q` green (new module, nothing else touched).
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/brains/doc_extract.py tests/test_doc_extract.py && git commit -m "feat(p9): multi-backend doc extraction fallback (docling->pymupdf4llm->pypdf)"`.

---

### Task 4: Download + extract web-found PDFs into the reference store (§B)

**Files:** Create `src/cn5_research_cos/brains/retrieval.py`. Test: create `tests/test_retrieval_fetch.py`.

- [ ] **Step 1: failing test**:
```python
from cn5_research_cos.brains import retrieval

def test_is_pdf_url():
    assert retrieval.is_doc_url("https://x.com/a.pdf")
    assert retrieval.is_doc_url("https://x.com/a.PDF?x=1")
    assert not retrieval.is_doc_url("https://x.com/page.html")

def test_fetch_and_extract(monkeypatch, tmp_path):
    monkeypatch.setattr(retrieval, "_download", lambda url, dest: dest.write_bytes(b"%PDF") or dest)
    monkeypatch.setattr(retrieval, "extract_doc", lambda p: ("EXTRACTED SPECS", "pymupdf4llm"))
    text, backend = retrieval.fetch_and_extract("https://x.com/sja.pdf", base_dir=str(tmp_path))
    assert text == "EXTRACTED SPECS" and backend == "pymupdf4llm"
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** `src/cn5_research_cos/brains/retrieval.py`:
```python
"""P9 §B — fetch a web-found doc/PDF and extract it (so public datasheets get READ, not just
search-snippeted). Deterministic; the LLM does not decide here."""
from __future__ import annotations
import logging, os, urllib.request
from pathlib import Path
from .doc_extract import extract_doc
logger = logging.getLogger("cn5_research_cos.retrieval")

_DOC_EXT = (".pdf",)

def is_doc_url(url: str | None) -> bool:
    if not url:
        return False
    path = url.split("?", 1)[0].lower()
    return any(path.endswith(ext) for ext in _DOC_EXT)

def _download(url: str, dest: Path) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:  # noqa: S310
        f.write(r.read())
    return dest

def fetch_and_extract(url: str, *, base_dir: str = "runs", run_id: str = "_docs") -> tuple[str, str]:
    """Download a doc URL into the reference store + extract. Returns (text, backend); ("","none") on failure."""
    try:
        d = Path(base_dir) / run_id / "reference" / "fetched"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / (os.path.basename(url.split("?", 1)[0]) or "doc.pdf")
        _download(url, dest)
        return extract_doc(str(dest))
    except Exception as e:  # noqa: BLE001 - visible gap, never raise into the loop
        logger.warning("fetch_and_extract failed for %s: %s: %s", url, type(e).__name__, e)
        return "", "none"
```
- [ ] **Step 4: verify PASS**.
- [ ] **Step 5: regression** — full suite green.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/brains/retrieval.py tests/test_retrieval_fetch.py && git commit -m "feat(p9): fetch+extract web-found PDFs into reference store"`.

---

### Task 5: CRAG-style retrieval grade-gate (§E)

**Files:** Create `src/cn5_research_cos/decision/retrieval_grade.py`. Test: create `tests/test_retrieval_grade.py`.

- [ ] **Step 1: failing test**:
```python
from cn5_research_cos.decision import retrieval_grade as rg
from cn5_research_cos.models import Source, SourceType, SourceQuality

def test_grade_primary_high_is_correct():
    s = Source(id="S1", title="datasheet", url="https://nxp.com/x.pdf",
               source_type=SourceType.primary, quality=SourceQuality.high)
    assert rg.grade_source(s) == "correct"

def test_grade_low_quality_is_incorrect():
    s = Source(id="S2", title="blog", url="http://b", source_type=SourceType.marketing,
               quality=SourceQuality.low)
    assert rg.grade_source(s) == "incorrect"

def test_grade_medium_is_ambiguous():
    s = Source(id="S3", title="distrib", url="http://d", source_type=SourceType.secondary,
               quality=SourceQuality.medium)
    assert rg.grade_source(s) == "ambiguous"
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** `src/cn5_research_cos/decision/retrieval_grade.py`:
```python
"""P9 §E — deterministic CRAG grade-gate. correct=use, ambiguous=refine+fetch-more,
incorrect=discard+escalate. Grades by source metadata (no LLM)."""
from __future__ import annotations
from ..models import Source, SourceType, SourceQuality

def grade_source(s: Source) -> str:
    if s.source_type in (SourceType.primary, SourceType.standard) or s.quality == SourceQuality.high:
        return "correct"
    if s.quality == SourceQuality.low or s.source_type == SourceType.marketing:
        return "incorrect"
    return "ambiguous"
```
- [ ] **Step 4: verify PASS**.
- [ ] **Step 5: regression** — full suite green.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/decision/retrieval_grade.py tests/test_retrieval_grade.py && git commit -m "feat(p9): CRAG-style retrieval grade-gate (deterministic)"`.

---

### Task 6: Cross-source triangulation + contradiction (§D)

**Files:** Create `src/cn5_research_cos/decision/triangulation.py`. Test: create `tests/test_triangulation.py`.

- [ ] **Step 1: failing test**:
```python
from cn5_research_cos.decision import triangulation as tri
from cn5_research_cos.models import Source, SourceType, SourceQuality

def _src(i, t, q): return Source(id=i, title=i, url="http://"+i, source_type=t, quality=q)

def test_two_secondary_agree_corroborated():
    obs = [("5", _src("A", SourceType.secondary, SourceQuality.medium)),
           ("5", _src("B", SourceType.secondary, SourceQuality.medium))]
    r = tri.triangulate(obs)
    assert r.value == "5" and r.status == "corroborated" and not r.contradiction

def test_one_primary_corroborated():
    obs = [("4", _src("DS", SourceType.primary, SourceQuality.high))]
    r = tri.triangulate(obs)
    assert r.value == "4" and r.status == "corroborated"

def test_single_secondary_weak():
    obs = [("4", _src("X", SourceType.secondary, SourceQuality.low))]
    r = tri.triangulate(obs)
    assert r.status == "weakly_sourced"

def test_contradiction_resolved_by_primary():
    obs = [("5", _src("blog", SourceType.secondary, SourceQuality.medium)),
           ("4", _src("DS", SourceType.primary, SourceQuality.high))]
    r = tri.triangulate(obs)
    assert r.contradiction is True and r.value == "4"  # primary wins
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** `src/cn5_research_cos/decision/triangulation.py`:
```python
"""P9 §D — cross-source triangulation + contradiction detection. Deterministic.
corroborated = >=2 sources agree OR 1 primary; weakly_sourced = single secondary;
contradiction = differing values, resolved by primary > recency > quality."""
from __future__ import annotations
from dataclasses import dataclass
from ..models import Source, SourceType, SourceQuality

_Q_RANK = {SourceQuality.high: 3, SourceQuality.medium: 2, SourceQuality.low: 1, SourceQuality.unknown: 0}

def _is_primary(s: Source) -> bool:
    return s.source_type in (SourceType.primary, SourceType.standard)

def _norm(v: str) -> str:
    return " ".join(str(v).strip().lower().split())

@dataclass
class TriResult:
    value: str | None
    status: str           # corroborated | weakly_sourced | none
    contradiction: bool
    all_values: dict      # normalized_value -> [source_id]

def triangulate(observations: list[tuple[str, Source]]) -> TriResult:
    """observations = [(value, source), ...] for ONE (product, field)."""
    if not observations:
        return TriResult(None, "none", False, {})
    groups: dict[str, list[Source]] = {}
    raw: dict[str, str] = {}
    for val, src in observations:
        k = _norm(val)
        groups.setdefault(k, []).append(src)
        raw[k] = val
    contradiction = len(groups) > 1
    # pick the winning value group: prefer a group with a primary; else most sources; else best quality
    def group_key(item):
        k, srcs = item
        has_primary = any(_is_primary(s) for s in srcs)
        best_q = max(_Q_RANK[s.quality] for s in srcs)
        return (has_primary, len(srcs), best_q)
    win_k, win_srcs = max(groups.items(), key=group_key)
    if any(_is_primary(s) for s in win_srcs) or len(win_srcs) >= 2:
        status = "corroborated"
    else:
        status = "weakly_sourced"
    return TriResult(raw[win_k], status, contradiction,
                     {k: [s.id for s in v] for k, v in groups.items()})
```
- [ ] **Step 4: verify PASS** — `PYTHONPATH=src py -3 -m pytest tests/test_triangulation.py -v`.
- [ ] **Step 5: regression** — full suite green.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/decision/triangulation.py tests/test_triangulation.py && git commit -m "feat(p9): cross-source triangulation + contradiction (deterministic)"`.

---

### Task 7: Per-cell exhaustion gate + classify (§5 f/h)

**Files:** Create `src/cn5_research_cos/decision/cell_exhaustion.py`. Test: create `tests/test_cell_exhaustion.py`.

- [ ] **Step 1: failing test**:
```python
from cn5_research_cos.decision import cell_exhaustion as ce
from cn5_research_cos.models import TaskCell, CellStatus

def _cell(): return TaskCell(id="NXP|f", vendor="NXP", spec_group="f", objective="o",
                             success_criteria=["packet_buffer","vlan_table"])

def test_not_exhausted_when_field_missing_and_modalities_left():
    assert ce.public_exhausted(_cell(), filled={"packet_buffer"}, modalities_tried={"search"},
                               all_modalities={"search","fetch","extract"}, rounds_no_new=0) is False

def test_exhausted_when_all_modalities_tried():
    assert ce.public_exhausted(_cell(), filled={"packet_buffer"}, modalities_tried={"search","fetch","extract"},
                               all_modalities={"search","fetch","extract"}, rounds_no_new=0) is True

def test_classify_covered():
    assert ce.classify_cell(_cell(), filled={"packet_buffer","vlan_table"}, gated_detected=False) == CellStatus.covered

def test_classify_needs_internal_when_gated():
    assert ce.classify_cell(_cell(), filled={"packet_buffer"}, gated_detected=True) == CellStatus.blocked  # = needs_internal

def test_classify_na_public_exhausted():
    assert ce.classify_cell(_cell(), filled={"packet_buffer"}, gated_detected=False) == CellStatus.partial
    assert ce.classify_cell(_cell(), filled=set(), gated_detected=False) == CellStatus.na
```
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** `src/cn5_research_cos/decision/cell_exhaustion.py`:
```python
"""P9 §5 (f)+(h) — DETERMINISTIC exhaustion gate + classification over the LLM's extraction.
The LLM may only say "this field's value is X"; it CANNOT declare N/A. n/a is code-PROVABLE
(all modalities tried + field empty + no gated signal); needs_internal requires a gated signal."""
from __future__ import annotations
from ..models import TaskCell, CellStatus

MAX_CELL_ROUNDS_DEFAULT = 4
K_ROUNDS_NO_NEW = 2

def _criteria_met(cell: TaskCell, filled: set[str]) -> bool:
    crit = set(cell.success_criteria)
    return bool(crit) and crit.issubset(filled)

def public_exhausted(cell: TaskCell, *, filled: set[str], modalities_tried: set[str],
                     all_modalities: set[str], rounds_no_new: int) -> bool:
    if _criteria_met(cell, filled):
        return True
    if modalities_tried >= all_modalities:   # every modality tried
        return True
    return rounds_no_new >= K_ROUNDS_NO_NEW

def classify_cell(cell: TaskCell, *, filled: set[str], gated_detected: bool) -> CellStatus:
    crit = set(cell.success_criteria)
    if crit and crit.issubset(filled):
        return CellStatus.covered
    if gated_detected and not crit.issubset(filled):
        return CellStatus.blocked        # = needs_internal (a gated source was code-detected)
    if filled:
        return CellStatus.partial
    return CellStatus.na                  # public-exhausted, genuinely nothing
```
- [ ] **Step 4: verify PASS**.
- [ ] **Step 5: regression** — full suite green.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/decision/cell_exhaustion.py tests/test_cell_exhaustion.py && git commit -m "feat(p9): deterministic exhaustion gate + cell classification"`.

---

### Task 8: The exhaustion LOOP inside RealResearcher (§A) — integration

**Files:** Modify `src/cn5_research_cos/brains/real.py` (`RealResearcher`, 160-257). Test: create `tests/test_exhaustion_loop.py`.

Context: preserve `research(state, issue_id) -> EvidenceBundle` and `research_async(state, issue_id, *, pool) -> EvidenceBundle`. The loop: round 1 = the existing websearch; if the cell's target fields (from the issue's linked cell, if any — else the issue title) aren't filled, escalate: fetch+extract any doc URL among the bundle's sources (via `retrieval.fetch_and_extract`), re-extract fields from that content with one more `call_structured` (no tools) pass, grade sources, accumulate. Bounded by `MAX_CELL_ROUNDS` + per-round "no new field" gate. The LLM extracts; the gate (`cell_exhaustion.public_exhausted`) decides when to stop.

- [ ] **Step 1: failing test** (mock the SDK + retrieval; assert the loop escalates to fetch when round-1 leaves a field empty, and stops when filled):
```python
import cn5_research_cos.brains.real as real
from cn5_research_cos.models import ResearchState, IssueNode, IssueType, IssueStatus

def _state_with_issue():
    rs = ResearchState(run_id="r", original_question="q")
    rs.issue_map["I-1"] = IssueNode(id="I-1", title="NXP packet buffer",
        description="find packet_buffer", issue_type=IssueType.intent,
        status=IssueStatus.open, impact=5, confidence=2)
    return rs

def test_loop_escalates_to_fetch_then_stops(monkeypatch):
    rounds = {"n": 0}
    def fake_ws(system, user, schema, **kw):  # round 1: a source that is a PDF, no usable claim yet
        return {"sources":[{"title":"DS","url":"https://nxp.com/sja.pdf","source_type":"primary","quality":"high","excerpt":"see datasheet"}],
                "claims":[]}
    def fake_extract(url, **kw):  # the fetched PDF yields the spec
        return ("packet buffer is 128 kB", "pymupdf4llm")
    def fake_struct(system, user, schema, **kw):  # extraction pass over fetched text → a grounded claim
        rounds["n"] += 1
        return {"claims":[{"claim":"packet buffer 128 kB","quote":"packet buffer is 128 kB","source_indices":[0],"confidence":5}]}
    monkeypatch.setattr(real.sdk_client, "call_structured_websearch", fake_ws)
    monkeypatch.setattr(real, "fetch_and_extract", fake_extract, raising=False)
    monkeypatch.setattr(real.sdk_client, "call_structured", fake_struct)
    b = real.RealResearcher().research(_state_with_issue(), "I-1")
    assert any("128 kB" in c.claim for c in b.claims)   # the fetched-PDF spec made it into the bundle
```
(If the exact escalation seam differs, adjust the test to the real method names — but the behavioral contract is: a round-1 PDF source with no claim triggers a fetch+extract+re-extract that yields the claim.)
- [ ] **Step 2: verify FAIL**.
- [ ] **Step 3: implement** — refactor `RealResearcher`:
  - Import at top: `from .retrieval import fetch_and_extract, is_doc_url` and `from ..decision import cell_exhaustion`.
  - Keep `_user_prompt`/`_build_bundle`. Add `_extract_from_text(text, source_id) -> list[Claim]` doing ONE `sdk_client.call_structured` (no tools) with a small schema `{"claims":[{claim,quote,confidence}]}` over the fetched text, building `Claim(claim=..., source_refs=[source_id], confidence=..., notes=quote)`.
  - New `_research_loop(state, issue_id, ws_call) -> EvidenceBundle`: round 1 = `ws_call()` → `_build_bundle`. Then while not satisfied and rounds < `_max_rounds()`: for each bundle source where `is_doc_url(s.url)` and not yet fetched → `text, backend = fetch_and_extract(s.url, base_dir=..., run_id=state.run_id)`; if text → `claims = _extract_from_text(text, s.id)`; append to bundle (and set `s.excerpt = text[:2000]` so verbatim verify has the source text); mark fetched. Stop when no new doc-source to fetch (deterministic exhaustion of the fetch modality). Cap rounds via env `CN5_COS_MAX_CELL_ROUNDS` (default `cell_exhaustion.MAX_CELL_ROUNDS_DEFAULT`).
  - `research`: `return self._research_loop(state, issue_id, lambda: sdk_client.call_structured_websearch(_RESEARCH_SYSTEM, self._user_prompt(state, issue_id)[1], _RESEARCH_SCHEMA))`.
  - `research_async`: same loop but round-1 ws via `pool.run_with_retry(...)` when pool given (keep the existing branch); the fetch+extract steps run with `await asyncio.to_thread(fetch_and_extract, ...)`.
  - Keep `_build_bundle` populating sources/claims; the loop appends fetched-doc claims to the SAME bundle so the fan-out + verify see them.
- [ ] **Step 4: verify PASS** — `PYTHONPATH=src py -3 -m pytest tests/test_exhaustion_loop.py -v`.
- [ ] **Step 5: REGRESSION (important)** — `PYTHONPATH=src py -3 -m pytest tests/test_real_brains.py tests/test_loop_real.py tests/test_fanout_concurrency.py tests/test_async_pool.py tests/test_researcher_excerpt.py -q` then full suite. The single-shot tests may now see extra fetch behavior — they mock `call_structured_websearch` returning no doc-URL sources, so the loop does round 1 only (no escalation) and behaves as before. Fix any test that asserted EXACTLY one call by allowing the no-doc-source path to short-circuit (loop exits when no `is_doc_url` source exists). Do NOT weaken behavioral assertions. Full suite green.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/brains/real.py tests/test_exhaustion_loop.py && git commit -m "feat(p9): per-cell evidence-exhaustion loop in RealResearcher (fetch+extract+re-extract)"`.

---

### Task 9: Wire classify-after-exhaustion + needs_internal supplement (§C)

**Files:** Modify `src/cn5_research_cos/graph.py` (`node_collect` ~498 — set cell status from evidence; `_notify_needs_supplement` ~890). Modify `src/cn5_research_cos/synthesis/memo.py` (`route_citations` ~194 — consume cell status). Test: `tests/test_cell_classify_wiring.py`.

- [ ] **Step 1: failing test**:
```python
import cn5_research_cos.graph as g
from cn5_research_cos.models import (ResearchState, TaskGrid, TaskCell, CellStatus,
    EvidenceBundle, Claim, Source, SourceType, SourceQuality)

def test_cell_marked_covered_when_criteria_filled():
    rs = ResearchState(run_id="r", original_question="q", task_grid=TaskGrid())
    rs.task_grid.cells["NXP|fabric"] = TaskCell(id="NXP|fabric", vendor="NXP", spec_group="fabric",
        objective="o", success_criteria=["packet_buffer"])
    # evidence whose claim fills packet_buffer for this cell
    src = Source(id="S1", title="DS", url="https://nxp.com/x.pdf", source_type=SourceType.primary, quality=SourceQuality.high, excerpt="packet buffer 128 kB")
    rs.evidence.append(EvidenceBundle(query="NXP fabric", issue_id="NXP|fabric",
        claims=[Claim(claim="packet_buffer = 128 kB", source_refs=["S1"], confidence=5, notes="packet buffer 128 kB")],
        sources=[src]))
    g.classify_grid_cells(rs)   # new deterministic pass
    assert rs.task_grid.cells["NXP|fabric"].status in (CellStatus.covered, CellStatus.partial)
```
- [ ] **Step 2: verify FAIL** (no `classify_grid_cells`).
- [ ] **Step 3: implement** — add `classify_grid_cells(rs)` to `graph.py`: for each cell, gather evidence bundles whose `issue_id == cell.id` (or whose claims map to the cell), compute `filled` = the set of `success_criteria` field-names that appear (case-insensitive substring) in any verified/cited claim for that cell, detect `gated_detected` from any source flagged gated (a Source whose excerpt/url has a login/register/myICP/401 marker — deterministic helper `_gated_signal(src)`), then `cell.status = cell_exhaustion.classify_cell(cell, filled=filled, gated_detected=gated)`. Call `classify_grid_cells(rs)` at the end of `node_collect`. In `_notify_needs_supplement`, ALSO source the supplement items from cells with `status == CellStatus.blocked` (needs_internal) — build a HumanTask per such cell ("提供內部資料：<vendor> <spec_group>") deduped by id, merged into the once-per-run email. In `route_citations`, when a claim's owning cell is `na`/`blocked`, do NOT re-mint a duplicate supplement (the cell path owns it) — guard by cell status.
- [ ] **Step 4: verify PASS**.
- [ ] **Step 5: regression** — `PYTHONPATH=src py -3 -m pytest tests/test_citation_notify_wiring.py tests/test_memo_assembly.py tests/test_loop.py -q` then full suite. The once-per-run flood guard MUST still hold. Green.
- [ ] **Step 6: commit** — `git add src/cn5_research_cos/graph.py src/cn5_research_cos/synthesis/memo.py tests/test_cell_classify_wiring.py && git commit -m "feat(p9): classify cells after exhaustion; needs_internal cells drive supplement"`.

---

## Final integration
- [ ] **Full regression:** `PYTHONPATH=src py -3 -m pytest -q` → all green (P1–P9).
- [ ] **Final code review** over the P9 diff.
- [ ] **Live (opt-in, clean env — NOT nested):** re-run switch-PK; confirm the NXP SJA1105 row fills packet_buffer=128kB / VLAN=4096 / queues=8 / CBS=10 / AEC-Q100 Grade2 (from the fetched datasheet, not N/A), and only genuinely myICP-locked fields → supplement email.
- [ ] **Do NOT push** without explicit user confirmation.

## Self-review notes
- Spec coverage: §A→T8, §B→T3+T4, §D→T6, §E→T5, §F→T1+T2, §C→T9, §5 invariant→T7 (deterministic gates) + T8 (LLM only extracts). P10 backlog (browser/auth, CBR memory, report self-critique, code-exec, multimodal, multi-perspective) consciously NOT in P9.
- The fan-out scaffolding (`run_research_fanout`/`_research_one_async`/`node_collect`) is preserved; the loop lives inside the researcher, honoring `(state, issue_id[, pool]) -> EvidenceBundle`.
- CellStatus reuse: `na`=public-exhausted, `blocked`=needs_internal (documented in the plan header).
