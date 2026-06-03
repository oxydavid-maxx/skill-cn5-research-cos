"""Multi-format reference -> markdown fragment routing (P5c Component 3).

A file the user drops into ``runs/<run_id>/reference/`` is routed BY EXTENSION to
the right converter, then mapped (by the caller) into the SAME EvidenceBundle shape
as the P4a paperwork path. Deterministic; the only heavy work is the converters.

  * ``.pdf``               -> the paperwork selective PDF pipeline (outline scan ->
                             bounded page range -> pdf2md docling). Large-doc
                             discipline; reuses the tier-2 path.
  * ``.docx``/``.pptx``/``.xlsx`` -> docling DIRECTLY
                             (``DocumentConverter().convert(path).document
                             .export_to_markdown()``). docling natively supports
                             these office formats — they are structured text (no
                             OCR), so a whole-doc convert is fine and fast; no
                             paperwork script needed.
  * ``.html``/``.htm``     -> paperwork ``html2md.py``.
  * ``.md``/``.markdown``/``.txt`` -> read directly.
  * anything else          -> raise ``UnsupportedReferenceError`` (the caller
                             records a coverage_gap + a VISIBLE warning; a dropped
                             file is NEVER silently ignored).
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("cn5_research_cos.reference_intake")

_OFFICE = {".docx", ".pptx", ".xlsx"}
_HTML = {".html", ".htm"}
_TEXT = {".md", ".markdown", ".txt"}


class UnsupportedReferenceError(RuntimeError):
    """A dropped reference file has an extension we do not know how to convert."""


def _docling_converter():
    """Construct a docling ``DocumentConverter`` (imported lazily so the dependency
    is only needed when an office doc is actually dropped; tests monkeypatch this)."""
    from docling.document_converter import DocumentConverter
    return DocumentConverter()


def _office_to_fragment(path: Path) -> str:
    """docling-DIRECT conversion for .docx/.pptx/.xlsx (no paperwork script)."""
    converter = _docling_converter()
    result = converter.convert(str(path))
    return result.document.export_to_markdown()


def _pdf_to_fragment(path: Path, home) -> str:
    """Convert ONE dropped PDF via the paperwork selective pipeline: outline scan
    -> bounded page range(s) -> pdf2md docling. Reuses the tier-2 discipline (never
    a whole-file dump). Returns the concatenated fragment markdown.

    Isolated as a module function so the routing test can monkeypatch it without a
    real paperwork home / docling install."""
    from . import scripts
    home = Path(home)
    pdf = Path(path)
    parts: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cn5_ref_pdf_") as tmp:
        tmpd = Path(tmp)
        outline_out = tmpd / "outline.md"
        scan = scripts.outline_scan(home, pdf, keywords=[], out=outline_out)
        total = scan.get("total_pages") or 1
        # The reference-drop path has no per-issue page-picker LLM; take a bounded
        # leading window (large-doc safe — never the whole file blindly). The
        # paperwork extract/convert enforces the rest.
        pages = "1" if total <= 1 else f"1-{min(total, 10)}"
        subset = tmpd / "subset.pdf"
        frag = tmpd / "frag.md"
        scripts.extract_pages(home, pdf, pages, subset)
        scripts.pdf2md(home, subset, frag, backend="docling")
        if frag.is_file():
            parts.append(frag.read_text(encoding="utf-8"))
    return "\n\n".join(p for p in parts if p)


def _html_to_fragment(path: Path, home) -> str:
    """Convert ONE dropped HTML file via paperwork ``html2md.py``. Isolated so the
    routing test can monkeypatch it."""
    from . import scripts
    return scripts.html2md(Path(home), Path(path))


def convert_to_fragment(path, home) -> str:
    """Route ``path`` by extension to a markdown fragment. Raises
    ``UnsupportedReferenceError`` for an unknown extension (the caller records a
    coverage_gap + warning — a dropped file is never silently ignored)."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _pdf_to_fragment(p, home)
    if suffix in _OFFICE:
        return _office_to_fragment(p)
    if suffix in _HTML:
        return _html_to_fragment(p, home)
    if suffix in _TEXT:
        return p.read_text(encoding="utf-8", errors="replace")
    raise UnsupportedReferenceError(
        f"unsupported reference file extension {suffix!r} for {p.name} "
        f"(supported: .pdf .docx .pptx .xlsx .html .htm .md .markdown .txt)"
    )
