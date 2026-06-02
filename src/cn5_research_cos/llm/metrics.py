"""Per-run cost + latency accumulation for the cockpit loop (P2 acceleration).

A tiny, dependency-free accumulator the LLM transport feeds (`record(...)` per
call) and that `cos run` prints as a one-line summary at the end. Deterministic:
the caller supplies wall-clock deltas and cost, so unit tests never touch a clock.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunMetrics:
    """Accumulates cost ($), wall-clock latency, call counts, and token usage.

    Fed by the SDK transport (`ClaudeSession.ask` / `call_structured`) when a
    metrics object is threaded through. `total_cost_usd` is read from each
    `ResultMessage`; `wall_s` is the per-call wall-clock measured by the transport.
    """

    calls: int = 0
    total_usd: float = 0.0
    wall_clock_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    per_brain: dict[str, int] = field(default_factory=dict)

    def record(self, *, cost_usd: float | None, wall_s: float,
               brain: str = "unknown", usage: dict | None = None) -> None:
        """Record one LLM call. A None cost (no ResultMessage.total_cost_usd)
        counts the call but adds nothing to the dollar total."""
        self.calls += 1
        if cost_usd is not None:
            self.total_usd += float(cost_usd)
        self.wall_clock_s += float(wall_s)
        self.per_brain[brain] = self.per_brain.get(brain, 0) + 1
        if usage:
            self.input_tokens += int(usage.get("input_tokens", 0) or 0)
            self.output_tokens += int(usage.get("output_tokens", 0) or 0)

    def summary_line(self) -> str:
        """One-line cost/latency/calls summary for `cos run`."""
        return (
            f"cost=${self.total_usd:.2f} "
            f"latency={self.wall_clock_s:.1f}s "
            f"calls={self.calls}"
        )
