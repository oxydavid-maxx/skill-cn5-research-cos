from cn5_research_cos.brains import doc_extract


def test_fallback_docling_then_pymupdf(monkeypatch, tmp_path):
    # docling opt-in: enable it so this exercises the docling->pymupdf fallback.
    monkeypatch.setenv("CN5_COS_USE_DOCLING", "1")
    p = tmp_path / "d.pdf"; p.write_bytes(b"%PDF-1.5 fake")
    calls = []
    monkeypatch.setattr(doc_extract, "_extract_docling", lambda path: (_ for _ in ()).throw(RuntimeError("OOM")))
    monkeypatch.setattr(doc_extract, "_extract_pymupdf4llm", lambda path: calls.append("pymupdf") or "MARKDOWN TEXT")
    text, backend = doc_extract.extract_doc(str(p))
    assert text == "MARKDOWN TEXT" and backend == "pymupdf4llm" and calls == ["pymupdf"]


def test_docling_opt_in_default_skips(monkeypatch, tmp_path):
    """Default (no CN5_COS_USE_DOCLING): docling is NEVER called — pymupdf4llm leads,
    so docling's uncatchable native segfault can't kill the default path."""
    monkeypatch.delenv("CN5_COS_USE_DOCLING", raising=False)
    p = tmp_path / "d.pdf"; p.write_bytes(b"%PDF")
    called = []
    monkeypatch.setattr(doc_extract, "_extract_docling", lambda path: called.append("docling") or "DOCLING")
    monkeypatch.setattr(doc_extract, "_extract_pymupdf4llm", lambda path: "PYMU TEXT")
    text, backend = doc_extract.extract_doc(str(p))
    assert text == "PYMU TEXT" and backend == "pymupdf4llm" and called == []


def test_docling_used_first_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("CN5_COS_USE_DOCLING", "1")
    p = tmp_path / "d.pdf"; p.write_bytes(b"%PDF")
    monkeypatch.setattr(doc_extract, "_extract_docling", lambda path: "DOCLING MD")
    monkeypatch.setattr(doc_extract, "_extract_pymupdf4llm", lambda path: "PYMU TEXT")
    text, backend = doc_extract.extract_doc(str(p))
    assert text == "DOCLING MD" and backend == "docling"


def test_all_fail_returns_visible_gap(monkeypatch, tmp_path):
    p = tmp_path / "d.pdf"; p.write_bytes(b"%PDF")
    for fn in ("_extract_docling", "_extract_pymupdf4llm", "_extract_pypdf"):
        monkeypatch.setattr(doc_extract, fn, lambda path: (_ for _ in ()).throw(RuntimeError("x")))
    text, backend = doc_extract.extract_doc(str(p))
    assert text == "" and backend == "none"
