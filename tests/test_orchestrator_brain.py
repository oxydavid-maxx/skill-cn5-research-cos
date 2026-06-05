from pathlib import Path

from cn5_research_cos.brains import build_brains
from cn5_research_cos.brains import orchestrator as orch
from cn5_research_cos.models import ResearchState, TaskGrid, CellStatus, AlbertChallenge, ChallengeStatus


def test_orchestrator_seeds_grid_from_brief():
    brains = build_brains("mock")
    rs = ResearchState(run_id="r", original_question="switch PK",
                       success_form="vendor x spec_group table")
    grid = brains.orchestrator.plan(rs)
    assert isinstance(grid, TaskGrid) and grid.cells


def test_orchestrator_adds_cells_for_uncovered_gaps():
    brains = build_brains("mock")
    rs = ResearchState(run_id="r", original_question="q")
    rs.task_grid = TaskGrid(axes=["vendor", "spec_group"])
    rs.albert_challenge_map["c1"] = AlbertChallenge(
        id="c1", challenge="NXP TSN gate-list depth unknown",
        status=ChallengeStatus.open, issue_id=None)
    grid = brains.orchestrator.plan(rs)
    assert any(c.status == CellStatus.open for c in grid.cells.values())


def _switch_pk_question() -> str:
    p = Path(__file__).resolve().parent.parent / "topics" / "switch pk.txt"
    return p.read_text(encoding="utf-8")


def test_orchestrator_prompt_is_condensed(monkeypatch):
    """RealOrchestrator must NOT dump the full ~9KB topic into the LLM prompt
    (root cause of the real-run Sonnet timeout). It condenses to vendor list +
    spec-group section headers + success_form, and uses a fail-fast timeout."""
    captured = {}

    def fake_call_structured(system, user, schema, *, model=None,
                             timeout_sec=300, attempts=5):
        captured["user"] = user
        captured["model"] = model
        captured["timeout_sec"] = timeout_sec
        captured["attempts"] = attempts
        return {"cells": [
            {"vendor": "NXP", "spec_group": "Switch fabric",
             "objective": "x", "impact": 5},
        ]}

    monkeypatch.setattr(orch, "call_structured", fake_call_structured)

    full = _switch_pk_question()
    rs = ResearchState(run_id="r", original_question=full,
                       success_form="vendor x spec_group silicon PK table")
    grid = orch.RealOrchestrator().plan(rs)

    # Output contract still holds.
    assert isinstance(grid, TaskGrid) and grid.cells

    user = captured["user"]
    # Condensed: far smaller than the raw 9KB question.
    assert len(full) > 5000  # guard: fixture really is the big topic
    assert len(user) < 3000, f"prompt not condensed: {len(user)} chars"
    # Still carries the decomposition axes the orchestrator needs.
    assert "NXP" in user
    assert "Infineon" in user
    assert ("Switch fabric" in user) or ("TSN" in user)
    assert "vendor x spec_group silicon PK table" in user
    # Fail-fast timeout policy: generous single-ish shot, few retries.
    assert captured["timeout_sec"] == 600
    assert captured["attempts"] == 2
    # Model stays None -> Sonnet default.
    assert captured["model"] is None


def test_orchestrator_emits_success_criteria(monkeypatch):
    import cn5_research_cos.brains.orchestrator as orch
    from cn5_research_cos.models import ResearchState
    def fake(system, user, schema, **kw):
        return {"cells": [{"vendor":"NXP","spec_group":"fabric","objective":"o",
                           "success_criteria":["packet_buffer"],"expected_sources":["datasheet PDF"]}]}
    monkeypatch.setattr(orch, "call_structured", fake)
    g = orch.RealOrchestrator().plan(ResearchState(run_id="r", original_question="q"))
    cell = g.cells["NXP|fabric"]
    assert cell.success_criteria == ["packet_buffer"]
    assert cell.expected_sources == ["datasheet PDF"]
