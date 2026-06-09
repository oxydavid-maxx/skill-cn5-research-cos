import cn5_research_cos.graph as g


def test_research_status_emitted_in_collect(monkeypatch):
    calls = []
    monkeypatch.setattr(g._obs, "render_research_status", lambda rs: "DASH")
    orig = g._report
    def spy(state, name, fn, *a):
        calls.append(name)
        return orig(state, name, fn, *a)
    monkeypatch.setattr(g, "_report", spy)
    from cn5_research_cos.models import ResearchState, TaskGrid
    state = {"research_state": ResearchState(run_id="r", original_question="q", task_grid=TaskGrid()),
             "now": "t", "worker_results": [], "prereqs": {}, "base_dir": "runs"}
    g.node_collect(state)
    assert "research_status" in calls


def test_convergence_readiness_not_emitted_as_live_cards():
    # the two retired stages must no longer be emitted via _report anywhere in graph.py
    import inspect
    src = inspect.getsource(g)
    assert '_report(state, "convergence"' not in src
    assert '_report(state, "readiness"' not in src
