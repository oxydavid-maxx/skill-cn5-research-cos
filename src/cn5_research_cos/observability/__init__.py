"""P5b live-debate observability: a deterministic StageReporter that streams a
per-stage, human-readable summary of the adversarial loop to the operator's
terminal AS THE LOOP RUNS — guaranteed visible (flushed) even in a non-tty."""
from .reporter import StageReporter

__all__ = ["StageReporter"]
