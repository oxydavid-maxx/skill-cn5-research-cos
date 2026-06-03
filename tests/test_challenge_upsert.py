"""Component 1 — challenge merge/upsert (deterministic, pure).

The bug: ``challenge_map.add`` mints a NEW id every call, so a challenge raised
round N and re-raised (verbatim or fuzzily) round N+1 piles up as a duplicate and
its prior ``status``/``current_answer`` is lost. ``upsert`` dedups against the
existing OPEN challenges by a stable deterministic key (normalized-text fuzzy
``difflib`` ratio >= threshold, OR an explicit prior ``challenge_id`` the auditor
references) and UPDATES the matched challenge in place (status, current_answer,
evidence_refs, rounds_seen) instead of minting a duplicate.
"""
from __future__ import annotations

from cn5_research_cos.artifacts import challenge_map
from cn5_research_cos.models import ChallengeStatus, ResearchState


def _state() -> ResearchState:
    return ResearchState(run_id="r", original_question="q")


def test_upsert_same_challenge_next_round_merges_not_duplicates():
    s = _state()
    c1 = challenge_map.upsert(s, challenge="競品是否已有此能力?",
                              why_albert_would_ask="Albert 會問競品")
    assert c1.id == "C-001"
    assert c1.rounds_seen == 1
    # Round N+1: the SAME challenge resurfaces with an answer.
    c2 = challenge_map.upsert(
        s, challenge="競品是否已有此能力?",
        current_answer="競品 X 已有, 但無 Y", status=ChallengeStatus.answered,
        evidence_refs=["S-1"],
    )
    # merged onto the SAME id, not a new one
    assert c2.id == "C-001"
    assert len(s.albert_challenge_map) == 1
    assert c2.rounds_seen == 2
    assert c2.status == ChallengeStatus.answered
    assert c2.current_answer == "競品 X 已有, 但無 Y"
    assert "S-1" in c2.evidence_refs


def test_upsert_fuzzy_match_merges():
    s = _state()
    challenge_map.upsert(s, challenge="What is the ROI of this feature for the BU?")
    # near-duplicate phrasing (>= 0.85 difflib ratio) -> merge
    c2 = challenge_map.upsert(
        s, challenge="What is the ROI of this feature for the BU??",
        status=ChallengeStatus.answered,
    )
    assert len(s.albert_challenge_map) == 1
    assert c2.id == "C-001"
    assert c2.status == ChallengeStatus.answered


def test_upsert_distinct_challenge_gets_new_id():
    s = _state()
    a = challenge_map.upsert(s, challenge="競品是否已有此能力?")
    b = challenge_map.upsert(s, challenge="這個專案的法遵風險是什麼?")
    assert a.id == "C-001" and b.id == "C-002"
    assert len(s.albert_challenge_map) == 2


def test_upsert_explicit_prior_id_overrides_fuzzy():
    s = _state()
    a = challenge_map.upsert(s, challenge="原始挑戰")
    # auditor references the prior id directly -> update that one even if text
    # differs (e.g. an escalated rephrasing)
    b = challenge_map.upsert(
        s, challenge="完全不同的措辭重述", prior_challenge_id=a.id,
        status=ChallengeStatus.needs_bu_judgment,
    )
    assert b.id == a.id
    assert len(s.albert_challenge_map) == 1
    assert b.status == ChallengeStatus.needs_bu_judgment


def test_upsert_resolved_challenge_does_not_match_new_open():
    """A RESOLVED challenge is closed; a genuinely new challenge with similar text
    must NOT silently re-open it — only OPEN/answered (still-live) challenges are
    dedup targets."""
    s = _state()
    a = challenge_map.upsert(s, challenge="同一句話")
    a.status = ChallengeStatus.resolved
    b = challenge_map.upsert(s, challenge="同一句話")
    # resolved is not a live dedup target -> new id
    assert b.id != a.id
    assert len(s.albert_challenge_map) == 2


def test_upsert_default_appends_evidence_never_drops():
    """override_reducer semantics: evidence_refs accumulate across rounds (append),
    never silently replaced."""
    s = _state()
    challenge_map.upsert(s, challenge="X", evidence_refs=["S-1"])
    c = challenge_map.upsert(s, challenge="X", evidence_refs=["S-2"])
    assert c.evidence_refs == ["S-1", "S-2"]


def test_upsert_explicit_override_replaces_evidence():
    """An explicit override replaces (the one escape hatch from append-by-default)."""
    s = _state()
    challenge_map.upsert(s, challenge="X", evidence_refs=["S-1"])
    c = challenge_map.upsert(s, challenge="X", evidence_refs=["S-9"], override=True)
    assert c.evidence_refs == ["S-9"]


def test_add_still_monotonic_back_compat():
    """The legacy ``add`` (mint-every-call) stays for back-compat callers/tests."""
    s = _state()
    c1 = challenge_map.add(s, challenge="ch1")
    c2 = challenge_map.add(s, challenge="ch2")
    assert c1.id == "C-001" and c2.id == "C-002"
