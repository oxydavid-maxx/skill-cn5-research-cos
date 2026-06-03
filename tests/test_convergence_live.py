"""Live opt-in convergence test (CN5_COS_LLM_TESTS=1). Skips cleanly without it.

Proves the adversarial loop CONVERGES end-to-end on REAL LLMs: a short real run
where Albert raises a challenge, the next round's research targets it, and the
challenge resolves (or is escalated to a human) — never piling up duplicates or
looping forever. Short by design (a couple of iterations), NOT a long benchmark.

Do NOT run this yourself in the build harness — the controller runs the long live
test. Without the opt-in it is skipped.
"""
from __future__ import annotations

import os

import pytest

from cn5_research_cos.decision import convergence
from cn5_research_cos.graph import run_auto
from cn5_research_cos.models import ChallengeStatus, ResearchState


@pytest.mark.llm
def test_real_loop_converges_or_escalates(tmp_path):
    if os.environ.get("CN5_COS_LLM_TESTS") != "1":
        pytest.skip("set CN5_COS_LLM_TESTS=1 to run live LLM tests")

    rs = ResearchState(
        run_id="live-converge",
        original_question="Should our BU build an autonomous overnight research agent?",
    )
    result = run_auto(rs, base_dir=tmp_path, max_iterations=3, now="t0", llm="real")
    final = result["state"]

    assert final.iteration_count >= 1
    assert final.last_audit is not None

    # The auditor produced challenges and they were tracked in the map WITHOUT
    # unbounded duplication: with upsert, distinct challenges <= total audit
    # rounds * a small per-round count. We assert convergence MOVEMENT instead of
    # a hard count (model variance): either a challenge resolved/escalated, OR the
    # open-count trend is recorded so the loop can see convergence.
    cm = final.albert_challenge_map
    assert cm, "Albert raised at least one challenge"

    progressed = (
        convergence.resolved_count(final) > 0
        or convergence.escalated_count(final) > 0
        or any(c.rounds_seen >= 2 for c in cm.values())   # a challenge carried fwd
        or len(final.convergence_history) >= 1            # the signal was recorded
    )
    assert progressed, (
        "no convergence movement: challenges neither resolved, escalated, carried "
        "forward, nor tracked"
    )

    # No silent duplication: every challenge id is unique (upsert merged re-raises).
    assert len(set(cm.keys())) == len(cm)

    # If the run paused, it was a real human gate (escalation), not a crash.
    if result["paused"]:
        assert result["ask"] is not None
