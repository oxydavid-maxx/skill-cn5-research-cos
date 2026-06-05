from cn5_research_cos.brains import doc_extract


def test_fallback_docling_then_pymupdf(monkeypatch, tmp_path):
    p = tmp_path / "d.pdf"; p.write_bytes(b"%PDF-1.5 fake")
    calls = []
    monkeypatch.setattr(doc_extract, "_extract_docling", lambda path: (_ for _ in ()).throw(RuntimeError("OOM")))
    monkeypatch.setattr(doc_extract, "_extract_pymupdf4llm", lambda path: calls.append("pymupdf") or "MARKDOWN TEXT")
    text, backend = doc_extract.extract_doc(str(p))
    assert text == "MARKDOWN TEXT" and backend == "pymupdf4llm" and calls == ["pymupdf"]


def test_all_fail_returns_visible_gap(monkeypatch, tmp_path):
    p = tmp_path / "d.pdf"; p.write_bytes(b"%PDF")
    for fn in ("_extract_docling", "_extract_pymupdf4llm", "_extract_pypdf"):
        monkeypatch.setattr(doc_extract, fn, lambda path: (_ for _ in ()).throw(RuntimeError("x")))
    text, backend = doc_extract.extract_doc(str(p))
    assert text == "" and backend == "none"
