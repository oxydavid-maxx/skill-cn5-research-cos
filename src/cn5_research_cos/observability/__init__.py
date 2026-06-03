"""P5b live-debate observability: a deterministic StageReporter that streams a
per-stage, human-readable summary of the adversarial loop to the operator's
terminal AS THE LOOP RUNS — guaranteed visible (flushed) even in a non-tty."""
from .reporter import (
    StageReporter, render_albert, render_convergence, render_critique,
    render_decision, render_expand, render_readiness, render_research,
    render_scope,
)

__all__ = [
    "StageReporter",
    "render_scope", "render_expand", "render_research", "render_critique",
    "render_albert", "render_convergence", "render_readiness", "render_decision",
]
