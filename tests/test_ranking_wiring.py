"""Component 2 — ranking wired into the loop AFTER research, BEFORE compress."""
from __future__ import annotations

from cn5_research_cos.models import (Claim, EvidenceBundle, Source, SourceQuality,
                                     SourceType)
from cn5_research_cos.ranking import pipeline


def _bundle():
    return EvidenceBundle(
        query="i2c compatibility",
        issue_id="I-1",
        sources=[
            Source(id="S-1", title="i2c compatibility standard",
                   url="https://std.example/a", source_type=SourceType.standard,
                   quality=SourceQuality.high),
            Source(id="S-2", title="i2c compatibility standard dup",
                   url="https://std.example/a/", source_type=SourceType.standard,
                   quality=SourceQuality.high),                       # near-dup URL
            Source(id="S-3", title="", url=None),                     # junk
            Source(id="S-4", title="unrelated cooking blog",
                   url="https://b.example/x", source_type=SourceType.secondary,
                   quality=SourceQuality.low),
        ],
        claims=[
            Claim(claim="c1", source_refs=["S-1"]),
            Claim(claim="c2", source_refs=["S-3"]),    # cites the junk source
        ],
    )


def test_pipeline_dedups_and_drops_junk_and_keeps_top_k():
    out = pipeline.apply(_bundle(), top_k=2)
    ids = {s.id for s in out.sources}
    # near-dup collapsed (one of S-1/S-2), junk S-3 dropped
    assert "S-3" not in ids
    assert not ({"S-1", "S-2"} <= ids)   # not both dup variants survive
    assert len(out.sources) <= 2


def test_pipeline_reprunes_claim_refs_to_surviving_sources():
    """A claim that cited a dropped source must not keep a dangling ref."""
    out = pipeline.apply(_bundle(), top_k=4)
    surviving = {s.id for s in out.sources}
    for c in out.claims:
        for ref in c.source_refs:
            assert ref in surviving


def test_pipeline_curator_off_by_default(monkeypatch):
    """With the flag unset the curator is NOT invoked (heuristic-only)."""
    from cn5_research_cos.llm import sdk_client
    called = {"n": 0}
    monkeypatch.delenv("CN5_COS_CURATOR", raising=False)
    monkeypatch.setattr(sdk_client, "call_structured",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {"kept_ids": []})
    pipeline.apply(_bundle(), top_k=4)
    assert called["n"] == 0


def test_pipeline_curator_on_when_flagged(monkeypatch):
    from cn5_research_cos.llm import sdk_client
    monkeypatch.setenv("CN5_COS_CURATOR", "1")
    monkeypatch.setattr(sdk_client, "call_structured",
                        lambda *a, **k: {"kept_ids": ["S-1"]})
    out = pipeline.apply(_bundle(), top_k=4)
    assert [s.id for s in out.sources] == ["S-1"]
