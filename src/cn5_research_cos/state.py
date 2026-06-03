"""GraphState TypedDict + reducers for the LangGraph loop.

worker_results uses an ``operator.add`` reducer so parallel Send-fan-out workers
merge instead of clobbering. The big ResearchState is written by a single linear
writer per super-step (only collect/main nodes touch it; workers write only
worker_results), so it needs no reducer.
"""
from __future__ import annotations

import operator
from typing import Annotated

from typing_extensions import TypedDict

from .models import Decision, ResearchState


class GraphState(TypedDict, total=False):
    research_state: ResearchState
    last_decision: Decision
    branch_budget: dict
    prereqs: dict
    worker_results: Annotated[list, operator.add]
    base_dir: str
    now: str
    max_iterations: int
    llm: str
    # P6 / Component D: the Albert auditor selector — "sim" (default, the
    # RealAlbertSimulator) | "real" (the external skill-cn5-i-am-albert via
    # subprocess). MUST be declared here or LangGraph drops the init value after
    # the first super-step, silently downgrading --albert real to the simulator
    # (the original 'str' object has no attribute 'get' crash had this as its
    # first half: _brains defaulted to "sim"). Threaded into build_brains.
    albert: str
    # P4a: evidence source selector — "web" (default, unchanged) | "internal" |
    # "auto" | "both". Threaded into build_brains exactly like ``llm``.
    research_source: str
    # P3 HITL: "interactive" (pause+exit on every pull gate) | "auto" (apply
    # default on low-risk pulls, hard-stop/interrupt only on high-risk).
    mode: str
    # H6 final-review interrupt is opt-in (CLI cos run sets it); the P1 run_loop
    # (no checkpointer) leaves it False so terminal stops don't pause.
    enable_h6: bool
    # P5: an explicit user command to emit the §22 memo even if the readiness
    # target is not met (the readiness emission gate honors it). Default False —
    # the normal path emits only when readiness targets are met.
    explicit_emit: bool
    # Test-only: inject a ready-made Brains bundle (non-checkpointed path only,
    # since a Brains dataclass is not JSON-serializable). Production never sets it.
    brains: object
    # P5b live-debate observability: an optional StageReporter the loop nodes call
    # to stream a per-stage human-readable summary to stdout (flushed, non-tty
    # safe). DEFAULT None/off so the existing loop tests (which never thread one)
    # emit nothing and stay green; the CLI `cos run`/`run-auto` threads a real
    # StageReporter(sys.stdout) when --stream (default ON). Not JSON-serializable,
    # so it rides the non-checkpointed compile_graph() path exactly like `brains`.
    reporter: object
