"""InternalDocResearcher tests (P4a Task 4) — deterministic, mock LLM + subprocess.

Covers: degrade (home None -> gap bundle + visible warning, NOT faked),
tier-1 consume + topic-overlap gate (match consumes / non-match skips),
tier-2 generate (scripts mocked + scripted page-range brain -> deterministic
bundle), bounded-subset assertion (never whole-PDF), docling-only-on-table-heavy.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cn5_research_cos.brains import internal_doc
from cn5_research_cos.brains.internal_doc import InternalDocResearcher
from cn5_research_cos.models import (EvidenceBundle, IssueStatus, IssueType,
                                     ResearchState, SourceType)

SURVEY = Path(__file__).parent / "fixtures" / "paperwork-survey"


def _state(question="I3C vs I2C for an automotive switch", **kw) -> ResearchState:
    rs = ResearchState(run_id="r", original_question=question)
    for k, v in kw.items():
        setattr(rs, k, v)
    return rs


def _issue(rs, title, itype=IssueType.technical):
    from cn5_research_cos.artifacts import issue_map
    return issue_map.add(rs, title=title, description=title, issue_type=itype,
                         status=IssueStatus.open, now="t", impact=4, confidence=1)


def test_satisfies_researcher_protocol():
    from cn5_research_cos.brains import interfaces
    assert isinstance(InternalDocResearcher(), interfaces.Researcher)


# --------------------------------------------------------------------------- #
# Degrade
# --------------------------------------------------------------------------- #
def test_degrade_when_home_none(monkeypatch, caplog):
    monkeypatch.setattr(internal_doc, "find_paperwork_home", lambda **k: None)
    rs = _state()
    iss = _issue(rs, "I3C backward compatibility")
    with caplog.at_level(logging.WARNING):
        bundle = InternalDocResearcher().research(rs, iss.id)
    assert isinstance(bundle, EvidenceBundle)
    # NOT faked: no internal sources/claims invented
    assert bundle.sources == []
    assert bundle.claims == []
    # the gap is recorded + detectable
    assert any("paperwork" in g.lower() for g in bundle.coverage_gaps)
    assert internal_doc.is_degraded(bundle) is True
    # a VISIBLE warning was emitted
    assert any("paperwork" in r.message.lower() for r in caplog.records)


# --------------------------------------------------------------------------- #
# Tier 1 — consume (topic-overlap gate)
# --------------------------------------------------------------------------- #
def test_tier1_consume_on_topic_match(monkeypatch):
    monkeypatch.setattr(internal_doc, "find_paperwork_home", lambda **k: SURVEY.parent)
    rs = _state()
    # brief points at the survey folder + the issue topic overlaps requirement_topics
    rs.available_sources = [str(SURVEY)]
    iss = _issue(rs, "i2c-backward-compatibility and dynamic-address-assignment")
    bundle = InternalDocResearcher().research(rs, iss.id)
    assert isinstance(bundle, EvidenceBundle)
    assert bundle.sources, "tier-1 should produce sources from the survey"
    assert any(s.source_type == SourceType.standard for s in bundle.sources)
    assert bundle.claims and all(c.notes for c in bundle.claims)
    assert internal_doc.is_degraded(bundle) is False


def test_paperwork_version_stamped_into_provenance(monkeypatch):
    # When paperwork actually produces evidence, the resolved plugin version is
    # stamped into the bundle (detectable in run metadata, per spec preflight).
    home = Path(__file__).parent / "fixtures" / "paperwork-home"
    monkeypatch.setattr(internal_doc, "find_paperwork_home", lambda **k: home)
    rs = _state()
    rs.available_sources = [str(SURVEY)]
    iss = _issue(rs, "i2c-backward-compatibility")
    bundle = InternalDocResearcher().research(rs, iss.id)
    assert any("paperwork" in s.lower() and "9.9.9-test" in s
               for s in bundle.suggested_followups)


def test_tier1_skips_on_topic_mismatch(monkeypatch):
    # No PDFs available either -> non-matching topic falls through to a degrade-
    # shaped (gap-recording) bundle rather than fabricating from a survey whose
    # requirement_topics do not overlap.
    monkeypatch.setattr(internal_doc, "find_paperwork_home", lambda **k: SURVEY.parent)
    rs = _state(question="quantum cryptography roadmap")
    rs.available_sources = [str(SURVEY)]
    iss = _issue(rs, "post-quantum key exchange")
    bundle = InternalDocResearcher().research(rs, iss.id)
    # survey did not match -> no survey-derived sources
    assert all("mipi-i3c" not in s.id for s in bundle.sources)
    # records that internal docs did not cover this issue
    assert bundle.coverage_gaps


def test_topic_overlap_gate_pure():
    # deterministic overlap: issue text tokens vs requirement_topics
    topics = ["i2c-backward-compatibility", "dynamic-address-assignment", "ibi"]
    assert internal_doc._topics_overlap("i2c backward compatibility check", topics)
    assert internal_doc._topics_overlap("need dynamic address assignment", topics)
    assert not internal_doc._topics_overlap("unrelated marketing spend", topics)


# --------------------------------------------------------------------------- #
# Tier 2 — generate (mocked scripts + scripted page-range brain)
# --------------------------------------------------------------------------- #
def _wire_tier2(monkeypatch, tmp_path, *, brain_ranges, capture):
    """Mock find_home, scripts.*, and the page-range brain for a tier-2 run."""
    home = tmp_path / "home"
    (home / "scripts").mkdir(parents=True)
    monkeypatch.setattr(internal_doc, "find_paperwork_home", lambda **k: home)

    def fake_outline(home_, pdf, keywords, *, out):
        return {"text": "# Outline\nTotal pages: 600\n", "total_pages": 600,
                "out": Path(out)}

    def fake_extract(home_, pdf, pages, out):
        capture["pages"] = pages
        Path(out).write_bytes(b"%PDF-subset")
        return Path(out)

    def fake_pdf2md(home_, subset, out, *, backend="docling", **kw):
        capture.setdefault("backends", []).append(backend)
        Path(out).write_text(
            "# §4 DAA\nDynamic Address Assignment assigns a 7-bit dynamic "
            "address to each I3C target at bus initialization.\n",
            encoding="utf-8")
        return Path(out)

    monkeypatch.setattr(internal_doc.scripts, "outline_scan", fake_outline)
    monkeypatch.setattr(internal_doc.scripts, "extract_pages", fake_extract)
    monkeypatch.setattr(internal_doc.scripts, "pdf2md", fake_pdf2md)
    # scripted page-range brain (the ONLY LLM call) -> canned ranges
    monkeypatch.setattr(internal_doc, "_pick_page_ranges",
                        lambda *a, **k: brain_ranges)


def test_tier2_generate_bounded_subset(monkeypatch, tmp_path):
    capture = {}
    pdf = tmp_path / "renesas i3c um.pdf"  # space in path
    pdf.write_bytes(b"%PDF-1.4")
    _wire_tier2(monkeypatch, tmp_path, capture=capture, brain_ranges=[
        {"pages": "40-45", "why": "DAA section", "role": "datasheet",
         "table_heavy": False},
    ])
    rs = _state()
    rs.internal_documents_available = True
    iss = _issue(rs, "dynamic address assignment details")
    bundle = InternalDocResearcher().research(rs, iss.id, pdfs=[pdf])

    assert isinstance(bundle, EvidenceBundle)
    assert bundle.sources and bundle.claims
    assert bundle.claims[0].notes  # verbatim quote
    # BOUNDED SUBSET: the extracted pages are NOT the whole 600-page PDF
    assert capture["pages"] == "40-45"
    assert capture["pages"] not in ("1-600", "1-", "all")
    # docling is the fragment-of-record backend (paperwork v7.0.1+ docling-strict)
    assert capture["backends"] == ["docling"]


def test_tier2_always_uses_docling_regardless_of_table_heavy(monkeypatch, tmp_path):
    # paperwork v7.0.1+: docling is the ONLY valid backend for citable fragments.
    # The old "pymupdf4llm default, docling on table_heavy" inversion is gone —
    # docling is used for EVERY range, table_heavy or not.
    capture = {}
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    _wire_tier2(monkeypatch, tmp_path, capture=capture, brain_ranges=[
        {"pages": "10-12", "why": "plain", "role": "standard", "table_heavy": False},
        {"pages": "50-52", "why": "register map table", "role": "standard",
         "table_heavy": True},
    ])
    rs = _state()
    rs.internal_documents_available = True
    iss = _issue(rs, "register map")
    InternalDocResearcher().research(rs, iss.id, pdfs=[pdf])
    # BOTH ranges use docling — never pymupdf4llm (forbidden for fragment-of-record)
    assert capture["backends"] == ["docling", "docling"]
    assert "pymupdf4llm" not in capture["backends"]


def test_tier2_never_extracts_whole_pdf_even_if_brain_misbehaves(monkeypatch, tmp_path):
    capture = {}
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    # brain returns an empty/garbage range -> the researcher must NOT fall back
    # to whole-file extraction; it records a gap instead.
    _wire_tier2(monkeypatch, tmp_path, capture=capture, brain_ranges=[])
    rs = _state()
    rs.internal_documents_available = True
    iss = _issue(rs, "anything")
    bundle = InternalDocResearcher().research(rs, iss.id, pdfs=[pdf])
    # no extraction happened (no pages captured) and a gap is recorded
    assert "pages" not in capture
    assert bundle.coverage_gaps


# --------------------------------------------------------------------------- #
# Silent-degradation regression: a SCRIPT/CONFIG error must NOT be masked as a
# benign "no relevant content" gap (silent-staleness / degraded-emission lesson).
# --------------------------------------------------------------------------- #
def test_tier2_script_error_surfaces_distinct_extraction_failure(monkeypatch, tmp_path, caplog):
    """When scripts.pdf2md raises PaperworkScriptError (e.g. the v7 docling-strict
    policy exit-2, or a tool failure), tier-2 must record a DISTINCT extraction-
    FAILURE marker (detectable), log a VISIBLE warning, and fabricate NOTHING —
    not swallow it into an indistinguishable benign content gap.

    FAILS on the old behavior (a plain "extract/convert failed …" content-style
    gap with no distinct marker / no warning); PASSES after the fix.
    """
    capture = {}
    pdf = tmp_path / "renesas i3c um.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    _wire_tier2(monkeypatch, tmp_path, capture=capture, brain_ranges=[
        {"pages": "40-45", "why": "DAA section", "role": "datasheet",
         "table_heavy": False},
    ])

    # Override pdf2md to raise the v7 policy error (the live regression).
    def boom_pdf2md(home_, subset, out, *, backend="docling", **kw):
        raise internal_doc.scripts.PaperworkScriptError(
            "pdf2md.py exited 2: backend_policy=docling-strict forbids "
            "--backend pymupdf4llm for fragment-of-record output."
        )
    monkeypatch.setattr(internal_doc.scripts, "pdf2md", boom_pdf2md)

    rs = _state()
    rs.internal_documents_available = True
    iss = _issue(rs, "dynamic address assignment details")
    with caplog.at_level(logging.WARNING):
        bundle = InternalDocResearcher().research(rs, iss.id, pdfs=[pdf])

    assert isinstance(bundle, EvidenceBundle)
    # 1) NO fabrication: a tool failure produced no real evidence.
    assert bundle.sources == []
    assert bundle.claims == []
    # 2) A DISTINCT extraction-FAILURE marker (not a benign content gap). The
    # bundle must be detectable as an extraction failure, naming the pdf + reason.
    assert internal_doc.has_extraction_failure(bundle) is True
    fail_gaps = [g for g in bundle.coverage_gaps if "extraction FAILED" in g]
    assert fail_gaps, "must record a distinctly-named extraction FAILURE gap"
    assert any("renesas i3c um.pdf" in g for g in fail_gaps)
    assert any("docling-strict" in g or "exited 2" in g for g in fail_gaps)
    # 3) It is NOT the indistinguishable benign-gap shape.
    assert not any(g.startswith("no relevant page range") for g in bundle.coverage_gaps)
    # 4) A VISIBLE warning/error was logged.
    assert any(
        r.levelno >= logging.WARNING and "extraction" in r.message.lower()
        for r in caplog.records
    ), "a visible warning naming the extraction failure must be logged"


def test_has_extraction_failure_false_on_benign_content_gap():
    # A genuine "found nothing" gap is NOT an extraction failure — the predicate
    # must distinguish a tool/config error from genuinely-empty content.
    benign = EvidenceBundle(
        query="q", issue_id="i", claims=[], sources=[],
        coverage_gaps=["no relevant page range identified in spec.pdf"],
    )
    assert internal_doc.has_extraction_failure(benign) is False


# --------------------------------------------------------------------------- #
# Async variant (fan-out path)
# --------------------------------------------------------------------------- #
def test_research_async_matches_sync(monkeypatch):
    import asyncio
    monkeypatch.setattr(internal_doc, "find_paperwork_home", lambda **k: None)
    rs = _state()
    iss = _issue(rs, "topic")
    bundle = asyncio.run(InternalDocResearcher().research_async(rs, iss.id, pool=None))
    assert isinstance(bundle, EvidenceBundle)
    assert internal_doc.is_degraded(bundle)
