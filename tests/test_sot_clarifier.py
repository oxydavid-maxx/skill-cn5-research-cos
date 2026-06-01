"""Deterministic tests for the SOT clarifier wiring over the cn5_ask engine.

Driven by a SCRIPTED fake StepFn (no LLM). The real convergence rule is
ConvergenceRule(threshold_k=3, stability_window=2): it converges when >=3 of 4
signals are active AND that has held for 2 consecutive rounds. So a program that
reaches the threshold by turn 2 and stays there converges at turn 3 (rounds
turn2+turn3 both >=3). A 1/4 -> 2/4 -> 4/4 program would NOT converge at turn 3
because turn 2 (2/4) breaks the 2-round stability window — that is the rule
working as designed, not a bug. Here we script 1/4 -> 3/4 -> 4/4 so convergence
lands at turn 3, then a fake compile_fn produces a SOTBrief — proving the
loop+converge+compile wiring without any LLM.

Also exercises the turn-based driver (one step per CLI invocation) over a
SqliteSaver and the SOTBrief persistence + ResearchState.research_brief mirror.
"""
from __future__ import annotations

import json

import pytest

from cn5_ask import StepResult

from cn5_research_cos.sot import clarifier
from cn5_research_cos.sot.brief import SOTBrief, BriefStatus, load_latest


# --- scripted signal program (1/4 -> 2/4 -> 4/4) --------------------------- #
_PROGRAM = [
    {"C1": True, "C2": False, "C3": False, "C4": False},   # turn 1: 1/4
    {"C1": True, "C2": True, "C3": True, "C4": False},      # turn 2: 3/4 (>=k)
    {"C1": True, "C2": True, "C3": True, "C4": True},       # turn 3: 4/4 -> stable 2 rounds
    {"C1": True, "C2": True, "C3": True, "C4": True},       # held
]


def _scripted_step_fn(state, context):
    idx = state.get("turn_count", 0)  # 0-based index of the turn being produced
    prog = _PROGRAM[min(idx, len(_PROGRAM) - 1)]
    return StepResult(
        output={"questions": [f"Q for turn {idx + 1}"],
                "signal_rationale": {k: "scripted" for k in prog}},
        signals=dict(prog),
    )


def _fake_compile_fn(state):
    return SOTBrief(
        objective="scripted converged objective",
        deliverable="scripted deliverable",
        created_at="2026-06-01T00:00:00",
    ).model_dump(mode="json")


def test_convergence_rule_shape():
    rule = clarifier.convergence_rule()
    assert rule.signals == ["C1", "C2", "C3", "C4"]
    assert rule.threshold_k == 3
    assert rule.stability_window == 2


def test_scripted_loop_converges_at_turn_3(tmp_path):
    db = str(tmp_path / "clarify.db")
    sess = clarifier.ClarifySession(
        run_id="run-scripted",
        db_path=db,
        step_fn=_scripted_step_fn,
        compile_fn=_fake_compile_fn,
        base_dir=str(tmp_path),
    )

    # turn 1: 1/4 -> not converged, emits questions
    r1 = sess.step(dialogue=[{"role": "user", "text": "underspecified topic"}],
                   now="2026-06-01T00:00:01")
    assert r1["converged"] is False
    assert r1["turn_count"] == 1
    assert r1["questions"]

    # turn 2: 2/4 -> still not converged
    r2 = sess.step(dialogue=[{"role": "user", "text": "answer 1"}],
                   now="2026-06-01T00:00:02")
    assert r2["converged"] is False
    assert r2["turn_count"] == 2

    # turn 3: 4/4 -> CONVERGED -> compile -> SOTBrief saved + mirrored
    r3 = sess.step(dialogue=[{"role": "user", "text": "answer 2"}],
                   now="2026-06-01T00:00:03")
    assert r3["converged"] is True
    assert r3["turn_count"] == 3
    assert r3["brief"] is not None
    assert r3["brief"]["objective"] == "scripted converged objective"

    # brief.v1 persisted
    b = load_latest("run-scripted", base_dir=str(tmp_path))
    assert isinstance(b, SOTBrief)
    assert b.version == 1
    assert b.objective == "scripted converged objective"


def test_each_step_is_one_turn_not_run_to_completion(tmp_path):
    """The turn-based driver must advance EXACTLY one turn per call even though
    the scripted program would converge if allowed to loop internally."""
    db = str(tmp_path / "c.db")
    sess = clarifier.ClarifySession(
        run_id="run-one", db_path=db, step_fn=_scripted_step_fn,
        compile_fn=_fake_compile_fn, base_dir=str(tmp_path),
    )
    r1 = sess.step(dialogue=[{"role": "user", "text": "t"}], now="t1")
    assert r1["turn_count"] == 1  # NOT 3
    assert r1["converged"] is False


def test_forced_stop_at_hard_cap(tmp_path):
    """A program that never reaches 3/4 must forced-stop at max_turns and still
    compile (forced_stop also routes to compile in cn5_ask)."""
    flat = [{"C1": True, "C2": False, "C3": False, "C4": False}]

    def never_converge(state, context):
        return StepResult(output={"questions": ["q"], "signal_rationale": {}},
                          signals=dict(flat[0]))

    db = str(tmp_path / "cap.db")
    sess = clarifier.ClarifySession(
        run_id="run-cap", db_path=db, step_fn=never_converge,
        compile_fn=_fake_compile_fn, base_dir=str(tmp_path), max_turns=3,
    )
    last = None
    for i in range(3):
        last = sess.step(dialogue=[{"role": "user", "text": f"a{i}"}], now=f"t{i}")
    assert last["turn_count"] == 3
    assert last["forced_stop"] is True
    assert last["brief"] is not None  # forced-stop still compiles a draft brief


@pytest.mark.llm
def test_live_underspecified_not_converged_turn1():
    from cn5_research_cos.llm.sdk_client import has_api_key
    if not has_api_key():
        pytest.skip("no ANTHROPIC_API_KEY; skipping live clarifier test")
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        sess = clarifier.ClarifySession(
            run_id="run-live", db_path=os.path.join(td, "l.db"),
            step_fn=clarifier.sot_step_fn, compile_fn=clarifier.sot_compile_fn,
            base_dir=td,
        )
        r = sess.step(dialogue=[{"role": "user", "text": "幫我研究一下 switch IC"}],
                      now="2026-06-01T00:00:00")
        assert r["turn_count"] == 1
        assert r["converged"] is False
        assert len(r["questions"]) >= 1
