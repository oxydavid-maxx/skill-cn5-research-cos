"""Albert Challenge Map artifact operations."""
from __future__ import annotations

from ..models import AlbertChallenge, ChallengeStatus, Classification, ResearchState


def _next_id(state: ResearchState) -> str:
    return "C-%03d" % (len(state.albert_challenge_map) + 1)


def add(
    state: ResearchState,
    *,
    challenge: str,
    why_albert_would_ask: str = "",
    status: ChallengeStatus = ChallengeStatus.open,
    classification: Classification | None = None,
    confidence: int = 0,
) -> AlbertChallenge:
    ch = AlbertChallenge(
        id=_next_id(state),
        challenge=challenge,
        why_albert_would_ask=why_albert_would_ask,
        status=status,
        classification=classification,
        confidence=confidence,
    )
    state.albert_challenge_map[ch.id] = ch
    return ch


def get(state: ResearchState, challenge_id: str) -> AlbertChallenge | None:
    return state.albert_challenge_map.get(challenge_id)
