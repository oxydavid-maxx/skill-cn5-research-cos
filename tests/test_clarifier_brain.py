from cn5_research_cos.brains import build_brains
from cn5_research_cos.models import ResearchState


def test_mock_clarifier_asks_for_missing_criteria():
    brains = build_brains("mock")
    rs = ResearchState(run_id="r", original_question="switch PK")
    qs = brains.clarifier.ask(rs, missing=["purpose", "success"])
    assert isinstance(qs, list) and qs
    joined = " ".join(qs)
    assert "用途" in joined or "決策" in joined
