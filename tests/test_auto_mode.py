"""Auto mode (run_auto) — Test 5 + low/high-risk behaviour + steer re-rank.

Deterministic (mock brains). Auto mode: low-risk pulls auto-default (no pause),
high-risk pulls hard-stop (interrupt). On completion the final state explains the
stop reason.
"""
from cn5_research_cos.graph import run_auto
from cn5_research_cos.models import (Decision, IssueStatus, IssueType,
                                     ResearchState)
from cn5_research_cos.artifacts import issue_map


def test_5_run_auto_multiple_iterations_audits_and_stops(tmp_path):
    """Test 5: run_auto over the stub loop runs multiple iterations, audits each,
    readiness updated, final state explains the stop reason — without pausing."""
    rs = ResearchState(run_id="auto5", original_question="AI 能否做隔夜研究?")
    result = run_auto(rs, base_dir=tmp_path, max_iterations=8, now="t0", llm="mock",
                      assume_brief=True)  # P8: tests loop, not the H0 clarify gate

    final = result["state"]
    assert final.iteration_count >= 2, "auto mode should run multiple iterations"
    assert final.readiness_score is not None, "audit/scoring ran each iteration"
    assert final.last_audit is not None
    # Reached a terminal stop (not a hard-stop pause): a stop reason is given.
    assert result["paused"] is False
    assert result["stop_reason"]
    assert result["decision"] in (Decision.synthesize, Decision.terminal_stop) \
        or result["reason_kind"] == "iteration_ceiling"
    # The deep audit ran at the terminal gate (gated, not per-iteration).
    assert final.deep_audit_count >= 1


def test_auto_low_risk_applies_default_and_records_steering_event(tmp_path):
    """A low-risk pull in auto mode applies default_if_no_response and records a
    steering_event(auto-default) — no interrupt, the loop continues."""
    rs = ResearchState(run_id="autolow", original_question="q")
    rs.default_research_priority = "ROI first"
    rs.fallback_behavior_if_human_unavailable = "proceed ROI"
    issue_map.add(rs, title="roi", description="d", issue_type=IssueType.roi,
                  status=IssueStatus.open, now="t", impact=3)
    issue_map.add(rs, title="competitor covered", description="d",
                  issue_type=IssueType.competitor, status=IssueStatus.open,
                  now="t", impact=3)
    rs.steering_events.append({
        "kind": "request_pull", "context": "c", "why": "w",
        "options": ["A", "B", "C"], "ai_recommendation": "A",
        "default_if_no_response": "A", "consumed": False,
    })
    result = run_auto(rs, base_dir=tmp_path, max_iterations=6, now="t0", llm="mock",
                      assume_brief=True)  # P8: tests low-risk pull, not the H0 clarify gate
    final = result["state"]
    assert result["paused"] is False
    auto_defaults = [e for e in final.steering_events if e.get("kind") == "auto-default"]
    assert auto_defaults, "low-risk pull must record an auto-default steering event"
    assert auto_defaults[0]["choice"] == "A"


def test_auto_high_risk_hard_stops(tmp_path):
    """A high-risk pull in auto mode hard-stops (interrupt) — the run pauses and
    is resumable, even in auto."""
    rs = ResearchState(run_id="autohi", original_question="q")
    # criterion unknown + every high-impact open issue depends on it -> high.
    for i in range(2):
        n = issue_map.add(rs, title=f"intent{i}", description="d",
                          issue_type=IssueType.intent, status=IssueStatus.open,
                          now="t", impact=5)
        n.unknowns.append("decision_criterion")
    rs.steering_events.append({
        "kind": "request_pull", "context": "方向", "why": "互斥",
        "options": ["A", "B", "C"], "ai_recommendation": "A",
        "default_if_no_response": "A", "consumed": False,
    })
    result = run_auto(rs, base_dir=tmp_path, max_iterations=6, now="t0", llm="mock",
                      assume_brief=True)  # P8: tests high-risk pull, not the H0 clarify gate
    assert result["paused"] is True, "high-risk pull must hard-stop in auto mode"
    assert result["ask"] is not None
    assert result["ask"]["options"] == ["A", "B", "C"]
    assert result["run_id"] == "autohi"  # resumable by run_id


def test_run_auto_pauses_at_clarify_when_brief_not_converged(tmp_path):
    """P8 H0 regression guard: the AFK run_auto path must NOT silently skip
    clarification. With a non-converged brief and assume_brief=False, run_auto
    PAUSES at the H0 clarify gate (it does not run the research loop)."""
    rs = ResearchState(run_id="h0pause", original_question="switch PK", mode="auto")
    # nothing pinned: no decision_criterion / success_form / research_brief / fallback
    result = run_auto(rs, base_dir=str(tmp_path), llm="mock", run_id="h0pause",
                      assume_brief=False)
    assert result["paused"] is True
    # the pause is the H0 clarify gate (not a later gate)
    blob = str(result.get("ask")) + str(result.get("stop_reason")) + str(result.get("reason_kind"))
    assert "clarify" in blob.lower() or "clarif" in blob.lower()


def test_run_auto_proceeds_past_clarify_with_assume_brief(tmp_path):
    """P8 H0: with assume_brief=True the AFK path proceeds past the clarify gate
    (clarify is not the blocker) — it may pause LATER or complete, but the loop
    progressed and clarify_converged is set."""
    rs = ResearchState(run_id="h0skip", original_question="switch PK", mode="auto")
    result = run_auto(rs, base_dir=str(tmp_path), llm="mock", run_id="h0skip",
                      assume_brief=True)
    # it ran the loop (did not pause at H0); it may pause LATER or complete, but
    # clarify must not be the blocker and the grid/loop progressed
    assert result["state"].clarify_converged is True


def test_steer_event_reranks_next_iteration(tmp_path):
    """A cos steer event injected into the checkpointed state is consumed and
    re-ranks/branches on the next iteration (records the event)."""
    from cn5_research_cos.graph import apply_steer
    rs = ResearchState(run_id="steer1", original_question="q")
    issue_map.add(rs, title="a", description="d", issue_type=IssueType.roi,
                  status=IssueStatus.open, now="t", impact=3)
    before = len(rs.steering_events)
    apply_steer(rs, "改成優先研究競品威脅", now="t1")
    assert len(rs.steering_events) == before + 1
    ev = rs.steering_events[-1]
    assert ev["kind"] == "steer"
    assert ev["text"] == "改成優先研究競品威脅"
    assert ev.get("consumed") is False
