"""Component 2 — LLM curator (opt-in, on survivors). Deterministic (mocked LLM).

GPTR's REAL 5 dimensions: Relevance / Credibility / Currency / Objectivity /
Quantitative-Value. A FILTER not a rewriter ("return the same source-list shape,
don't rewrite/summarize"); FALLS BACK to the uncurated list on parse failure. Off
by default behind a flag; uses call_structured (SMART/normal model).
"""
from __future__ import annotations

import pytest

from cn5_research_cos.llm import sdk_client
from cn5_research_cos.models import Source
from cn5_research_cos.ranking import curator


def _sources():
    return [
        Source(id="S-1", title="primary study", url="https://a.com/1"),
        Source(id="S-2", title="marketing fluff", url="https://b.com/2"),
        Source(id="S-3", title="data-rich report", url="https://c.com/3"),
    ]


def test_curate_selects_by_five_dimensions(monkeypatch):
    captured = {}

    def fake_call(system, user, schema, **kw):
        captured["system"] = system
        captured["schema"] = schema
        return {"kept_ids": ["S-1", "S-3"]}

    monkeypatch.setattr(sdk_client, "call_structured", fake_call)
    out = curator.curate(_sources(), issue="ROI of feature")
    ids = [s.id for s in out]
    assert ids == ["S-1", "S-3"]   # S-2 (marketing) filtered out
    # the prompt names GPTR's 5 real dimensions
    blob = captured["system"].lower()
    for dim in ("relevance", "credibility", "currency", "objectivity", "quantitative"):
        assert dim in blob


def test_curate_is_filter_not_rewriter(monkeypatch):
    """Survivors are the SAME Source objects, unmodified — never rewritten."""
    srcs = _sources()
    monkeypatch.setattr(sdk_client, "call_structured",
                        lambda *a, **k: {"kept_ids": ["S-1"]})
    out = curator.curate(srcs, issue="x")
    assert len(out) == 1
    assert out[0] is srcs[0]          # identity preserved
    assert out[0].title == "primary study"


def test_curate_falls_back_to_uncurated_on_parse_failure(monkeypatch):
    srcs = _sources()

    def boom(*a, **k):
        raise ValueError("bad json")

    monkeypatch.setattr(sdk_client, "call_structured", boom)
    out = curator.curate(srcs, issue="x")
    # fallback: return the uncurated list unchanged
    assert out == srcs


def test_curate_falls_back_when_kept_ids_missing(monkeypatch):
    srcs = _sources()
    monkeypatch.setattr(sdk_client, "call_structured", lambda *a, **k: {"unexpected": 1})
    out = curator.curate(srcs, issue="x")
    assert out == srcs


def test_curate_ignores_unknown_ids(monkeypatch):
    srcs = _sources()
    monkeypatch.setattr(sdk_client, "call_structured",
                        lambda *a, **k: {"kept_ids": ["S-1", "S-999"]})
    out = curator.curate(srcs, issue="x")
    assert [s.id for s in out] == ["S-1"]


def test_curate_empty_input_skips_llm(monkeypatch):
    called = {"n": 0}

    def spy(*a, **k):
        called["n"] += 1
        return {"kept_ids": []}

    monkeypatch.setattr(sdk_client, "call_structured", spy)
    assert curator.curate([], issue="x") == []
    assert called["n"] == 0     # no LLM call on empty input


def test_curate_disabled_by_default_flag(monkeypatch):
    """is_enabled reflects the env flag; off by default."""
    monkeypatch.delenv("CN5_COS_CURATOR", raising=False)
    assert curator.is_enabled() is False
    monkeypatch.setenv("CN5_COS_CURATOR", "1")
    assert curator.is_enabled() is True
