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
