# Phase 5c — citation honesty + async human-supplement + user manual (design)

> 2026-06-03. Decided via multi-round discussion. Triggered by the P5 live run: the citation gate blocked the memo on real web claims. Root cause (verified): (bug #2 dominant) the researcher captured no per-claim verbatim quote → verify fell back to the paraphrased claim text → never matched a source; (bug #1 fragility) the verify metric was a full-string ratio, thin-margin/autojunk-vulnerable. The verify-mechanism fix is DONE (committed on `p5c-citation-verify-fix`). This spec covers the rest: the confidence-based citation policy, async human-supplement (notify → come back → resume), multi-format reference intake, and a clear in-repo USER MANUAL. Builds on P5/P5b (merged), P3 (HITL checkpoint + `cos steer/resume`), P4a (paperwork intake). DoD: a real run that can't verify a critical claim does NOT fabricate, notifies the user, CONTINUES, and the user can asynchronously supplement (text or document) and resume.

## Component 1 — Confidence-based citation policy (user directive 2026-06-03)
Replace the hard "any unverified KEY claim → block whole memo" with the user's policy. Per claim, after the (now-fixed) verbatim verify:
- **confidence ≥ 85% (verified) → CITE it, continue.**
- **confidence < 85%, NOT critical → do NOT cite it (drop from the cited set), continue.** (No fabrication; the claim simply isn't presented as evidence.)
- **confidence < 85% AND critical (decision-critical: high `impact` / linked to `decision_criterion`, reuse `risk.classify_pull` criticality) → do NOT cite it, create a `HumanTask` ("supplement X to verify"), NOTIFY the user (email), and CONTINUE other branches** (never block/deadlock; H3 push-human is non-blocking).
- The loop NEVER stops to wait for the human on this. The memo can still emit; unverified-critical items are surfaced in "What We Cannot Say" / "Required Human Decisions" with a clear "needs human supplement" flag — NOT presented as verified fact.
- (Supersedes the earlier "hard block" — the considered policy is continue-and-notify, not block-and-wait.)
- The "85%" maps to the existing verbatim-verify pass (web ≥0.85 quote-coverage) + the claim/source confidence; reuse the verify result + `risk.classify_pull`, no new magic number beyond the existing 0.85.

## Component 2 — Email notification (reuse daily_brief's proven Outlook-COM send)
A small `notify/email.py` in THIS repo (mirror the proven win32com Outlook pattern from `daily_brief/publishers/email_sender.py` — do NOT cross-import the sibling project; no SMTP/IMAP/Graph). `notify_supplement_needed(run_id, items, base_dir)` composes + sends (to self / a configurable recipient) an email containing: the `run_id`, WHAT is needed (each unverified-critical claim + what data would verify it), and COPY-PASTE-READY commands:
- text supplement: `cos steer <run_id> "<your answer>"`
- document supplement: drop the file into `runs/<run_id>/reference/` then `cos steer <run_id> "added <filename>"`
Requires the user's Outlook running on the same Windows box (true — the cockpit is terminal-run on that box). Fail-soft: if Outlook send fails, log a VISIBLE warning + still record the HumanTask (never silently swallow); the user can still see the need via `cos show`.

## Component 3 — Multi-format reference intake (close the raw-doc gap)
Today the internal-doc researcher takes an explicit `pdfs=[...]` / scans paperwork survey folders, but does NOT scan a raw drop-folder, and handles ONLY PDF. Add:
- **A per-run reference folder `runs/<run_id>/reference/`** that the internal-doc researcher SCANS each iteration for NEW documents (dedup by filename+mtime so a file is processed once).
- **Route by extension (verified support):**
  - `.pdf` → paperwork selective pipeline (`pdf_outline_scan` → page-range pick → `pdf2md --backend docling`) — the large-doc discipline.
  - `.docx` / `.pptx` / `.xlsx` → **docling directly** (docling natively supports these — `InputFormat` confirmed; office docs are structured-text, no OCR, whole-doc convert is fine and fast).
  - `.html` → paperwork `html2md.py`.
  - `.md` / `.txt` → read directly.
  - unsupported extension → record a coverage_gap + a VISIBLE warning (never silently ignore a dropped file).
  - → markdown fragment → the SAME `EvidenceBundle` mapping (sources/claims/excerpt/quote) as P4a.
- This is the shared ingest point BOTH the terminal path (v1: human drops the file) and the future email path (v2: attachment auto-saved here) feed into.

## Component 4 — USER MANUAL (in-repo, clear — user directive "user manual at github 要寫清楚")
`README.md` (or `docs/USER-MANUAL.md` linked from README) covering, in plain language with copy-paste examples:
- **What the cockpit is** (continuous, audit-driven, human-steered BU research loop — not a one-shot bot).
- **Setup**: gerrit `CN5_PAPERWORK_HOME` checkout; Python deps; how to run.
- **Running**: `cos clarify` (SOT brief) → `cos run` / `cos run-auto` (the loop, with the live per-stage debate stream visible on screen — P5b); `cos show <run_id>`; `cos brief <run_id>`.
- **Watching the debate live** (P5b): the per-stage summary incl. Albert's full challenges streams to your terminal; it survives pipe/redirect.
- **The async-supplement flow** (the key new section): when a critical claim can't be verified, the cockpit does NOT fabricate — it emails you, records a HumanTask, and CONTINUES. To supplement: **(text)** `cos steer <run_id> "<answer>"`; **(document — PDF/PPT/Word/Excel/HTML)** drop the file into `runs/<run_id>/reference/` then `cos steer <run_id> "added <file>"`. The next iteration re-researches/re-verifies. (v2 note: replying to the email with an attachment will auto-ingest — planned.)
- **The §22 memo** (P5): the 9 sections; what each gate means; that unverified-critical items appear in "What We Cannot Say / Required Human Decisions", never as fact.
- **Gerrit dependency + paperwork v7 docling-strict** note (for maintainers).

## Modules
- (DONE) `citation/verify.py` quote-coverage fix.
- `synthesis/memo.py` + `synthesis/gates.py`: apply the confidence policy (cite/drop/notify) instead of hard-block; surface unverified-critical into the memo sections + HumanTasks.
- `notify/email.py`: Outlook-COM send (mirror daily_brief).
- `brains/internal_doc.py` (+ a small `brains/paperwork/convert.py` for the docling-direct / html2md routing): the per-run reference folder scan + multi-format routing.
- `graph.py`: wire the reference-folder scan into the internal-doc research step; wire notify into the citation policy.
- `README.md` / `docs/USER-MANUAL.md`.

## Deterministic-vs-LLM split
- Deterministic: the confidence routing (cite/drop/notify), the reference scan + extension routing, the email composition, the manual. No new LLM.
- LLM: unchanged (researcher now returns per-claim quote — already in the verify fix).

## Tests / DoD
- **Deterministic:** confidence policy — verified→cited; unverified-non-critical→dropped (not in cited set, no HumanTask); unverified-critical→not cited + HumanTask created + notify called (mock the email sender) + loop continues. Reference intake — a `.pdf` routes to the paperwork pipeline, a `.docx`/`.pptx` routes to docling-direct, `.html` to html2md, unknown ext → coverage_gap + warning (mock the converters; assert routing + dedup-by-filename). Email — `notify_supplement_needed` composes the run_id + copy-paste commands (mock win32com; assert content + fail-soft on send error). The memo emits with unverified-critical surfaced in the right sections, never as fact.
- **Regression:** P1–P5b + the P5c verify fix all STAY GREEN.
- **Live (opt-in):** a real run where a critical claim is unverified → no fabrication + a HumanTask + (mock-or-real) notification + the loop continues; the live debate stream shows it. (Controller runs.)
- **Manual review:** the README/USER-MANUAL reads clearly for a colleague (the controller eyeballs it).
- Committed; push on user confirmation.

## Out of scope (v2 / later)
- Email reply + attachment auto-ingest (v2 — reuse daily_brief `get_unread_emails` + win32com attachment save into `runs/<run_id>/reference/` + auto-resume; polling). Defer.
- Real external Albert (P6); packaging (P6).
