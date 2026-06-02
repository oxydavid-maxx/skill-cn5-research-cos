"""Thin, deterministic subprocess wrappers around paperwork's ``scripts/`` CLIs.

Each wrapper builds an EXPLICIT list-args command (never ``shell=True``), runs
it via the current Python interpreter (``[sys.executable, <script>, ...]`` so it
works regardless of the script's exec bit / shebang and handles spaces in
paths), decodes stdout/stderr as UTF-8, and raises ``PaperworkScriptError`` on a
non-zero exit. NO LLM here — these are pure I/O shims.

Verified script signatures (paperwork v2.19.x):
  scripts/pdf_outline_scan.py    <PDF> [--keywords KW...] [--out OUT]
  scripts/extract_page_range_pdf.py <PDF> --pages SPEC --out FILE
  scripts/pdf2md.py              <PDF> [-o OUT] [--backend pymupdf4llm|docling]
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_VALID_BACKENDS = ("pymupdf4llm", "docling")

_TOTAL_PAGES_RE = re.compile(r"Total pages:\s*(\d+)")


class PaperworkScriptError(RuntimeError):
    """A paperwork script exited non-zero (or could not be launched)."""


def _script_path(home: Path | str, name: str) -> str:
    return str(Path(home) / "scripts" / name)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a list-args command, UTF-8 decoded, raising on non-zero exit.

    NO ``shell=True`` (so spaces in paths are safe and there is no shell
    injection surface). ``text=True`` + ``encoding="utf-8"`` normalizes CRLF and
    decodes deterministically across platforms.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
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


def pdf2md(home: Path | str, subset_pdf: Path | str, out: Path | str,
           *, backend: str = "pymupdf4llm") -> Path:
    """Convert a (subset) PDF to markdown via ``backend`` into ``out``.

    ``pymupdf4llm`` is the default (fast); ``docling`` only when the caller flags
    a table-heavy range. Returns the output markdown path.
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
    _run(cmd)
    return out_path
