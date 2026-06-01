"""SOTBrief: the Source-of-Truth research brief + its persist/version lifecycle.

The brief is the north-star everything downstream (research + audit) consumes so
it cannot drift. It is persisted per run as a human-readable
``runs/<run_id>/brief.v<N>.md`` plus a lossless JSON sidecar
``brief.v<N>.json`` for round-trip. Old versions are kept; on a new confirm the
prior versions are marked ``superseded``.

No wall-clock here — ``created_at`` / ``now`` are supplied by the caller (CLI),
keeping the core deterministic and unit-testable.
"""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class BriefStatus(str, Enum):
    draft = "draft"
    confirmed = "confirmed"
    superseded = "superseded"


class SOTBrief(BaseModel):
    """The Source-of-Truth brief produced by the clarification front-end."""

    version: int = Field(default=1, ge=1)
    objective: str  # one precise sentence = the north-star
    background: str = ""
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    forbidden_directions: list[str] = Field(default_factory=list)
    available_sources: list[str] = Field(default_factory=list)
    deliverable: str
    success_criteria: list[str] = Field(default_factory=list)
    decision_served: str | None = None
    decision_criterion: str | None = None  # None = explicitly deferred to human
    open_questions: list[str] = Field(default_factory=list)
    status: BriefStatus = BriefStatus.draft
    confirmed_by: str | None = None
    created_at: str | None = None

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def to_markdown(self) -> str:
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {x}" for x in items) if items else "_(none)_"

        return "\n".join(
            [
                f"# SOT Brief v{self.version}",
                "",
                f"- **status**: {self.status.value}",
                f"- **confirmed_by**: {self.confirmed_by or '_(unconfirmed)_'}",
                f"- **created_at**: {self.created_at or '_(unset)_'}",
                "",
                "## Objective (north-star)",
                self.objective,
                "",
                "## Background",
                self.background or "_(none)_",
                "",
                "## In scope",
                bullets(self.in_scope),
                "",
                "## Out of scope",
                bullets(self.out_of_scope),
                "",
                "## Constraints",
                bullets(self.constraints),
                "",
                "## Assumptions",
                bullets(self.assumptions),
                "",
                "## Forbidden directions",
                bullets(self.forbidden_directions),
                "",
                "## Available sources",
                bullets(self.available_sources),
                "",
                "## Deliverable",
                self.deliverable,
                "",
                "## Success criteria",
                bullets(self.success_criteria),
                "",
                "## Decision served",
                self.decision_served or "_(none / deferred)_",
                "",
                "## Decision criterion",
                self.decision_criterion or "_(deferred to human)_",
                "",
                "## Open questions",
                bullets(self.open_questions),
                "",
            ]
        )


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
_VERSION_RE = re.compile(r"^brief\.v(\d+)\.md$")


def _run_dir(run_id: str, base_dir: str) -> Path:
    return Path(base_dir) / run_id


def _md_path(run_id: str, version: int, base_dir: str) -> Path:
    return _run_dir(run_id, base_dir) / f"brief.v{version}.md"


def _json_path(run_id: str, version: int, base_dir: str) -> Path:
    return _run_dir(run_id, base_dir) / f"brief.v{version}.json"


def save(brief: SOTBrief, run_id: str, base_dir: str = "runs") -> Path:
    """Persist ``brief`` as ``brief.v<N>.md`` (human-readable) + ``.json`` sidecar.

    ``N`` is taken from ``brief.version`` (the caller owns version assignment).
    Returns the markdown path.
    """
    run_dir = _run_dir(run_id, base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    md = _md_path(run_id, brief.version, base_dir)
    md.write_text(brief.to_markdown(), encoding="utf-8")
    _json_path(run_id, brief.version, base_dir).write_text(
        brief.model_dump_json(indent=2), encoding="utf-8"
    )
    return md


def list_versions(run_id: str, base_dir: str = "runs") -> list[Path]:
    """All ``brief.v<N>.md`` paths for a run, sorted by version ascending."""
    run_dir = _run_dir(run_id, base_dir)
    if not run_dir.exists():
        return []
    found: list[tuple[int, Path]] = []
    for p in run_dir.iterdir():
        m = _VERSION_RE.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    return [p for _, p in sorted(found)]


def _versions(run_id: str, base_dir: str) -> list[int]:
    return sorted(
        int(_VERSION_RE.match(p.name).group(1)) for p in list_versions(run_id, base_dir)
    )


def load_version(run_id: str, version: int, base_dir: str = "runs") -> SOTBrief:
    """Load a specific version from its JSON sidecar (lossless)."""
    sidecar = _json_path(run_id, version, base_dir)
    if not sidecar.exists():
        raise FileNotFoundError(
            f"No SOTBrief v{version} for run_id={run_id!r} at {sidecar}"
        )
    return SOTBrief.model_validate_json(sidecar.read_text(encoding="utf-8"))


def load_latest(run_id: str, base_dir: str = "runs") -> SOTBrief:
    """Load the highest-version brief for a run."""
    versions = _versions(run_id, base_dir)
    if not versions:
        raise FileNotFoundError(f"No SOTBrief for run_id={run_id!r} under {base_dir}")
    return load_version(run_id, versions[-1], base_dir)


def latest_version_number(run_id: str, base_dir: str = "runs") -> int:
    """Highest version on disk, or 0 if none yet."""
    versions = _versions(run_id, base_dir)
    return versions[-1] if versions else 0


def supersede(
    run_id: str,
    up_to_version: int,
    base_dir: str = "runs",
    now: str | None = None,
) -> list[int]:
    """Mark every persisted version <= ``up_to_version`` as ``superseded``.

    Rewrites those briefs in place (status -> superseded; created_at preserved
    unless ``now`` supplied as an audit marker is desired — we leave created_at
    untouched to keep provenance). Returns the list of versions touched.
    """
    touched: list[int] = []
    for v in _versions(run_id, base_dir):
        if v > up_to_version:
            continue
        b = load_version(run_id, v, base_dir)
        if b.status == BriefStatus.superseded:
            continue
        b.status = BriefStatus.superseded
        save(b, run_id, base_dir)
        touched.append(v)
    return touched
