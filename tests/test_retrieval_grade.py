from cn5_research_cos.decision import retrieval_grade as rg
from cn5_research_cos.models import Source, SourceType, SourceQuality


def test_grade_primary_high_is_correct():
    s = Source(id="S1", title="datasheet", url="https://nxp.com/x.pdf",
               source_type=SourceType.primary, quality=SourceQuality.high)
    assert rg.grade_source(s) == "correct"


def test_grade_low_quality_is_incorrect():
    s = Source(id="S2", title="blog", url="http://b", source_type=SourceType.marketing,
               quality=SourceQuality.low)
    assert rg.grade_source(s) == "incorrect"


def test_grade_medium_is_ambiguous():
    s = Source(id="S3", title="distrib", url="http://d", source_type=SourceType.secondary,
               quality=SourceQuality.medium)
    assert rg.grade_source(s) == "ambiguous"
