"""Phase 5c Task 6 — live opt-in: honest no-fabrication + continue + notify.

A REAL run (CN5_COS_LLM_TESTS=1) that asserts the P5c honesty contract end-to-end:

  * NO fabrication — every claim surfaced AS fact in the emitted memo is verified;
    any unverified-critical item appears ONLY in "What We Cannot Say" / "Required
    Human Decisions", flagged "needs human supplement", NEVER as fact;
  * the loop did NOT pause/block on the unverified-critical item (it continued to a
    terminal/synthesize/ceiling stop, not a high-risk hard-stop on this);
  * a notification was ATTEMPTED for any needs-supplement item (the email sender is
    mocked to record, so no Outlook is required), and the live debate stream shows
    the Albert audit.

Do NOT run this in the build harness — the controller runs the long live test after
implementation returns. Without the opt-in it skips cleanly.
"""
from __future__ import annotations

import io
import os

import pytest

import cn5_research_cos.graph as graph
from cn5_research_cos.brains import build_brains
from cn5_research_cos.graph import run_auto
from cn5_research_cos.observability.reporter import StageReporter
from cn5_research_cos.synthesis.gates import check_emission
from cn5_research_cos.synthesis.memo import assemble_memo, route_citations
from cn5_research_cos.models import ResearchState


@pytest.mark.llm
def test_live_no_fabrication_continue_and_notify(tmp_path, monkeypatch):
    if os.environ.get("CN5_COS_LLM_TESTS") != "1":
        pytest.skip("set CN5_COS_LLM_TESTS=1 to run live LLM tests")

    # Record every notify attempt instead of sending a real email (no Outlook).
    notified: list[tuple[str, list]] = []
    monkeypatch.setattr(
        graph, "notify_supplement_needed",
        lambda run_id, items, **kw: notified.append((run_id, list(items))) or True,
    )

    rs = ResearchState(
        run_id="live-supplement",
        original_question="Should our BU build an autonomous overnight research agent?",
    )
    debate_buf = io.StringIO()
    reporter = StageReporter(stream=debate_buf)
    result = run_auto(rs, base_dir=tmp_path, max_iterations=3, now="t0",
                      llm="real", reporter=reporter)
    final = result["state"]

    # The loop did NOT hard-stop on an unverified-critical item — it reached a
    # normal stop (continue-and-notify, never block).
    assert result["paused"] is False, f"unexpected pause: {result['stop_reason']}"
    assert final.iteration_count >= 1
    assert "[albert_audit]" in debate_buf.getvalue()

    # Route the citations on the final state: any unverified-critical item is a
    # HumanTask in needs_supplement (surfaced, not faked); verified are cited.
    route = route_citations(final)
    synth = build_brains(llm="real").synthesizer
    memo = assemble_memo(final, synth)
    check_emission(final, memo, explicit=True)

    # NO fabrication: the memo never emits an unverified KEY claim AS fact.
    if memo.emitted:
        assert not memo.unverified_key_claims, memo.unverified_key_claims

    # Every needs-supplement item is surfaced (flagged) in the rendered memo and is
    # NEVER in the cited set; a HumanTask exists for it.
    for item in memo.needs_supplement:
        assert item in (final.final_memo or ""), f"needs-supplement item not surfaced: {item!r}"
        assert item not in [c.claim for c in route.cited]
        assert any(item == t.requested_input for t in final.human_tasks.values())

    # If anything needed supplement, a notification was attempted with the run_id.
    if memo.needs_supplement:
        assert notified, "needs_supplement present but no notification was attempted"
        assert notified[0][0] == "live-supplement"
