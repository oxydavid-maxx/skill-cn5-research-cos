"""Deterministic tests for the paperwork subprocess wrappers (P4a Task 2).

Each wrapper builds an explicit list-args subprocess command (NO shell=True),
runs it, and returns a typed result. Tests mock ``subprocess.run`` at the
boundary; ONE live test (opt-in) runs the real scripts (test_paperwork_live.py).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cn5_research_cos.brains.paperwork import scripts

HOME = Path(__file__).parent / "fixtures" / "paperwork-home"


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_outline_scan_builds_list_args_and_reads_out(monkeypatch, tmp_path):
    captured = {}
    out_file = tmp_path / "outline.md"

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        # The real script writes the outline to --out; emulate that.
        out_file.write_text("# PDF Outline Scan\nTotal pages: 42\n", encoding="utf-8")
        return _FakeCompleted(returncode=0, stderr=f"Written to {out_file}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf = tmp_path / "my doc.pdf"  # space in path on purpose
    pdf.write_bytes(b"%PDF-1.4")
    result = scripts.outline_scan(HOME, pdf, ["i3c", "daa"], out=out_file)

    cmd = captured["cmd"]
    # list args, not a shell string
    assert isinstance(cmd, list)
    assert captured["kw"].get("shell") in (None, False)
    # invokes the python interpreter on the script (NOT a bare path)
    assert cmd[0] == scripts.sys.executable
    assert cmd[1].endswith(str(Path("scripts") / "pdf_outline_scan.py"))
    assert str(pdf) in cmd
    # keywords passed through after --keywords
    assert "--keywords" in cmd and "i3c" in cmd and "daa" in cmd
    assert "--out" in cmd
    # result carries the outline text + total_pages parsed from it
    assert "Total pages: 42" in result["text"]
    assert result["total_pages"] == 42


def test_extract_pages_returns_out_path(monkeypatch, tmp_path):
    captured = {}
    out_pdf = tmp_path / "subset.pdf"

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out_pdf.write_bytes(b"%PDF-subset")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf = tmp_path / "full.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out = scripts.extract_pages(HOME, pdf, "10,20-25", out_pdf)

    assert Path(out) == out_pdf
    cmd = captured["cmd"]
    assert cmd[1].endswith(str(Path("scripts") / "extract_page_range_pdf.py"))
    assert "--pages" in cmd and "10,20-25" in cmd
    assert "--out" in cmd and str(out_pdf) in cmd


def test_pdf2md_default_backend_docling(monkeypatch, tmp_path):
    # paperwork v7.0.1+ flipped backend_policy to docling-strict: docling is the
    # ONLY valid backend for fragment-of-record output. Our default is now docling.
    captured = {}
    out_md = tmp_path / "frag.md"

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["kw"] = kw
        out_md.write_text("# fragment", encoding="utf-8")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    subset = tmp_path / "subset.pdf"
    subset.write_bytes(b"%PDF")
    out = scripts.pdf2md(HOME, subset, out_md)
    assert Path(out) == out_md
    cmd = captured["cmd"]
    assert cmd[1].endswith(str(Path("scripts") / "pdf2md.py"))
    assert "--backend" in cmd
    assert cmd[cmd.index("--backend") + 1] == "docling"
    # docling is model-based (seconds-per-page): a generous explicit timeout must
    # be passed so a slow-but-valid conversion is NOT silently killed/truncated.
    assert captured["kw"].get("timeout") is not None
    assert captured["kw"]["timeout"] >= 300


def test_pdf2md_pymupdf4llm_backend_still_constructible(monkeypatch, tmp_path):
    # The wrapper can still build a pymupdf4llm command (non-citable scratch only;
    # tier-2 never uses it), but the backend must be passed explicitly.
    captured = {}
    out_md = tmp_path / "frag.md"

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out_md.write_text("# fragment", encoding="utf-8")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    subset = tmp_path / "subset.pdf"
    subset.write_bytes(b"%PDF")
    scripts.pdf2md(HOME, subset, out_md, backend="pymupdf4llm")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--backend") + 1] == "pymupdf4llm"


def test_nonzero_exit_raises_typed_error(monkeypatch, tmp_path):
    def fake_run(cmd, **kw):
        return _FakeCompleted(returncode=2, stderr="boom: bad pdf")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(scripts.PaperworkScriptError) as ei:
        scripts.extract_pages(HOME, pdf, "1-2", tmp_path / "o.pdf")
    assert "boom: bad pdf" in str(ei.value)


def test_unknown_backend_rejected(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    with pytest.raises(ValueError):
        scripts.pdf2md(HOME, pdf, tmp_path / "o.md", backend="nope")
