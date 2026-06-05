"""P9 §B — multi-backend document extraction with fallback. Fail-visible
(returns ("","none")), never raises.

Backend order (live-tuned 2026-06-05): pymupdf4llm -> pypdf. ``pymupdf4llm`` is
purpose-built for LLM-grade markdown and extracted a real 80-page datasheet
cleanly (292 kB) where ``docling`` HARD-CRASHED the interpreter with a native
``std::bad_alloc``/SIGSEGV. A segfault is NOT a Python exception, so the
``try/except`` below can NOT catch it — running docling first meant the whole
process died before the fallback could engage. docling is therefore OPT-IN
(``CN5_COS_USE_DOCLING=1``); when enabled it is tried FIRST for its richer
markdown, but the robust pymupdf4llm/pypdf path is the default so the fallback
chain actually falls back. (If docling is enabled in a memory-constrained env it
should be subprocess-isolated so its native crash is contained — future hardening.)
"""
from __future__ import annotations
import logging
import os
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


def _chain() -> tuple[tuple[str, str], ...]:
    """The backend chain. docling is OPT-IN (it can SIGSEGV the process, which the
    fallback try/except can't catch) — only prepended when CN5_COS_USE_DOCLING is set."""
    base = (("pymupdf4llm", "_extract_pymupdf4llm"), ("pypdf", "_extract_pypdf"))
    if os.environ.get("CN5_COS_USE_DOCLING"):
        return (("docling", "_extract_docling"),) + base
    return base


def extract_doc(path: str) -> tuple[str, str]:
    """Return (text, backend_used). Tries each backend in order; ("","none") if all
    fail (visible gap). Looks the private extractors up via ``globals()`` at call
    time so tests can monkeypatch them."""
    for name, fnname in _chain():
        try:
            text = globals()[fnname](path)
            if text and text.strip():
                return text, name
        except Exception as e:  # noqa: BLE001 - degrade to next backend, visibly
            logger.warning("doc_extract %s failed for %s: %s: %s", name, path, type(e).__name__, e)
    logger.error("doc_extract: ALL backends failed for %s (visible gap)", path)
    return "", "none"
