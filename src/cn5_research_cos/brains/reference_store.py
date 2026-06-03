"""Component B — per-topic reference store writers.

The reference folder (``<base_dir>/<run_id>/reference/``) is the persistent
per-topic store: human attachments already land there (P5c), but AI web sources
lived only in transient ``state.evidence`` and human text answers lived only in
``steering_events``. B makes BOTH durable + auditable by writing small Markdown
notes into the store, which ``internal_doc.scan_reference_folder`` then picks up
(it walks the subfolders) exactly like a human attachment.

Two writers, both PURE Python (no LLM, no ``datetime.now()`` — the steer note's
date is supplied by the caller's ``now`` so the core is deterministic; mtime-based
dedup is the scan's job, not ours):

  * :func:`save_source_note` — one AI-collected source ->
    ``reference/sources/<sid>.md`` (title / url / excerpt). Idempotent per source
    id (overwrites the same path, never duplicates).
  * :func:`save_steer_note` — a ``cos steer`` answer ->
    ``reference/steer/<date>-<slug>.md`` (deterministic name from ``now`` + text).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..models import ResearchState, Source


def _reference_dir(state: ResearchState, base_dir: str) -> Path:
    return Path(base_dir) / state.run_id / "reference"


def _slugify(text: str, *, max_len: int = 40) -> str:
    """A filesystem-safe slug from arbitrary text (CJK-safe: keep word chars)."""
    slug = re.sub(r"\s+", "-", (text or "").strip())
    slug = re.sub(r"[^\w\-]", "", slug, flags=re.UNICODE)
    slug = slug.strip("-")
    return (slug[:max_len] or "note")


def save_source_note(state: ResearchState, source: Source, *,
                     base_dir: str = "runs") -> Path:
    """Persist ONE AI-collected source as a small note in the topic store.

    ``reference/sources/<source.id>.md`` carrying the title / url / excerpt. The
    path is keyed by the source id so re-saving the same source overwrites (the
    store ACCUMULATES distinct sources, never duplicates one). Returns the path."""
    sources_dir = _reference_dir(state, base_dir) / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / f"{source.id}.md"
    body = (
        f"# {source.title}\n\n"
        f"- id: {source.id}\n"
        f"- url: {source.url or '(no url)'}\n"
        f"- source_type: {getattr(source.source_type, 'value', source.source_type)}\n"
        f"- quality: {getattr(source.quality, 'value', source.quality)}\n\n"
        f"## Excerpt\n\n{source.excerpt or '(no excerpt captured)'}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def save_steer_note(state: ResearchState, text: str, *, base_dir: str = "runs",
                    now: str) -> Path:
    """Persist a ``cos steer`` answer as a dated note in the topic store.

    ``reference/steer/<date>-<slug>.md``. The filename is DETERMINISTIC from the
    supplied ``now`` (the caller's clock token, e.g. ``2026-06-03T10-00``) + a slug
    of the text — no ``datetime.now()`` in core, so the same (now, text) maps to
    the same path (re-writing it, not duplicating). Returns the path."""
    steer_dir = _reference_dir(state, base_dir) / "steer"
    steer_dir.mkdir(parents=True, exist_ok=True)
    date = (now or "").split("T")[0] or "undated"
    path = steer_dir / f"{date}-{_slugify(text)}.md"
    body = (
        f"# Steer note ({now})\n\n"
        f"- kind: human-steer\n"
        f"- at: {now}\n\n"
        f"## Answer / direction\n\n{text}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path
