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

    def fake_pdf2md(home_, subset, out, *, backend="pymupdf4llm"):
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
    # default backend pymupdf4llm (not table-heavy)
    assert capture["backends"] == ["pymupdf4llm"]


def test_tier2_docling_only_when_table_heavy(monkeypatch, tmp_path):
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
    # first range pymupdf4llm, the table-heavy range docling
    assert capture["backends"] == ["pymupdf4llm", "docling"]


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
