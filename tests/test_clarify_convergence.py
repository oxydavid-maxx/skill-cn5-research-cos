from cn5_research_cos.decision import clarify
from cn5_research_cos.models import ResearchState

def _rs(**kw):
    rs = ResearchState(run_id="r", original_question="q")
    for k, v in kw.items(): setattr(rs, k, v)
    return rs

def test_not_converged_when_any_criterion_missing():
    rs = _rs(decision_criterion="RFQ scoring", success_form="PK table")
    ok, missing = clarify.clarify_converged(rs)
    assert ok is False
    assert "scope" in missing and "constraints" in missing

def test_converged_when_all_four_pinned():
    rs = _rs(decision_criterion="RFQ scoring", success_form="PK table",
             research_brief="scope: silicon only; out: gateway apps",
             fallback_behavior_if_human_unavailable="public-only, NDA out")
    ok, missing = clarify.clarify_converged(rs)
    assert ok is True and missing == []
