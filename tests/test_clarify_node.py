import cn5_research_cos.graph as g
from cn5_research_cos.models import ResearchState

class _Brains:
    class _Clar:
        def ask(self, rs, missing): return [f"Q:{m}" for m in missing]
    clarifier = _Clar()

def test_clarify_blocks_until_four_pinned(monkeypatch):
    asks = {}
    monkeypatch.setattr(g, "interrupt", lambda payload: asks.setdefault("p", payload) or {"answer": "x"})
    rs = ResearchState(run_id="r", original_question="q")
    state = {"research_state": rs, "brains": _Brains(), "mode": "interactive"}
    g.node_clarify(state)
    assert "p" in asks
    assert rs.clarify_converged is False

def test_clarify_passes_when_converged():
    rs = ResearchState(run_id="r", original_question="q",
                       decision_criterion="RFQ", success_form="table",
                       research_brief="scope x", fallback_behavior_if_human_unavailable="public-only")
    state = {"research_state": rs, "brains": _Brains(), "mode": "auto"}
    out = g.node_clarify(state)
    assert out["research_state"].clarify_converged is True
