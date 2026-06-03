"""Component 2 — heuristic source ranking (deterministic, always-on, no LLM).

GPTR's cheap filter SKIPS embeddings on small input; at our scale we are always
in that regime, so we faithfully reproduce the small-input behavior WITHOUT
embeddings: URL dedup (collapse near-dup URLs), drop obvious junk, relevance =
issue-keyword overlap + recency/known-authority heuristic, cap top-k. Pure.
"""
from __future__ import annotations

from cn5_research_cos.models import Source, SourceQuality, SourceType
from cn5_research_cos.ranking import heuristic


def _src(sid, title, url=None, **kw):
    return Source(id=sid, title=title, url=url, **kw)


def test_url_dedup_collapses_near_duplicate_urls():
    sources = [
        _src("S-1", "A", url="https://example.com/page"),
        _src("S-2", "A dup", url="https://example.com/page/"),       # trailing slash
        _src("S-3", "A utm", url="https://example.com/page?utm_source=x"),  # tracking
        _src("S-4", "B", url="https://other.com/x"),
    ]
    out = heuristic.rank(sources, issue_keywords=[], top_k=10)
    urls = {s.url for s in out}
    # the three example.com/page variants collapse to ONE survivor
    assert len([s for s in out if "example.com/page" in (s.url or "")]) == 1
    assert any("other.com" in (s.url or "") for s in out)


def test_drops_obvious_junk():
    sources = [
        _src("S-1", "Real source", url="https://example.com/a"),
        _src("S-2", "", url=None),                       # no title, no url -> junk
        _src("S-3", "spam", url="https://bit.ly/abc"),   # shortener -> junk
    ]
    out = heuristic.rank(sources, issue_keywords=[], top_k=10)
    ids = {s.id for s in out}
    assert "S-1" in ids
    assert "S-2" not in ids
    assert "S-3" not in ids


def test_relevance_keyword_overlap_orders_results():
    sources = [
        _src("S-1", "Unrelated weather report", url="https://a.com/1"),
        _src("S-2", "I2C bus backward compatibility analysis", url="https://b.com/2"),
    ]
    out = heuristic.rank(sources, issue_keywords=["i2c", "compatibility"], top_k=2)
    # the keyword-matching source ranks first
    assert out[0].id == "S-2"


def test_known_authority_breaks_ties():
    sources = [
        _src("S-1", "blog post", url="https://randomblog.example/x",
             source_type=SourceType.secondary, quality=SourceQuality.low),
        _src("S-2", "primary standard", url="https://standards.example/y",
             source_type=SourceType.standard, quality=SourceQuality.high),
    ]
    out = heuristic.rank(sources, issue_keywords=[], top_k=2)
    # high-authority / high-quality source ranks first on a keyword tie
    assert out[0].id == "S-2"


def test_top_k_cap():
    sources = [_src(f"S-{i}", f"src {i} relevant", url=f"https://a.com/{i}")
               for i in range(10)]
    out = heuristic.rank(sources, issue_keywords=["relevant"], top_k=3)
    assert len(out) == 3


def test_empty_input_returns_empty():
    assert heuristic.rank([], issue_keywords=["x"], top_k=5) == []


def test_preserves_source_shape_no_rewrite():
    """A FILTER, not a rewriter: surviving sources are the SAME objects, unmodified."""
    s = _src("S-1", "keep me", url="https://a.com/1")
    out = heuristic.rank([s], issue_keywords=[], top_k=5)
    assert out == [s]
    assert out[0].title == "keep me"
