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


def extract_doc(path: str) -> tuple[str, str]:
    """Return (text, backend_used). Tries each backend in order; ("","none") if all
    fail (visible gap). Looks the private extractors up via ``globals()`` at call
    time so tests can monkeypatch them."""
    for name, fnname in (("docling", "_extract_docling"),
                         ("pymupdf4llm", "_extract_pymupdf4llm"),
                         ("pypdf", "_extract_pypdf")):
        try:
            text = globals()[fnname](path)
            if text and text.strip():
                return text, name
        except Exception as e:  # noqa: BLE001 - degrade to next backend, visibly
            logger.warning("doc_extract %s failed for %s: %s: %s", name, path, type(e).__name__, e)
    logger.error("doc_extract: ALL backends failed for %s (visible gap)", path)
    return "", "none"
