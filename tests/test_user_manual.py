"""Phase 5c Task 5 — the in-repo USER MANUAL exists and covers the key sections.

A structural test (not a prose judge): the README must mention the cockpit's core
commands, the live debate stream, the async-supplement flow (text + document drop
with the supported formats), the §22 memo + gates, and the paperwork dependency.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _manual_text() -> str:
    readme = _REPO_ROOT / "README.md"
    assert readme.is_file(), "README.md must exist at the repo root"
    return readme.read_text(encoding="utf-8")


def test_user_manual_covers_required_sections():
    txt = _manual_text().lower()
    for anchor in [
        "cos clarify", "cos run", "cos run-auto", "cos show", "cos steer",
        "runs/", "reference/", "ppt", "word", "excel", "pdf", "html",
        "§22", "cn5_paperwork_home",
    ]:
        assert anchor.lower() in txt, f"manual missing required anchor: {anchor!r}"


def test_user_manual_explains_async_supplement_no_fabrication():
    txt = _manual_text().lower()
    # the honesty contract: unverified-critical is surfaced, never faked.
    assert "needs human supplement" in txt or "需人類補充" in _manual_text() \
        or "需要您補充" in _manual_text()
    # the live debate stream (P5b) is documented.
    assert "albert" in txt
