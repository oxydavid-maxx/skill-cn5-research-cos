"""Pure deterministic tests for conflict.detect on hand-built (brief, change) pairs.

No LLM. A conflict means a proposed change contradicts the current SOT value;
the engine NEVER silently overwrites — it surfaces the Conflict for a human.
"""
from __future__ import annotations

from cn5_research_cos.sot.brief import SOTBrief
from cn5_research_cos.sot.conflict import Conflict, Severity, detect


def _brief(**kw) -> SOTBrief:
    base = dict(
        objective="比較 24-port automotive switch IC 的 MAC 設計，產出選型表",
        deliverable="選型比較表",
        in_scope=["Ethernet MAC IP"],
        out_of_scope=["TSN scheduler"],
        constraints=["成本 < 5 USD"],
        decision_criterion="成本優先",
        created_at="2026-06-01T00:00:00",
    )
    base.update(kw)
    return SOTBrief(**base)


def test_no_conflict_when_change_matches_scalar():
    b = _brief()
    assert detect(b, {"deliverable": "選型比較表"}) is None


def test_no_conflict_when_field_absent_in_brief():
    b = _brief(decision_served=None)
    # adding a value where the brief had None is NOT a conflict (it's a fill-in)
    assert detect(b, {"decision_served": "BU 選型決策"}) is None


def test_scalar_contradiction_is_conflict():
    b = _brief(deliverable="選型比較表")
    c = detect(b, {"deliverable": "一頁式 executive memo"})
    assert isinstance(c, Conflict)
    assert c.field == "deliverable"
    assert c.sot_value == "選型比較表"
    assert c.new_value == "一頁式 executive memo"
    assert c.severity == Severity.high  # deliverable/objective = high severity


def test_objective_contradiction_is_high_severity():
    b = _brief()
    c = detect(b, {"objective": "改成研究 PCIe switch"})
    assert c is not None and c.severity == Severity.high


def test_decision_criterion_change_is_conflict():
    b = _brief(decision_criterion="成本優先")
    c = detect(b, {"decision_criterion": "TSN 領先優先"})
    assert c is not None and c.field == "decision_criterion"


def test_scope_direct_contradiction_in_scope_vs_out_of_scope():
    # proposing to ADD "TSN scheduler" to in_scope when it is in out_of_scope
    b = _brief(in_scope=["Ethernet MAC IP"], out_of_scope=["TSN scheduler"])
    c = detect(b, {"in_scope": ["Ethernet MAC IP", "TSN scheduler"]})
    assert c is not None
    assert c.field == "in_scope"
    assert "TSN scheduler" in str(c.new_value)
    assert c.severity == Severity.high


def test_list_pure_addition_is_not_conflict():
    b = _brief(in_scope=["Ethernet MAC IP"], out_of_scope=["TSN scheduler"])
    # adding a new, non-contradicting item is a fill-in, not a conflict
    assert detect(b, {"in_scope": ["Ethernet MAC IP", "PHY interface"]}) is None


def test_constraint_relaxation_flagged_medium():
    b = _brief(constraints=["成本 < 5 USD"])
    c = detect(b, {"constraints": []})  # dropping a stated constraint
    assert c is not None
    assert c.field == "constraints"
    assert c.severity == Severity.medium


def test_source_is_recorded_in_conflict():
    b = _brief()
    c = detect(b, {"deliverable": "memo"}, source="revise-brief")
    assert c is not None and c.source == "revise-brief"


def test_conflict_round_trip():
    c = Conflict(field="deliverable", sot_value="x", new_value="y",
                 source="test", severity=Severity.high)
    assert Conflict.model_validate_json(c.model_dump_json()) == c
