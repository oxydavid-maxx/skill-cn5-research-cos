"""--research-source hot-swap test (P4a Task 5 DoD).

Looping the deterministic mock loop across all research_source values keeps the
loop GREEN (the graph topology + COS control are identical; only the researcher
node differs). No LLM, no network.
"""
from __future__ import annotations

import pytest

from cn5_research_cos.brains import build_brains
from cn5_research_cos.brains.research_router import RoutingResearcher
from cn5_research_cos.graph import run_loop
from cn5_research_cos.models import ResearchState


@pytest.mark.parametrize("source", ["web", "internal", "auto", "both"])
def test_loop_stays_green_across_research_sources(source, tmp_path):
    rs = ResearchState(run_id=f"r-{source}", original_question="Should we ship I3C?")
    final = run_loop(rs, base_dir=str(tmp_path), max_iterations=4, now="t",
                     llm="mock", research_source=source)
    assert isinstance(final, ResearchState)
    assert final.iteration_count >= 1
    # the bundle factory selected the right researcher shape
    brains = build_brains("mock", research_source=source)
    if source == "web":
        assert not isinstance(brains.researcher, RoutingResearcher)
    else:
        assert isinstance(brains.researcher, RoutingResearcher)


def test_unknown_research_source_rejected():
    with pytest.raises(NotImplementedError):
        build_brains("mock", research_source="bogus")
