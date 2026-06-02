"""Audit tiering seam: build_auditor(tier, model) is pluggable + model-configurable.

In P3 BOTH tiers wrap the SAME simulator (real Albert FSM = P6). This test only
asserts the SEAM exists and is configurable, so later phases swap models by
config not rewrite.
"""
from cn5_research_cos.brains.auditor_tier import build_auditor
from cn5_research_cos.brains.stubs import AuditorStub
from cn5_research_cos.models import AuditResult, ResearchState


def test_build_auditor_sentinel_default_is_an_auditor():
    a = build_auditor(tier="sentinel")
    out = a.audit(ResearchState(run_id="r", original_question="q"))
    assert isinstance(out, AuditResult)


def test_build_auditor_deep_is_an_auditor():
    a = build_auditor(tier="deep")
    out = a.audit(ResearchState(run_id="r", original_question="q"))
    assert isinstance(out, AuditResult)


def test_tier_recorded_on_auditor():
    assert build_auditor(tier="sentinel").tier == "sentinel"
    assert build_auditor(tier="deep").tier == "deep"


def test_model_is_configurable_and_recorded():
    a = build_auditor(tier="deep", model="claude-opus-4")
    assert a.model == "claude-opus-4"


def test_unknown_tier_rejected():
    try:
        build_auditor(tier="bogus")
    except ValueError:
        return
    raise AssertionError("unknown tier should raise ValueError")


def test_base_auditor_injectable_for_test_doubles():
    """A caller can inject the underlying auditor (e.g. a counting fake) so the
    graph wiring can be tested deterministically."""
    calls = {"n": 0}

    class Counting(AuditorStub):
        def audit(self, state):
            calls["n"] += 1
            return super().audit(state)

    a = build_auditor(tier="deep", base=Counting())
    a.audit(ResearchState(run_id="r", original_question="q"))
    assert calls["n"] == 1
