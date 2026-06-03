"""Task 1 (P5): memo data models + Source.excerpt field."""
from cn5_research_cos.models import Memo, MemoSection, BlockerType, Source


def test_blocker_type_has_six_kinds():
    vals = {b.value for b in BlockerType}
    assert vals == {"research", "internal_data", "permission",
                    "human_judgment", "bu_preference", "albert_decision"}


def test_memo_has_nine_sections_by_key():
    m = Memo(sections=[MemoSection(key="executive_answer", title="...", body="x")])
    assert m.sections[0].key == "executive_answer"
    assert m.section_keys() == ["executive_answer"]


def test_memo_defaults_not_emitted():
    m = Memo()
    assert m.emitted is False
    assert m.refused_reason is None
    assert m.section_keys() == []


def test_source_carries_excerpt_default_empty():
    s = Source(id="S-1", title="t", url="u", origin="web")
    assert s.excerpt == ""
