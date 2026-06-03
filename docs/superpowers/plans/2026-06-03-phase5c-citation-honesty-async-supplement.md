# Phase 5c — Citation Honesty + Async Human-Supplement + User Manual Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** a real run that can't verify a critical claim does NOT fabricate — it drops/flags it, emails the user, and CONTINUES; the user supplements (text or document) and resumes; a clear user manual ships in-repo.

**Architecture:** deterministic confidence-routing (cite/drop/notify) replaces the hard citation block; an Outlook-COM email notifier (mirrors daily_brief); a per-run reference folder scanned each iteration with extension-routed conversion (paperwork PDF / docling office / html2md). Spec: `docs/spec/2026-06-03-phase5c-citation-honesty-async-supplement-design.md`. Branch: `p5c-citation-verify-fix` (verify fix already here; do NOT push).

**Invariant:** P1–P5b + the P5c verify fix STAY GREEN — `PYTHONPATH=src py -3 -m pytest -q` after every task.

---

### Task 1: Confidence-based citation policy (cite / drop / notify-critical) — replaces hard block

**Files:** Modify `src/cn5_research_cos/synthesis/memo.py` (`citation_pass` → return a routing result), `src/cn5_research_cos/synthesis/gates.py` (citation gate no longer hard-blocks on unverified-non-fabricated); Test `tests/test_citation_policy_p5c.py`

- [ ] **Step 1: failing test** — `route_citations(state)` returns: verified claims in `cited`; unverified-non-critical in `dropped` (not cited, no task); unverified-critical in `needs_supplement` (each a HumanTask payload) — and creates `HumanTask`s for the critical ones. The memo can still emit (no hard block); unverified-critical surface in "What We Cannot Say"/"Required Human Decisions".
```python
def test_unverified_critical_drops_and_flags_not_blocks(...):
    res = route_citations(state)
    assert claim_v in res.cited
    assert claim_minor in res.dropped
    assert claim_crit.claim in [t.requested_input for t in res.needs_supplement]
    # memo still assembles + can emit (no hard citation block)
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — extend `citation_pass`/add `route_citations`: per claim run flatten→verify (existing) ; classify critical via `risk.classify_pull` criticality; bucket into cited / dropped / needs_supplement; emit `HumanTask`s for needs_supplement. In `gates.py`, the citation gate now refuses ONLY if a needs_supplement item would be presented AS fact — i.e. it does NOT block emission; instead the memo's "cannot say"/"required human decisions" sections carry them (unverified, flagged). Keep degraded-audit gate hard. Pure Python.
- [ ] **Step 4: run → PASS;** full suite green.
- [ ] **Step 5: commit** `feat(p5c): confidence-based citation routing (cite/drop/notify, continue not block)`

---

### Task 2: Email notifier (Outlook COM, mirror daily_brief; fail-soft)

**Files:** Create `src/cn5_research_cos/notify/__init__.py`, `src/cn5_research_cos/notify/email.py`; Test `tests/test_notify_email.py`

- [ ] **Step 1: failing test** — `notify_supplement_needed(run_id, items, base_dir, send=fake)` composes a body containing the run_id, each item's "what's needed", and the copy-paste `cos steer <run_id> "..."` + the `runs/<run_id>/reference/` drop instruction; a send exception is caught + logged (fail-soft) and returns False, never raises.
```python
def test_email_body_has_runid_and_pasteable_commands(...):
    body = build_supplement_email("abc123", items)
    assert "abc123" in body and 'cos steer abc123' in body and "runs/abc123/reference/" in body
def test_send_failure_is_fail_soft(...):
    assert notify_supplement_needed("abc123", items, tmp, send=boom) is False  # no raise
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — `build_supplement_email(run_id, items) -> str` (pure, the body); `notify_supplement_needed(...)` calls a `send` callable (default = a win32com Outlook send mirroring `daily_brief/publishers/email_sender.py`: `win32com.client.Dispatch("Outlook.Application")`, `CreateItem(0)`, set `.To`/`.Subject`/`.Body`, `.Send()`); wrap send in try/except → log a VISIBLE warning + return False on failure. Recipient configurable (default self). The win32com import is inside the default-send function so tests (passing a fake `send`) need no Outlook.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p5c): Outlook-COM supplement-needed email notifier (fail-soft)`

---

### Task 3: Wire notify into the citation policy

**Files:** Modify `src/cn5_research_cos/graph.py` (after `route_citations`, if `needs_supplement` non-empty → `notify_supplement_needed`); Test `tests/test_citation_notify_wiring.py`

- [ ] **Step 1: failing test** — a mock loop where a critical claim is unverified → the (mocked) notifier is called once with the run_id + items, the loop CONTINUES (does not pause/stop), and a HumanTask exists.
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — in the synthesize/citation step, when `needs_supplement` is non-empty, call `notify_supplement_needed(...)` (inject the notifier; default real, fake in tests). Loop continues. Idempotent: don't re-email the same item every iteration (track notified item keys on state).
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p5c): notify user on unverified-critical (continue, idempotent)`

