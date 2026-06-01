"""Deterministic tests for the SOTBrief model + persist/version/load/supersede.

No LLM, no wall-clock in core: created_at is supplied by the caller.
"""
from __future__ import annotations

import json

import pytest

from cn5_research_cos.sot.brief import (
    SOTBrief,
    BriefStatus,
    save,
    load_latest,
    load_version,
    list_versions,
    supersede,
)


def _brief(objective="一句話的北極星目標", status=BriefStatus.draft, **kw):
    base = dict(
        objective=objective,
        background="背景",
        in_scope=["A", "B"],
        out_of_scope=["C"],
        constraints=["成本 < X"],
        assumptions=["假設1"],
        forbidden_directions=["不要做 marketing 比較"],
        available_sources=["datasheet"],
        deliverable="選型比較表",
        success_criteria=["涵蓋 3 家競品"],
        decision_served="BU 選型決策",
        decision_criterion="TSN 領先 + 成本",
        open_questions=["供應鏈鎖哪幾家？"],
        status=status,
        confirmed_by=None,
        created_at="2026-06-01T00:00:00",
    )
    base.update(kw)
    return SOTBrief(**base)


def test_model_round_trip():
    b = _brief()
    assert SOTBrief.model_validate_json(b.model_dump_json()) == b


def test_defaults_and_optional_fields():
    b = SOTBrief(objective="o", deliverable="d", created_at="2026-06-01T00:00:00")
    assert b.version == 1
    assert b.status == BriefStatus.draft
    assert b.in_scope == [] and b.out_of_scope == []
    assert b.decision_served is None and b.decision_criterion is None
    assert b.confirmed_by is None


def test_save_writes_md_and_json_sidecar(tmp_path):
    b = _brief()
    md_path = save(b, run_id="run-x", base_dir=str(tmp_path))
    assert md_path.exists()
    assert md_path.name == "brief.v1.md"
    sidecar = md_path.with_suffix(".json")
    assert sidecar.exists()
    # md is human-readable and contains the objective
    text = md_path.read_text(encoding="utf-8")
    assert "一句話的北極星目標" in text
    # json sidecar round-trips losslessly
    loaded = SOTBrief.model_validate_json(sidecar.read_text(encoding="utf-8"))
    assert loaded == b


def test_save_increments_version_field(tmp_path):
    v1 = _brief(objective="v1 obj")
    save(v1, run_id="run-x", base_dir=str(tmp_path))
    v2 = _brief(objective="v2 obj", version=2)
    p2 = save(v2, run_id="run-x", base_dir=str(tmp_path))
    assert p2.name == "brief.v2.md"
    assert {p.name for p in list_versions("run-x", base_dir=str(tmp_path))} == {
        "brief.v1.md",
        "brief.v2.md",
    }


def test_load_latest_returns_highest_version(tmp_path):
    save(_brief(objective="v1", version=1), run_id="r", base_dir=str(tmp_path))
    save(_brief(objective="v2", version=2), run_id="r", base_dir=str(tmp_path))
    latest = load_latest("r", base_dir=str(tmp_path))
    assert latest.version == 2 and latest.objective == "v2"


def test_load_latest_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_latest("nope", base_dir=str(tmp_path))


def test_load_version_specific(tmp_path):
    save(_brief(objective="v1", version=1), run_id="r", base_dir=str(tmp_path))
    save(_brief(objective="v2", version=2), run_id="r", base_dir=str(tmp_path))
    assert load_version("r", 1, base_dir=str(tmp_path)).objective == "v1"


def test_supersede_marks_prior_versions(tmp_path):
    save(_brief(objective="v1", version=1, status=BriefStatus.confirmed),
         run_id="r", base_dir=str(tmp_path))
    # confirming a new v2 supersedes the prior confirmed v1
    superseded = supersede("r", up_to_version=1, base_dir=str(tmp_path),
                           now="2026-06-02T00:00:00")
    assert superseded == [1]
    reloaded = load_version("r", 1, base_dir=str(tmp_path))
    assert reloaded.status == BriefStatus.superseded


def test_save_is_idempotent_round_trip_with_chinese(tmp_path):
    b = _brief()
    save(b, run_id="r", base_dir=str(tmp_path))
    reloaded = load_latest("r", base_dir=str(tmp_path))
    assert reloaded == b
    # the json sidecar must be valid JSON
    sidecar = tmp_path / "r" / "brief.v1.json"
    json.loads(sidecar.read_text(encoding="utf-8"))
