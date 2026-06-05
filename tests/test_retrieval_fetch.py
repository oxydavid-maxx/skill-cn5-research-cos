from cn5_research_cos.brains import retrieval


def test_is_pdf_url():
    assert retrieval.is_doc_url("https://x.com/a.pdf")
    assert retrieval.is_doc_url("https://x.com/a.PDF?x=1")
    assert not retrieval.is_doc_url("https://x.com/page.html")


def test_fetch_and_extract(monkeypatch, tmp_path):
    monkeypatch.setattr(retrieval, "_download", lambda url, dest: dest.write_bytes(b"%PDF") or dest)
    monkeypatch.setattr(retrieval, "extract_doc", lambda p: ("EXTRACTED SPECS", "pymupdf4llm"))
    text, backend = retrieval.fetch_and_extract("https://x.com/sja.pdf", base_dir=str(tmp_path))
    assert text == "EXTRACTED SPECS" and backend == "pymupdf4llm"
