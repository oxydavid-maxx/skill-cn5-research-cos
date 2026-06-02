"""InternalDocResearcher — internal-document research via paperwork (P4a).

Implements the existing ``Researcher`` Protocol (sync ``research`` + async
``research_async`` for the P2b fan-out) using paperwork's deterministic
``scripts/`` as a toolbox. Three tiers, in order, per issue:

  Tier 1 — CONSUME: a relevant existing paperwork survey (brief
    ``available_sources`` folder) whose ``requirement_topics`` overlap the issue
    (deterministic gate) is read into an EvidenceBundle. Zero PDF processing,
    zero LLM. Non-matching topic -> skip (fall to tier 2 / degrade).

  Tier 2 — GENERATE: for a raw PDF (brief ``internal_documents_available`` /
    ``pdfs=[...]``): outline_scan -> ONE cheap LLM call (the page-range picker)
    -> extract_pages (BOUNDED subset, never whole file) -> pdf2md (pymupdf4llm
    default, docling only when the brain flags table_heavy) -> cited Claims.

  Degrade — if ``find_paperwork_home()`` is None: do NOT fabricate internal
    evidence; return a gap-recording bundle + emit a VISIBLE warning. The
    degraded path is detectable via ``is_degraded(bundle)`` (caller routes to web).

Determinism: tier selection, topic-overlap gate, and assembly are pure Python.
The ONLY LLM is the tier-2 page-range picker (``_pick_page_ranges``).
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from ..llm import sdk_client
from ..models import EvidenceBundle, ResearchState
from .paperwork import evidence_map, scripts
from .paperwork.locate import find_paperwork_home, paperwork_version

logger = logging.getLogger("cn5_research_cos.internal_doc")

# Marker recorded in coverage_gaps when paperwork is unavailable, so the degraded
# bundle is detectable downstream (never silently presented as gathered evidence).
_DEGRADED_GAP = "paperwork unavailable: internal-document research degraded to web"

_PAGE_RANGE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pages": {"type": "string"},
                    "why": {"type": "string"},
                    "role": {"type": "string"},
                    "table_heavy": {"type": "boolean"},
                },
                "required": ["pages", "role"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ranges"],
    "additionalProperties": False,
}

_PAGE_RANGE_SYSTEM = (
    "You select the MINIMAL set of page ranges from a PDF outline that answer ONE "
    "research sub-issue. One job: read the outline/TOC + keyword hits and return "
    "the bounded page range(s) most relevant to the issue — NEVER the whole "
    "document. For each range give pages (e.g. '40-45' or '10,20-25'), a one-line "
    "why, a role (standard|datasheet|application-note|whitepaper|market-report|"
    "internal-research), and table_heavy (true only if that range is dominated by "
    "tables/register maps needing high-fidelity extraction). Return STRICT JSON."
)

# A page spec is a bounded subset iff it is comma/dash separated digits and is
# not an obvious whole-file form. We additionally cap the span defensively.
_PAGES_RE = re.compile(r"^\s*\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*\s*$")


# --------------------------------------------------------------------------- #
# Pure helpers (deterministic, unit-tested)
# --------------------------------------------------------------------------- #
def is_degraded(bundle: EvidenceBundle) -> bool:
    """True iff the bundle is the degraded (paperwork-unavailable) shape."""
    return any(g == _DEGRADED_GAP for g in bundle.coverage_gaps)


def _tokenize(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) > 2}


def _topics_overlap(issue_text: str, requirement_topics: list[str]) -> bool:
    """Deterministic overlap gate: any requirement topic's words appear in the
    issue text (a topic like 'i2c-backward-compatibility' matches if ALL of its
    word-parts appear among the issue tokens)."""
    issue_tokens = _tokenize(issue_text)
    if not issue_tokens:
        return False
    for topic in requirement_topics or []:
        parts = _tokenize(topic)
        if parts and parts <= issue_tokens:
            return True
    return False


def _is_bounded_pages(pages: str) -> bool:
    """Reject empty / non-numeric / whole-file page specs (defense in depth so a
    misbehaving brain can NEVER trigger a whole-PDF extraction)."""
    if not pages or not _PAGES_RE.match(pages):
        return False
    low = pages.strip().lower()
    return low not in ("all", "1-", "-")


def _issue_text(state: ResearchState, issue_id: str) -> tuple[str, str]:
    node = state.issue_map.get(issue_id)
    title = node.title if node else issue_id
    desc = node.description if node and node.description else title
    return title, desc


def _survey_folders(state: ResearchState) -> list[Path]:
    """Paperwork survey folders pointed at by the brief's available_sources (a
    folder containing reference-map.yaml is a survey)."""
    out: list[Path] = []
    for raw in state.available_sources or []:
        p = Path(raw)
        if p.is_dir() and (p / "reference-map.yaml").is_file():
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# Tier-2 LLM seam (the ONLY LLM call) — isolated so tests can scripted-mock it
# --------------------------------------------------------------------------- #
def _pick_page_ranges(outline_text: str, title: str, desc: str) -> list[dict]:
    """ONE cheap LLM call: outline -> bounded page ranges for THIS issue.

    Uses the default (cheap) model via call_structured. Returns the raw
    ``ranges`` list (each {pages, why, role, table_heavy}). Isolated as a
    module function so deterministic tests monkeypatch it directly.
    """
    user = (
        f"SUB-ISSUE:\n{title}\n{desc}\n\n"
        f"PDF OUTLINE / KEYWORD HITS:\n{outline_text}\n\n"
        "Return the minimal bounded page range(s) for this sub-issue."
    )
    raw = sdk_client.call_structured(_PAGE_RANGE_SYSTEM, user, _PAGE_RANGE_SCHEMA)
    ranges = raw.get("ranges", [])
    return ranges if isinstance(ranges, list) else []


# --------------------------------------------------------------------------- #
# Researcher
# --------------------------------------------------------------------------- #
class InternalDocResearcher:
    """Researcher that gathers evidence from internal documents via paperwork."""

    # ---- degrade --------------------------------------------------------- #
    @staticmethod
    def _degraded_bundle(title: str, issue_id: str | None) -> EvidenceBundle:
        logger.warning(
            "paperwork home not found (set CN5_PAPERWORK_HOME or check out "
            "cn5dd2/CN5DD2_common) — internal-document research for %r DEGRADED "
            "to web-only; NO internal evidence fabricated.", title,
        )
        return EvidenceBundle(
            query=title, issue_id=issue_id, claims=[], sources=[],
            coverage_gaps=[_DEGRADED_GAP],
            missing_evidence=[f"internal documents not searched for: {title}"],
        )

    # ---- tier 1 ---------------------------------------------------------- #
    def _tier1_consume(self, state: ResearchState, issue_id: str,
                       title: str, desc: str) -> EvidenceBundle | None:
        import yaml
        for folder in _survey_folders(state):
            try:
                ref_map = yaml.safe_load(
                    (folder / "reference-map.yaml").read_text(encoding="utf-8")
                ) or {}
            except (OSError, yaml.YAMLError):
                continue
            topics = ref_map.get("requirement_topics") or []
            if not _topics_overlap(f"{title} {desc}", topics):
                continue  # non-matching topic -> skip this survey
            bundle = evidence_map.bundle_from_survey(
                folder, issue_id=issue_id, query=title
            )
            if bundle.sources:
                return bundle
        return None

    # ---- tier 2 ---------------------------------------------------------- #
    def _tier2_generate(self, home: Path, state: ResearchState, issue_id: str,
                        title: str, desc: str, pdfs: list[Path]) -> EvidenceBundle:
        sources = []
        claims = []
        coverage_gaps: list[str] = []
        keywords = sorted(_tokenize(f"{title} {desc}"))[:8]

        with tempfile.TemporaryDirectory(prefix="cn5_p4a_") as tmp:
            tmpd = Path(tmp)
            for pi, pdf in enumerate(pdfs):
                pdf = Path(pdf)
                outline_out = tmpd / f"outline_{pi}.md"
                try:
                    scan = scripts.outline_scan(home, pdf, keywords, out=outline_out)
                except scripts.PaperworkScriptError as e:
                    coverage_gaps.append(f"outline_scan failed for {pdf.name}: {e}")
                    continue

                ranges = _pick_page_ranges(scan.get("text", ""), title, desc)
                if not ranges:
                    coverage_gaps.append(
                        f"no relevant page range identified in {pdf.name}"
                    )
                    continue

                for ri, rng in enumerate(ranges):
                    pages = str(rng.get("pages", "")).strip()
                    if not _is_bounded_pages(pages):
                        # NEVER fall back to whole-PDF: record a gap and skip.
                        coverage_gaps.append(
                            f"skipped unbounded/invalid page spec {pages!r} "
                            f"in {pdf.name}"
                        )
                        continue
                    table_heavy = bool(rng.get("table_heavy", False))
                    backend = "docling" if table_heavy else "pymupdf4llm"
                    subset = tmpd / f"subset_{pi}_{ri}.pdf"
                    frag = tmpd / f"frag_{pi}_{ri}.md"
                    try:
                        scripts.extract_pages(home, pdf, pages, subset)
                        scripts.pdf2md(home, subset, frag, backend=backend)
                    except scripts.PaperworkScriptError as e:
                        coverage_gaps.append(
                            f"extract/convert failed for {pdf.name} {pages}: {e}"
                        )
                        continue
                    src, c, g = evidence_map.record_from_fragment(
                        reference_id=f"{pdf.stem}-{pi}-{ri}",
                        title=pdf.name,
                        role=str(rng.get("role", "internal-research")),
                        fragment_path=frag, pages=pages, issue_id=issue_id,
                    )
                    sources.append(src)
                    claims.extend(c)
                    coverage_gaps.extend(g)

        return EvidenceBundle(
            query=title, issue_id=issue_id, claims=claims, sources=sources,
            coverage_gaps=coverage_gaps,
        )

    # ---- orchestration --------------------------------------------------- #
    def _gather(self, state: ResearchState, issue_id: str,
                pdfs: list[Path] | None) -> EvidenceBundle:
        title, desc = _issue_text(state, issue_id)
        home = find_paperwork_home()
        if home is None:
            return self._degraded_bundle(title, issue_id)

        # Tier 1: opportunistic consume of a topic-matching existing survey.
        tier1 = self._tier1_consume(state, issue_id, title, desc)
        if tier1 is not None:
            return tier1

        # Tier 2: generate from raw PDFs (explicit arg, or brief intake).
        candidate_pdfs = list(pdfs or [])
        if not candidate_pdfs:
            candidate_pdfs = self._brief_pdfs(state)
        if candidate_pdfs:
            return self._tier2_generate(
                Path(home), state, issue_id, title, desc, candidate_pdfs
            )

        # Nothing internal applied (no matching survey, no PDFs): record the gap
        # rather than fabricate. Not the paperwork-unavailable degrade shape.
        return EvidenceBundle(
            query=title, issue_id=issue_id, claims=[], sources=[],
            coverage_gaps=[
                f"no internal survey matched and no internal PDF supplied for: {title}"
            ],
            missing_evidence=[f"internal evidence for: {title}"],
        )

    @staticmethod
    def _brief_pdfs(state: ResearchState) -> list[Path]:
        """Raw PDFs declared in the brief's available_sources (a .pdf path or a
        reference/pdf/ folder), used when no explicit pdfs= is passed."""
        out: list[Path] = []
        for raw in state.available_sources or []:
            p = Path(raw)
            if p.is_file() and p.suffix.lower() == ".pdf":
                out.append(p)
            elif p.is_dir():
                out.extend(sorted(p.glob("*.pdf")))
        return out

    # ---- Researcher Protocol -------------------------------------------- #
    def research(self, state: ResearchState, issue_id: str, *,
                 pdfs: list[Path] | None = None) -> EvidenceBundle:
        return self._gather(state, issue_id, pdfs)

    async def research_async(self, state: ResearchState, issue_id: str, *,
                             pool=None, pdfs: list[Path] | None = None) -> EvidenceBundle:
        """Async variant for the fan-out. The internal-doc work is subprocess +
        ONE cheap structured call (no WebSearch), so it runs in a worker thread
        via ``asyncio.to_thread`` — overlapping with sibling researchers without
        driving its own nested event loop inside the running fan-out loop."""
        import asyncio
        return await asyncio.to_thread(self._gather, state, issue_id, pdfs)
