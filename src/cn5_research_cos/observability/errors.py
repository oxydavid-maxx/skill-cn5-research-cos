"""Typed observability exceptions for the cockpit (P5d honest visibility).

Mirrors ``skill-cn5-i-am-albert/albert/errors.py``: the cockpit treats the durable
per-stage debate record as a deterministic runtime guarantee, not optional logging.
A failure to persist the auditable debate block is FAIL-CLOSED — it raises rather
than silently dropping the record — because for an audit-driven cockpit, "no
auditable record" must stop the run, not produce a degraded-success.
"""
from __future__ import annotations


class VisibilityContractError(Exception):
    """A required debate-visibility sink could not be written.

    Raised when the durable ``runs/<run_id>/debate.md`` sink cannot be created or
    appended to. The live stderr/tty sinks are best-effort and do NOT raise this;
    only the durable file (the one real 100%) is fail-closed.
    """

    def __init__(self, message: str, *, phase: str = "", sink: str = "") -> None:
        super().__init__(message)
        self.phase = phase
        self.sink = sink
