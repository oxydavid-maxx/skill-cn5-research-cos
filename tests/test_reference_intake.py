"""Phase 5c Task 4 — multi-format reference intake (per-run folder scan + routing).

``convert.convert_to_fragment(path, home)`` routes a dropped reference file by
extension to a markdown fragment:
  * .pdf                -> the paperwork selective PDF pipeline (mocked here);
  * .docx/.pptx/.xlsx   -> docling DIRECTLY (DocumentConverter, mocked here);
  * .html               -> paperwork html2md (mocked here);
  * .md/.txt            -> read directly;
  * unknown extension   -> records a coverage_gap + a VISIBLE warning (NEVER
                           silently ignores a dropped file).

``internal_doc.scan_reference_folder(state)`` scans ``runs/<run_id>/reference/``
each iteration, dedups by filename+mtime (a file is processed once), and converts
NEW files into EvidenceBundles. A second scan of an unchanged folder yields nothing
new.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cn5_research_cos.brains import internal_doc
from cn5_research_cos.brains.paperwork import convert
from cn5_research_cos.models import ResearchState


# --------------------------------------------------------------------------- #
# convert_to_fragment — extension routing
# --------------------------------------------------------------------------- #
def test_md_and_txt_read_directly(tmp_path):
    md = tmp_path / "note.md"
    md.write_text("# Heading\n\nsome internal note content.", encoding="utf-8")
    frag = convert.convert_to_fragment(md, home=None)
    assert "some internal note content" in frag

    txt = tmp_path / "raw.txt"
    txt.write_text("plain text evidence", encoding="utf-8")
    assert "plain text evidence" in convert.convert_to_fragment(txt, home=None)


def test_office_docs_route_to_docling_direct(tmp_path, monkeypatch):
    seen = {}

    class _FakeDoc:
        def export_to_markdown(self):
            return "docling markdown for office doc"

    class _FakeResult:
        document = _FakeDoc()

    class _FakeConverter:
        def convert(self, path):
            seen["path"] = str(path)
            return _FakeResult()

    monkeypatch.setattr(convert, "_docling_converter", lambda: _FakeConverter())

    for ext in (".docx", ".pptx", ".xlsx"):
        f = tmp_path / f"deck{ext}"
        f.write_bytes(b"binary")
        frag = convert.convert_to_fragment(f, home=None)
        assert "docling markdown for office doc" in frag
        assert seen["path"].endswith(ext)


def test_pdf_routes_to_paperwork_pipeline(tmp_path, monkeypatch):
    called = {}

    def fake_pdf(path, home):
        called["pdf"] = str(path)
        return "pdf md"

    monkeypatch.setattr(convert, "_pdf_to_fragment", fake_pdf)
    f = tmp_path / "spec.pdf"
    f.write_bytes(b"%PDF-1.4")
    frag = convert.convert_to_fragment(f, home="HOME")
    assert frag == "pdf md"
    assert called["pdf"].endswith(".pdf")


def test_html_routes_to_html2md(tmp_path, monkeypatch):
    monkeypatch.setattr(convert, "_html_to_fragment",
                        lambda path, home: "html md")
    f = tmp_path / "page.html"
    f.write_text("<h1>x</h1>", encoding="utf-8")
    assert convert.convert_to_fragment(f, home="HOME") == "html md"


def test_unknown_extension_raises_coverage_gap(tmp_path):
    f = tmp_path / "mystery.xyz"
    f.write_bytes(b"???")
    with pytest.raises(convert.UnsupportedReferenceError):
        convert.convert_to_fragment(f, home=None)


# --------------------------------------------------------------------------- #
# scan_reference_folder — per-run scan, dedup, route, EvidenceBundle mapping
# --------------------------------------------------------------------------- #
def _state_with_reference(tmp_path) -> tuple[ResearchState, Path]:
    rs = ResearchState(run_id="run-1", original_question="q")
    ref = tmp_path / "run-1" / "reference"
    ref.mkdir(parents=True)
    return rs, ref


def test_scan_routes_and_builds_bundles(tmp_path):
    rs, ref = _state_with_reference(tmp_path)
    (ref / "a.md").write_text("dropped markdown evidence about i3c", encoding="utf-8")
    (ref / "b.txt").write_text("another dropped note", encoding="utf-8")

    bundles = internal_doc.scan_reference_folder(rs, base_dir=str(tmp_path))
    assert len(bundles) == 2
    # each bundle maps to internal-origin sources + a cited claim (EvidenceBundle)
    all_sources = [s for b in bundles for s in b.sources]
    assert all_sources and all(s.origin == "internal" for s in all_sources)
    quotes = [c.notes for b in bundles for c in b.claims]
    assert any("dropped markdown evidence" in q for q in quotes)


def test_scan_dedups_each_file_once(tmp_path):
    rs, ref = _state_with_reference(tmp_path)
    (ref / "a.md").write_text("dropped markdown evidence", encoding="utf-8")

    first = internal_doc.scan_reference_folder(rs, base_dir=str(tmp_path))
    assert len(first) == 1
    # a second scan of an UNCHANGED folder yields nothing new (dedup by name+mtime)
    second = internal_doc.scan_reference_folder(rs, base_dir=str(tmp_path))
    assert second == []


def test_scan_unknown_extension_records_gap_not_silent(tmp_path):
    rs, ref = _state_with_reference(tmp_path)
    (ref / "weird.xyz").write_bytes(b"???")
    bundles = internal_doc.scan_reference_folder(rs, base_dir=str(tmp_path))
    # the dropped file is NOT silently ignored: a coverage_gap is recorded.
    gaps = [g for b in bundles for g in b.coverage_gaps]
    assert any("weird.xyz" in g for g in gaps)


def test_scan_missing_folder_is_noop(tmp_path):
    rs = ResearchState(run_id="run-none", original_question="q")
    assert internal_doc.scan_reference_folder(rs, base_dir=str(tmp_path)) == []
