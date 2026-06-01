"""Persistence: new_run / save_snapshot / load_snapshot.

Human-readable JSON snapshot at ``<base_dir>/<run_id>/state.json`` for ``cos show``
and inspection. The LangGraph SqliteSaver checkpoint (resume) is wired in graph.py;
this module is the inspectable mirror.

No wall-clock here — ``now`` is supplied by the caller (CLI/tests).
"""
from __future__ import annotations

from pathlib import Path

from .models import ResearchState


def new_run(
    question: str,
    *,
    run_id: str,
    now: str,
    mode: str = "interactive",
) -> ResearchState:
    return ResearchState(
        run_id=run_id,
        original_question=question,
        mode=mode,
        created_at=now,
        updated_at=now,
    )


def _run_dir(run_id: str, base_dir) -> Path:
    return Path(base_dir) / run_id


def save_snapshot(state: ResearchState, base_dir="runs") -> Path:
    run_dir = _run_dir(state.run_id, base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "state.json"
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_snapshot(run_id: str, base_dir="runs") -> ResearchState:
    path = _run_dir(run_id, base_dir) / "state.json"
    if not path.exists():
        raise FileNotFoundError(f"No snapshot for run_id={run_id!r} at {path}")
    return ResearchState.model_validate_json(path.read_text(encoding="utf-8"))