---

### Task 4: Multi-format reference intake (per-run folder scan + extension routing)

**Files:** Create `src/cn5_research_cos/brains/paperwork/convert.py` (route a path → markdown fragment); Modify `src/cn5_research_cos/brains/internal_doc.py` (scan `runs/<run_id>/reference/`, dedup, route); Test `tests/test_reference_intake.py`

- [ ] **Step 1: failing test** — `convert_to_fragment(path, home)` routes by suffix: `.pdf`→paperwork pdf pipeline (mock), `.docx`/`.pptx`/`.xlsx`→docling-direct (mock), `.html`→html2md (mock), `.md`→read direct, unknown→raises/records gap. `scan_reference_folder(state)` lists NEW files (dedup by name+mtime), processes each once (second scan of an unchanged folder yields nothing new).
```python
def test_routes_by_extension(...): ...
def test_unknown_extension_records_gap_not_silent(...): ...
def test_dedup_processes_each_file_once(...): ...
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — `convert.convert_to_fragment(path, home)`: `.pdf`→existing `InternalDocResearcher` tier-2 PDF path (outline→range→`pdf2md docling`); `.docx/.pptx/.xlsx`→call docling's `DocumentConverter().convert(path).document.export_to_markdown()` directly (docling natively supports these — no paperwork script); `.html`→paperwork `html2md.py`; `.md/.txt`→`read_text`; else→record coverage_gap + visible warning. `internal_doc.scan_reference_folder(state)`: glob `runs/<run_id>/reference/`, dedup via a processed-set on state (name+mtime), convert new files → fragments → `EvidenceBundle` (same mapping). Wire the scan into the internal-doc research step in `graph.py`.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `feat(p5c): multi-format reference intake (pdf/docx/pptx/xlsx/html/md), per-run scan`

---

### Task 5: USER MANUAL (in-repo, clear)

**Files:** Create `README.md` (or `docs/USER-MANUAL.md` + link from README); Test `tests/test_user_manual.py` (a structural test — manual exists + covers the key sections)

- [ ] **Step 1: failing test** — assert `README.md` (or USER-MANUAL.md) exists and contains the required section anchors: cockpit overview, setup (`CN5_PAPERWORK_HOME`), running (`cos clarify`/`cos run`/`cos run-auto`/`cos show`), live debate stream, the async-supplement flow (`cos steer`, `runs/<run_id>/reference/`, PDF/PPT/Word/Excel), the §22 memo + gates, and the paperwork dependency note.
```python
def test_user_manual_covers_required_sections():
    txt = Path("README.md").read_text(encoding="utf-8")
    for anchor in ["cos run", "cos steer", "runs/", "reference/", "PPT", "Word", "§22", "CN5_PAPERWORK_HOME"]:
        assert anchor in txt or anchor.lower() in txt.lower()
```
- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** — write a clear, plain-language `README.md` per the spec's Component 4: overview, setup, running, watching the live debate, the async-supplement flow (text via `cos steer`; document via drop-in-`runs/<run_id>/reference/` + `cos steer`, listing PDF/PPT/Word/Excel/HTML), the §22 memo + what each gate means (unverified-critical surfaced, never faked), and the gerrit/paperwork-v7 note. Copy-paste examples throughout.
- [ ] **Step 4: run → PASS;** suite green.
- [ ] **Step 5: commit** `docs(p5c): clear in-repo user manual (run, watch debate, async supplement)`

---

### Task 6: Live test (opt-in) — honest no-fabrication + continue + notify

**Files:** `tests/test_memo_live.py` (extend) or a new `tests/test_supplement_live.py`

- [ ] **Step 1:** opt-in live test: a real run; assert no fabrication (every cited memo claim is verified; unverified-critical appear only in cannot-say/required-decisions, never as fact), the loop did NOT pause on it (continued), and a notification was attempted (mock the sender to record). `@pytest.mark.llm`, skips cleanly. Controller runs it.
- [ ] **Step 2: commit** `test(p5c): live honest-no-fabrication + continue + notify (opt-in)`

---

## Self-Review
- **Spec coverage:** ✅ confidence policy (T1), email notify (T2) + wiring (T3), multi-format intake (T4), user manual (T5), live (T6).
- **Placeholder scan:** none — concrete tests + the real docling/win32com/paperwork calls named.
- **Type consistency:** `route_citations(state)` result (T1) consumed by gates + notify-wiring (T3); `convert_to_fragment(path, home)` (T4) used by `scan_reference_folder`; `notify_supplement_needed(run_id, items, base_dir, send=)` signature stable across T2/T3.
