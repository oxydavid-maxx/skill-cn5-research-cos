"""Task 5 (P5): deterministic memo assembly (9 sections + blocker labels)."""
from cn5_research_cos.synthesis.memo import assemble_memo, NINE_SECTION_KEYS
from cn5_research_cos.brains.synthesis import MockSynthesizer, SECTION_KEYS
from cn5_research_cos.models import (
    AlbertChallenge, BlockerType, ChallengeStatus, IssueNode, IssueStatus,
    IssueType, ResearchState,
)


def _state():
    rs = ResearchState(run_id="r", original_question="DAA 是否該做？")
    rs.issue_map = {
        "I-perm": IssueNode(id="I-perm", title="授權問題", description="d",
                            issue_type=IssueType.technical,
                            status=IssueStatus.blocked_by_permission,
                            impact=4, confidence=1),
    }
    rs.albert_challenge_map = {
        "C-bu": AlbertChallenge(id="C-bu", challenge="BU 偏好?",
                                status=ChallengeStatus.needs_bu_judgment),
    }
    return rs


def test_section_keys_single_source_of_truth():
    assert NINE_SECTION_KEYS == SECTION_KEYS
    assert len(NINE_SECTION_KEYS) == 9


def test_memo_has_nine_sections_in_order():
    memo = assemble_memo(_state(), MockSynthesizer())
    assert memo.section_keys() == NINE_SECTION_KEYS
    assert len(memo.sections) == 9


def test_every_section_has_title_and_body():
    memo = assemble_memo(_state(), MockSynthesizer())
    for s in memo.sections:
        assert s.title, f"section {s.key} missing title"
        assert s.body, f"section {s.key} missing body"


def test_blocking_section_carries_labeled_blockers():
    memo = assemble_memo(_state(), MockSynthesizer())
    kinds = {b.blocker_type for b in memo.blockers}
    assert BlockerType.permission in kinds
    assert BlockerType.bu_preference in kinds
    # the blocker labels are surfaced into the §4 blocking section body
    blocking = next(s for s in memo.sections if s.key == "blocking")
    assert "permission" in blocking.body or "授權問題" in blocking.body


def test_albert_section_reflects_challenge_status():
    memo = assemble_memo(_state(), MockSynthesizer())
    alb = next(s for s in memo.sections if s.key == "albert_challenge_map")
    assert "needs_bu_judgment" in alb.body or "BU 偏好" in alb.body


def test_assembly_does_not_set_emitted():
    memo = assemble_memo(_state(), MockSynthesizer())
    assert memo.emitted is False
