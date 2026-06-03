"""Albert Challenge Map artifact operations.

``add`` is the legacy mint-every-call constructor (kept for back-compat callers).
``upsert`` (P4b Component 1) dedups a re-raised challenge against the existing
LIVE (open/answered) challenges by a stable deterministic key — an explicit prior
``challenge_id`` the auditor references, OR a normalized-text ``difflib`` ratio at
or above ``MERGE_THRESHOLD`` — and UPDATES the matched challenge in place
(status / current_answer / evidence_refs / rounds_seen) instead of minting a
duplicate. A genuinely new challenge gets a new id. Pure / deterministic.

override-reducer semantics (copied from ODR): accumulating fields (evidence_refs)
DEFAULT-APPEND across rounds — never silently dropped — and are replaced only on an
explicit ``override=True``.
"""
from __future__ import annotations

import difflib

from ..models import AlbertChallenge, ChallengeStatus, Classification, ResearchState

# difflib similarity at/above which a re-raised challenge is treated as the SAME
# challenge (the spec's 0.85 fuzzy threshold).
MERGE_THRESHOLD = 0.85

# Statuses that are still "live" — a dedup target for an incoming challenge. A
# resolved / escalated challenge is closed: a new challenge with similar text must
# NOT silently re-open it (it gets a fresh id instead).
_LIVE_STATUSES = (
    ChallengeStatus.open,
    ChallengeStatus.answered,
    ChallengeStatus.needs_internal_data,
    ChallengeStatus.needs_albert_decision,
    ChallengeStatus.needs_bu_judgment,
)


def _next_id(state: ResearchState) -> str:
    return "C-%03d" % (len(state.albert_challenge_map) + 1)


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace for a stable fuzzy-match key."""
    return " ".join((text or "").lower().split())


def add(
    state: ResearchState,
    *,
    challenge: str,
    why_albert_would_ask: str = "",
    status: ChallengeStatus = ChallengeStatus.open,
    classification: Classification | None = None,
    confidence: int = 0,
) -> AlbertChallenge:
    """Legacy: mint a NEW challenge every call (no dedup). Kept for back-compat."""
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


def _find_live_match(
    state: ResearchState, challenge: str, *, prior_challenge_id: str | None
) -> AlbertChallenge | None:
    """Return the existing LIVE challenge this incoming one should merge onto, or
    None for a genuinely new challenge.

    Precedence: an explicit ``prior_challenge_id`` the auditor references wins
    (even if the text was rephrased); otherwise the best fuzzy text match among
    LIVE challenges with ratio >= MERGE_THRESHOLD.
    """
    if prior_challenge_id:
        existing = state.albert_challenge_map.get(prior_challenge_id)
        if existing is not None:
            return existing

    key = _normalize(challenge)
    best: AlbertChallenge | None = None
    best_ratio = MERGE_THRESHOLD
    for ch in state.albert_challenge_map.values():
        if ch.status not in _LIVE_STATUSES:
            continue
        ratio = difflib.SequenceMatcher(None, key, _normalize(ch.challenge)).ratio()
        if ratio >= best_ratio:
            best = ch
            best_ratio = ratio
    return best


def upsert(
    state: ResearchState,
    *,
    challenge: str,
    why_albert_would_ask: str | None = None,
    current_answer: str | None = None,
    status: ChallengeStatus | None = None,
    classification: Classification | None = None,
    confidence: int | None = None,
    evidence_refs: list[str] | None = None,
    issue_id: str | None = None,
    prior_challenge_id: str | None = None,
    override: bool = False,
) -> AlbertChallenge:
    """Dedup-aware insert/merge of an audit challenge.

    A match against a LIVE challenge (explicit ``prior_challenge_id`` or fuzzy text
    ratio >= MERGE_THRESHOLD) UPDATES that challenge in place and bumps
    ``rounds_seen``; a non-match mints a new challenge (``rounds_seen=1``).

    Field-merge rules:
      * scalar fields (status, current_answer, why_albert_would_ask, classification,
        confidence) are overwritten only when a non-None value is supplied;
      * ``evidence_refs`` DEFAULT-APPEND (dedup-preserving order) — never silently
        dropped — unless ``override=True`` replaces them.
    """
    match = _find_live_match(state, challenge, prior_challenge_id=prior_challenge_id)

    if match is None:
        ch = AlbertChallenge(
            id=_next_id(state),
            challenge=challenge,
            why_albert_would_ask=why_albert_would_ask or "",
            current_answer=current_answer or "",
            status=status or ChallengeStatus.open,
            classification=classification,
            confidence=confidence or 0,
            evidence_refs=list(evidence_refs or []),
            issue_id=issue_id,
            rounds_seen=1,
        )
        state.albert_challenge_map[ch.id] = ch
        return ch

    # Merge onto the existing live challenge.
    match.rounds_seen += 1
    if issue_id is not None:
        match.issue_id = issue_id
    if why_albert_would_ask is not None:
        match.why_albert_would_ask = why_albert_would_ask
    if current_answer is not None:
        match.current_answer = current_answer
    if status is not None:
        match.status = status
    if classification is not None:
        match.classification = classification
    if confidence is not None:
        match.confidence = confidence
    if evidence_refs is not None:
        if override:
            match.evidence_refs = list(evidence_refs)
        else:
            for ref in evidence_refs:
                if ref not in match.evidence_refs:
                    match.evidence_refs.append(ref)
    return match


def get(state: ResearchState, challenge_id: str) -> AlbertChallenge | None:
    return state.albert_challenge_map.get(challenge_id)
