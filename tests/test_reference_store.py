"""Component B — per-topic reference store (AI sources + steer notes as notes).

Today only human-dropped files land in runs/<run_id>/reference/; AI web sources
live only in transient state.evidence, and human text answers go to
steering_events. B makes the reference folder a persistent per-topic store:

  * the AI saves each collected source as a small note
    ``reference/sources/<sid>.md`` (title / url / excerpt);
  * a ``cos steer`` answer is written as a dated note
    ``reference/steer/<slug>.md``;
  * ``scan_reference_folder`` picks up BOTH (walking the subfolders) alongside the
    existing human attachments.

Small + deterministic: the note writers are pure Python (mtime ok, no
datetime.now() in core — the steer note's date is supplied by the caller's `now`).
"""
from __future__ import annotations

from pathlib import Path

from cn5_research_cos.brains import internal_doc
from cn5_research_cos.brains.reference_store import (save_source_note,
                                                     save_steer_note)
from cn5_research_cos.models import ResearchState, Source, SourceType


def _state() -> ResearchState:
    return ResearchState(run_id="topic-x", original_question="比較 A 與 B")


def test_save_source_note_writes_markdown(tmp_path):
    st = _state()
    src = Source(id="S-1", title="A datasheet", url="http://a/ds",
                 source_type=SourceType.secondary,
                 excerpt="Product A supports Qbv time-aware shaping.")
    path = save_source_note(st, src, base_dir=str(tmp_path))
    assert path.exists()
    assert path == tmp_path / "topic-x" / "reference" / "sources" / "S-1.md"
    body = path.read_text(encoding="utf-8")
    assert "A datasheet" in body
    assert "http://a/ds" in body
    assert "Qbv time-aware shaping" in body


def test_save_source_note_is_idempotent_per_source(tmp_path):
    st = _state()
    src = Source(id="S-1", title="t", url="http://a", excerpt="e")
    p1 = save_source_note(st, src, base_dir=str(tmp_path))
    p2 = save_source_note(st, src, base_dir=str(tmp_path))
    assert p1 == p2
    # only one note for the source id (no duplicates).
    assert len(list((tmp_path / "topic-x" / "reference" / "sources").glob("*.md"))) == 1


def test_save_steer_note_writes_dated_note(tmp_path):
    st = _state()
    path = save_steer_note(st, "聚焦 NXP 與 Infineon 的 TSN 對標",
                           base_dir=str(tmp_path), now="2026-06-03T10-00")
    assert path.exists()
    assert path.parent == tmp_path / "topic-x" / "reference" / "steer"
    assert "2026-06-03" in path.name
    body = path.read_text(encoding="utf-8")
    assert "NXP 與 Infineon" in body


def test_steer_note_no_wallclock_in_core(tmp_path):
    # The dated name comes from the supplied `now`, NOT datetime.now() — two calls
    # with the same `now` + text collide on the same deterministic filename.
    st = _state()
    p1 = save_steer_note(st, "same", base_dir=str(tmp_path), now="2026-06-03T10-00")
    p2 = save_steer_note(st, "same", base_dir=str(tmp_path), now="2026-06-03T10-00")
    assert p1 == p2


def test_scan_picks_up_ai_source_and_steer_notes(tmp_path):
    st = _state()
    src = Source(id="S-9", title="B datasheet", url="http://b",
                 excerpt="Product B lacks Qbu.")
    save_source_note(st, src, base_dir=str(tmp_path))
    save_steer_note(st, "比較必須包含 power 一欄", base_dir=str(tmp_path),
                    now="2026-06-03T11-00")

    bundles = internal_doc.scan_reference_folder(st, base_dir=str(tmp_path))
    # both the AI source note and the steer note were picked up as evidence.
    titles = " ".join(b.query for b in bundles)
    assert "S-9.md" in titles
    assert any("steer" in b.query or "2026-06-03" in b.query for b in bundles)
    # re-scan is a no-op (dedup by name+mtime).
    assert internal_doc.scan_reference_folder(st, base_dir=str(tmp_path)) == []


def test_apply_steer_writes_note_to_store(tmp_path):
    # Component B integration: the cos-steer caller path persists the answer note
    # (apply_steer with base_dir), and the scan then picks it up.
    from cn5_research_cos.graph import apply_steer
    st = _state()
    apply_steer(st, "把 power 一欄補齊", now="2026-06-03T12-00",
                base_dir=str(tmp_path))
    notes = list((tmp_path / "topic-x" / "reference" / "steer").glob("*.md"))
    assert len(notes) == 1
    assert "把-power" in notes[0].name or "2026-06-03" in notes[0].name
    bundles = internal_doc.scan_reference_folder(st, base_dir=str(tmp_path))
    assert any("2026-06-03" in b.query for b in bundles)


def test_scan_still_picks_up_human_attachment_at_top_level(tmp_path):
    # The existing human-attachment path (a file dropped at reference/ root) still
    # works alongside the new AI/steer subfolders.
    st = _state()
    ref = tmp_path / "topic-x" / "reference"
    ref.mkdir(parents=True)
    (ref / "human_note.md").write_text("人工補充：B 的 buffer 為 512KB。", encoding="utf-8")
    src = Source(id="S-2", title="t", url="http://a", excerpt="e")
    save_source_note(st, src, base_dir=str(tmp_path))

    bundles = internal_doc.scan_reference_folder(st, base_dir=str(tmp_path))
    queries = {b.query for b in bundles}
    assert "human_note.md" in queries
    assert "S-2.md" in queries
