"""Thin, deterministic subprocess wrappers around paperwork's ``scripts/`` CLIs.

Each wrapper builds an EXPLICIT list-args command (never ``shell=True``), runs
it via the current Python interpreter (``[sys.executable, <script>, ...]`` so it
works regardless of the script's exec bit / shebang and handles spaces in
paths), decodes stdout/stderr as UTF-8, and raises ``PaperworkScriptError`` on a
non-zero exit. NO LLM here — these are pure I/O shims.

Verified script signatures (paperwork v7.14.2):
  scripts/pdf_outline_scan.py    <PDF> [--keywords KW...] [--out OUT]
  scripts/extract_page_range_pdf.py <PDF> --pages SPEC --out FILE
  scripts/pdf2md.py              <PDF> [-o OUT] [--backend pymupdf4llm|docling]
                                 [--timeout SEC] [--seconds-per-page SEC]

Backend contract (paperwork v7.0.1+): ``backend_policy`` defaults to
``docling-strict`` — ``pdf2md.py --backend pymupdf4llm`` EXITS 2 for
fragment-of-record output. ``docling`` is therefore the ONLY valid backend for
citable fragments and is our default. docling is model-based (seconds-per-page),
so its subprocess is given a generous explicit timeout (not the fast-script
default) to avoid silently killing a slow-but-valid conversion.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_VALID_BACKENDS = ("pymupdf4llm", "docling")

# docling is model-based (default ~3 s/page + model load): a small bounded subset
# can still take minutes. A generous explicit timeout avoids silently killing a
# slow-but-valid conversion (we never truncate). Fast scripts (outline/extract)
# use the shorter default.
_FAST_TIMEOUT = 120
_DOCLING_TIMEOUT = 900

_TOTAL_PAGES_RE = re.compile(r"Total pages:\s*(\d+)")


class PaperworkScriptError(RuntimeError):
    """A paperwork script exited non-zero (or could not be launched)."""


def _script_path(home: Path | str, name: str) -> str:
    return str(Path(home) / "scripts" / name)


def _run(cmd: list[str], *, timeout: int = _FAST_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a list-args command, UTF-8 decoded, raising on non-zero exit.

    NO ``shell=True`` (so spaces in paths are safe and there is no shell
    injection surface). ``text=True`` + ``encoding="utf-8"`` normalizes CRLF and
    decodes deterministically across platforms. ``timeout`` is explicit so the
    model-based docling backend gets a generous window (see ``_DOCLING_TIMEOUT``)
    while fast scripts stay snappy; a timeout surfaces as ``PaperworkScriptError``
    (a loud tool failure), never a silent truncation.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise PaperworkScriptError(
            f"{cmd[1] if len(cmd) > 1 else cmd!r} timed out after {timeout}s "
            f"(no partial/truncated output committed)"
        ) from e
    except OSError as e:  # interpreter/script missing, permissions, etc.
        raise PaperworkScriptError(f"failed to launch {cmd!r}: {e}") from e
    if proc.returncode != 0:
        raise PaperworkScriptError(
            f"{cmd[1] if len(cmd) > 1 else cmd!r} exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()}"
        )
    return proc


def outline_scan(home: Path | str, pdf: Path | str, keywords: list[str],
                 *, out: Path | str) -> dict:
    """Scan a PDF's outline/TOC + keyword hits, writing markdown to ``out``.

    Returns ``{"text": <outline markdown>, "total_pages": int|None, "out": Path}``.
    The text is what the tier-2 page-range brain consumes to pick page ranges.
    """
    out_path = Path(out)
    cmd = [sys.executable, _script_path(home, "pdf_outline_scan.py"), str(pdf)]
    if keywords:
        cmd.append("--keywords")
        cmd.extend(str(k) for k in keywords)
    cmd.extend(["--out", str(out_path)])
    _run(cmd)
    text = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
    m = _TOTAL_PAGES_RE.search(text)
    total_pages = int(m.group(1)) if m else None
    return {"text": text, "total_pages": total_pages, "out": out_path}


def extract_pages(home: Path | str, pdf: Path | str, pages: str,
                  out: Path | str) -> Path:
    """Extract ``pages`` (e.g. ``"10,20-25"``) from ``pdf`` into subset ``out``.

    Returns the output PDF path. ``pages`` is ALWAYS a bounded subset spec — the
    caller (tier-2) never passes the whole-file range.
    """
    out_path = Path(out)
    cmd = [
        sys.executable, _script_path(home, "extract_page_range_pdf.py"),
        str(pdf), "--pages", str(pages), "--out", str(out_path),
    ]
    _run(cmd)
    return out_path


def html2md(home: Path | str, html: Path | str,
            out: Path | str | None = None) -> str:
    """Convert an HTML file to markdown via paperwork's ``html2md.py``.

    Writes to ``out`` (a temp file if not given) and returns the markdown text.
    Raises ``PaperworkScriptError`` on a non-zero exit (a loud tool failure).
    """
    import tempfile
    html_path = Path(html)
    if out is None:
        out_path = Path(tempfile.gettempdir()) / f"{html_path.stem}.cn5html.md"
    else:
        out_path = Path(out)
    cmd = [
        sys.executable, _script_path(home, "html2md.py"), str(html_path),
        "-o", str(out_path),
    ]
    _run(cmd)
    return out_path.read_text(encoding="utf-8") if out_path.is_file() else ""


def pdf2md(home: Path | str, subset_pdf: Path | str, out: Path | str,
           *, backend: str = "docling", seconds_per_page: float | None = None) -> Path:
    """Convert a (subset) PDF to markdown via ``backend`` into ``out``.

    ``docling`` is the default and the ONLY valid backend for fragment-of-record
    output (paperwork v7.0.1+ ``backend_policy=docling-strict`` forbids
    ``pymupdf4llm`` for citable fragments — it exits 2). ``pymupdf4llm`` is only
    for non-citable scratch and is never used by tier-2. docling is model-based
    and slower (seconds-per-page); we give it a generous explicit timeout so a
    slow-but-valid conversion is not silently killed/truncated. Returns the
    output markdown path.
    """
    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"unknown backend {backend!r}; expected one of {_VALID_BACKENDS}"
        )
    out_path = Path(out)
    cmd = [
        sys.executable, _script_path(home, "pdf2md.py"), str(subset_pdf),
        "-o", str(out_path), "--backend", backend,
    ]
    if backend == "docling":
        # Forward seconds-per-page so the script's auto-timeout scales with the
        # subset size; our subprocess timeout is the generous outer bound.
        if seconds_per_page is not None:
            cmd.extend(["--seconds-per-page", str(seconds_per_page)])
        _run(cmd, timeout=_DOCLING_TIMEOUT)
    else:
        _run(cmd, timeout=_FAST_TIMEOUT)
    return out_path
