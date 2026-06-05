from cn5_research_cos.decision import triangulation as tri
from cn5_research_cos.models import Source, SourceType, SourceQuality


def _src(i, t, q): return Source(id=i, title=i, url="http://"+i, source_type=t, quality=q)


def test_two_secondary_agree_corroborated():
    obs = [("5", _src("A", SourceType.secondary, SourceQuality.medium)),
           ("5", _src("B", SourceType.secondary, SourceQuality.medium))]
    r = tri.triangulate(obs)
    assert r.value == "5" and r.status == "corroborated" and not r.contradiction


def test_one_primary_corroborated():
    obs = [("4", _src("DS", SourceType.primary, SourceQuality.high))]
    r = tri.triangulate(obs)
    assert r.value == "4" and r.status == "corroborated"


def test_single_secondary_weak():
    obs = [("4", _src("X", SourceType.secondary, SourceQuality.low))]
    r = tri.triangulate(obs)
    assert r.status == "weakly_sourced"


def test_contradiction_resolved_by_primary():
    obs = [("5", _src("blog", SourceType.secondary, SourceQuality.medium)),
           ("4", _src("DS", SourceType.primary, SourceQuality.high))]
    r = tri.triangulate(obs)
    assert r.contradiction is True and r.value == "4"  # primary wins
