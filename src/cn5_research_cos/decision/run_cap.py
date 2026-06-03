"""Component C — hard run cap (cost + wall).

With the real Albert auditor (5–20 min/audit) a runaway loop can blow up cost and
time. The cockpit already has ``max_iterations`` + branch-budget decay + a SOFT
budget warning, but no HARD cost/time cap. This module adds one.

Two pure pieces + one contextvar seam:

  * :func:`cap_exceeded` — the pure predicate: given the run ``metrics`` + caps +
    elapsed wall, returns ``(hit, reason)``. No clock, no I/O — fully testable.
  * :func:`caps_from_args` — resolve the effective caps from explicit args, else
    the ``CN5_COS_MAX_COST_USD`` / ``CN5_COS_MAX_WALL_S`` env vars (explicit wins).
  * a contextvar (``_CAP_CV``) the run_loop / run_auto entrypoints publish (the
    checkpointed graph cannot carry the non-serializable ``RunMetrics`` in
    GraphState, exactly like the StageReporter) and the graph router consults via
    :func:`cap_hit_now`. When the cap is hit the router wraps the run up (deep
    audit -> review -> emit current findings) instead of starting another
    iteration — a hard-stop AFTER the current node, deterministic and honest.
"""
from __future__ import annotations

import contextvars
import os
import time
from dataclasses import dataclass
from typing import Callable


def cap_exceeded(metrics, *, max_cost_usd: float | None,
                 max_wall_s: float | None, elapsed_s: float) -> tuple[bool, str]:
    """Pure cap predicate: True (+ a reason) iff a cap is set AND met/exceeded.

    Cost: ``metrics.total_usd >= max_cost_usd``. Wall: ``elapsed_s >= max_wall_s``.
    An unset (None) cap never triggers. Cost is checked before wall."""
    if max_cost_usd is not None and getattr(metrics, "total_usd", 0.0) >= max_cost_usd:
        return True, (f"hard cost cap hit: ${getattr(metrics, 'total_usd', 0.0):.2f} "
                      f">= ${max_cost_usd:.2f}")
    if max_wall_s is not None and elapsed_s >= max_wall_s:
        return True, (f"hard wall cap hit: {elapsed_s:.0f}s >= {max_wall_s:.0f}s")
    return False, ""


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def caps_from_args(max_cost_usd: float | None,
                   max_wall_s: float | None) -> tuple[float | None, float | None]:
    """Resolve the effective (cost, wall) caps: explicit arg wins over the env var
    (``CN5_COS_MAX_COST_USD`` / ``CN5_COS_MAX_WALL_S``); None when neither is set."""
    cost = max_cost_usd if max_cost_usd is not None else _env_float("CN5_COS_MAX_COST_USD")
    wall = max_wall_s if max_wall_s is not None else _env_float("CN5_COS_MAX_WALL_S")
    return cost, wall


@dataclass
class _ActiveCap:
    metrics: object
    max_cost_usd: float | None
    max_wall_s: float | None
    started: float
    clock: Callable[[], float]

    def hit(self) -> tuple[bool, str]:
        elapsed = self.clock() - self.started
        return cap_exceeded(self.metrics, max_cost_usd=self.max_cost_usd,
                            max_wall_s=self.max_wall_s, elapsed_s=elapsed)


# The active cap for the current run (None = no cap). The checkpointed graph cannot
# carry RunMetrics in GraphState, so the entrypoint publishes the cap here for the
# duration of the invoke and the router reads it (mirrors graph._REPORTER_CV).
_CAP_CV: "contextvars.ContextVar[_ActiveCap | None]" = contextvars.ContextVar(
    "cn5_cos_run_cap", default=None,
)


def publish_cap(metrics, *, max_cost_usd: float | None, max_wall_s: float | None,
                clock: Callable[[], float] = time.monotonic):
    """Publish the active cap on the contextvar for the duration of a run; returns
    the reset token. ``clock`` is injectable so tests are deterministic. When BOTH
    caps are None this still publishes (a no-op cap that never hits) so callers can
    reset uniformly."""
    cap = _ActiveCap(metrics=metrics, max_cost_usd=max_cost_usd,
                     max_wall_s=max_wall_s, started=clock(), clock=clock)
    return _CAP_CV.set(cap)


def reset_cap(token) -> None:
    """Reset the cap contextvar (call in a finally so a cap never leaks across runs)."""
    try:
        _CAP_CV.reset(token)
    except (LookupError, ValueError):
        _CAP_CV.set(None)


def cap_hit_now() -> bool:
    """True iff a cap is published AND currently hit. Router consults this."""
    cap = _CAP_CV.get()
    if cap is None:
        return False
    hit, _ = cap.hit()
    return hit


def cap_reason_now() -> str:
    """The human-readable reason the cap is hit ("" when not hit / no cap)."""
    cap = _CAP_CV.get()
    if cap is None:
        return ""
    _, reason = cap.hit()
    return reason
