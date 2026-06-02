"""LIVE opt-in tests for the REAL paperwork scripts + page-range brain (P4a).

Gated by BOTH ``CN5_COS_LLM_TESTS=1`` (the live LLM gate, mirrors the rest of
the suite) AND a discoverable paperwork home (``CN5_PAPERWORK_HOME`` set or the
sibling checkout present). Skips cleanly otherwise, so CI without paperwork stays
green.

Why this test is REQUIRED (prior-increment lesson): a live-only subprocess /
encoding / path bug passes the mocked tests — only running the real scripts on a
real PDF catches it. So mocked tests are not sufficient for the tier-2 chain.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cn5_research_cos.brains import internal_doc
from cn5_research_cos.brains.internal_doc import InternalDocResearcher
from cn5_research_cos.brains.paperwork import scripts
from cn5_research_cos.brains.paperwork.locate import find_paperwork_home
from cn5_research_cos.models import EvidenceBundle, IssueStatus, IssueType, ResearchState

_LLM = os.environ.get("CN5_COS_LLM_TESTS") == "1"
_HOME = find_paperwork_home()

pytestmark = pytest.mark.skipif(
    not (_LLM and _HOME is not None),
    reason="set CN5_COS_LLM_TESTS=1 AND a discoverable CN5_PAPERWORK_HOME to run",
)


def _make_pdf(path: Path, pages: list[str]) -> Path:
    """Generate a tiny multi-page text PDF with PyMuPDF (fitz).

    Uses ``insert_textbox`` with multi-line paragraph bodies (NOT a single
    ``insert_text`` line near the top margin): pymupdf4llm's markdown layout
    heuristics drop a lone short line, but reliably capture a proper text block.
    This was a real live-only finding — the mocked tests can't surface it.
    """
    import fitz
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 500, 720), body, fontsize=14,
                            fontname="helv")
    doc.save(str(path))
    doc.close()
    return path


def test_real_scripts_chain(tmp_path):
    # A 4-page PDF with a clearly-locatable target section.
    pdf = tmp_path / "tiny i3c spec.pdf"  # space in path on purpose
    _make_pdf(pdf, [
        "Chapter 1 Introduction\n\nGeneral overview of the bus and its goals.",
        "Chapter 2 Electrical\n\nVoltage levels and timing requirements.",
        "Chapter 3 Dynamic Address Assignment (DAA)\n\nThe controller assigns a "
        "seven bit dynamic address to each target during bus initialization. "
        "DAA replaces static addressing.",
        "Chapter 4 Appendix\n\nReference tables and additional material.",
    ])

    # 1) outline_scan (real)
    out = tmp_path / "outline.md"
    scan = scripts.outline_scan(_HOME, pdf, ["dynamic", "address", "daa"], out=out)
    assert scan["total_pages"] == 4
    assert "Total pages: 4" in scan["text"]

    # 2) extract a bounded page range (real) — pages 3 only (the DAA page)
    subset = tmp_path / "subset.pdf"
    scripts.extract_pages(_HOME, pdf, "3", subset)
    assert subset.is_file() and subset.stat().st_size > 0

    # 3) pdf2md (real, pymupdf4llm)
    frag = tmp_path / "frag.md"
    scripts.pdf2md(_HOME, subset, frag, backend="pymupdf4llm")
    text = frag.read_text(encoding="utf-8")
    assert "Dynamic Address Assignment" in text or "DAA" in text


def test_real_tier2_end_to_end_with_real_brain(tmp_path, monkeypatch):
    """Full tier-2: real scripts + the REAL page-range brain (one cheap LLM call)
    -> a cited EvidenceBundle. The brain must pick a BOUNDED range."""
    pdf = tmp_path / "tiny spec.pdf"
    _make_pdf(pdf, [
        "Chapter 1 Introduction\n\nGeneral overview.",
        "Chapter 2 Dynamic Address Assignment\n\nThe controller assigns a seven "
        "bit dynamic address to each target at bus initialization. DAA replaces "
        "static addressing used by legacy I2C.",
        "Chapter 3 Appendix\n\nReference tables.",
    ])
    # force tier-2: home discoverable, an issue, the PDF passed explicitly.
    monkeypatch.setattr(internal_doc, "find_paperwork_home", lambda **k: _HOME)
    rs = ResearchState(run_id="live", original_question="I3C DAA details")
    from cn5_research_cos.artifacts import issue_map
    iss = issue_map.add(rs, title="dynamic address assignment",
                        description="how DAA assigns addresses",
                        issue_type=IssueType.technical, status=IssueStatus.open,
                        now="t", impact=4, confidence=1)
    bundle = InternalDocResearcher().research(rs, iss.id, pdfs=[pdf])
    assert isinstance(bundle, EvidenceBundle)
    # The real brain should have located the DAA section and produced a cited
    # claim with a verbatim quote. (If the brain returned no range, the bundle
    # records a gap instead — assert one or the other, never fabrication.)
    assert bundle.sources or bundle.coverage_gaps
    if bundle.claims:
        assert bundle.claims[0].notes  # verbatim quote
        assert bundle.claims[0].source_refs
