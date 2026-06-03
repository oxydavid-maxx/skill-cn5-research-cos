"""Phase 5c Task 2 — Outlook-COM supplement-needed email notifier (fail-soft).

Mirrors (does NOT import) daily_brief's win32com Outlook send. The body carries the
run_id, each unverified-critical item's "what's needed", and COPY-PASTE-READY
commands: a text supplement (``cos steer <run_id> "..."``) and the document
drop-folder instruction (``runs/<run_id>/reference/``). A send exception is caught,
logged with a VISIBLE warning, and returns False — never raises (the HumanTask is
still recorded elsewhere, so the need is never silently lost).

Tests pass a FAKE ``send`` callable so no Outlook is required.
"""
from __future__ import annotations

from cn5_research_cos.models import HumanTask
from cn5_research_cos.notify.email import (build_supplement_email,
                                           notify_supplement_needed)


def _items() -> list[HumanTask]:
    return [
        HumanTask(id="HT-001", task_title="補充驗證：claim A",
                  requested_input="claim A needs a primary source",
                  why_needed="決策關鍵但無法驗證"),
        HumanTask(id="HT-002", task_title="補充驗證：claim B",
                  requested_input="claim B needs internal data",
                  why_needed="決策關鍵但無法驗證"),
    ]


def test_email_body_has_runid_and_pasteable_commands():
    body = build_supplement_email("abc123", _items())
    assert "abc123" in body
    assert 'cos steer abc123' in body
    assert "runs/abc123/reference/" in body
    # each item's "what is needed" appears
    assert "claim A needs a primary source" in body
    assert "claim B needs internal data" in body


def test_email_body_lists_supported_document_formats():
    body = build_supplement_email("abc123", _items())
    # the document-drop instruction names the supported formats
    for fmt in ("PDF", "Word", "Excel"):
        assert fmt in body or fmt.lower() in body.lower()


def test_notify_calls_send_with_composed_body():
    sent = {}

    def fake_send(*, to, subject, body):
        sent["to"] = to
        sent["subject"] = subject
        sent["body"] = body

    ok = notify_supplement_needed("abc123", _items(), base_dir="runs",
                                  send=fake_send)
    assert ok is True
    assert "abc123" in sent["body"]
    assert "cos steer abc123" in sent["body"]
    assert "abc123" in sent["subject"]


def test_send_failure_is_fail_soft():
    def boom(*, to, subject, body):
        raise RuntimeError("Outlook not running")

    # a send exception is caught -> returns False, never raises.
    assert notify_supplement_needed("abc123", _items(), base_dir="runs",
                                    send=boom) is False


def test_no_items_does_not_send():
    calls = []

    def rec(**kw):
        calls.append(kw)

    # nothing to supplement -> no email attempted, returns False.
    assert notify_supplement_needed("abc123", [], base_dir="runs", send=rec) is False
    assert calls == []
