"""StageReporter — flushed, non-tty-safe per-stage stdout writer (P5b Task 1).

The hard requirement (user directive 2026-06-03): a colleague running ``cos run``
MUST be able to WATCH the adversarial debate live on screen, and the per-stage
output MUST still arrive when stdout is piped / redirected / captured by a
subprocess ``stdout=PIPE`` / run in the background — incrementally, NOT held in a
buffer until process exit.

Design choice: PLAIN ``stream.write(...) + stream.flush()`` rather than a Rich
``Console``. Rich auto-detects a non-tty and, while it still writes, its markup /
soft-wrap behaviour and any future ``force_terminal`` regressions are an avoidable
risk for the ONE guarantee that matters here (bytes reach the pipe, flushed, per
stage). A plain write+flush is the simplest thing that provably emits in every
invocation form and is trivially red-teamable (Task 5). No LLM, no wall-clock.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from .errors import VisibilityContractError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models import AuditResult, Decision, ReadinessScore, ResearchState


class StageReporter:
    """Writes a labeled, delimited per-stage block to ``stream`` and FLUSHES after
    every stage so the content is delivered incrementally (never buffered until
    process exit). Works with any text stream: ``sys.stdout``, a ``StringIO``, a
    real file, or a subprocess-captured pipe.

    The reporter is intentionally dumb: a node renders its block (see
    ``render_*`` helpers) and hands the finished string to ``stage(name, body)``.
    The reporter only labels + writes + flushes.
    """

    def __init__(self, stream: TextIO | None = None, *, run_dir=None) -> None:
        self.stream: TextIO = stream if stream is not None else sys.stdout
        # P5d: the durable sink — the ONE real 100%. If a run_dir is given, every
        # stage block is appended to ``<run_dir>/debate.md`` (utf-8, flushed),
        # fail-CLOSED. run_dir is OPTIONAL (back-compat: a StringIO-only reporter
        # with no run_dir writes no file and behaves exactly as it did in P5b).
        self._debate_path: Path | None = (
            Path(run_dir) / "debate.md" if run_dir is not None else None
        )
        if self._debate_path is not None:
            try:
                self._debate_path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise VisibilityContractError(
                    f"Failed to create debate directory {self._debate_path.parent}: {exc}",
                    sink=str(self._debate_path.parent),
                ) from exc

    def stage(self, name: str, body: str) -> None:
        """Write a ``=== [name] ===`` header, the body, and a trailing blank line,
        then FLUSH. The flush is the guarantee that the block reaches the pipe now
        (not at process exit). If a ``run_dir`` was given, the SAME block is first
        appended to the durable ``debate.md`` sink (fail-closed)."""
        block = f"=== [{name}] ===\n{body}\n\n"
        self._persist(name, block)
        self.stream.write(block)
        # Flush AFTER the whole block so a reader sees the complete stage at once,
        # and so the next stage cannot be coalesced into a single end-of-run dump.
        self.stream.flush()

    def _persist(self, name: str, block: str) -> None:
        """Append a block to the durable ``debate.md`` sink, flushed, FAIL-CLOSED.

        Mirrors ``albert/deliberation.py``: a write failure raises
        ``VisibilityContractError`` — for an audit-driven cockpit, losing the
        auditable record must stop the run, not degrade silently. No-op when no
        ``run_dir`` was provided (back-compat)."""
        if self._debate_path is None:
            return
        try:
            with open(self._debate_path, "a", encoding="utf-8") as f:
                f.write(block)
                f.flush()
        except OSError as exc:
            raise VisibilityContractError(
                f"Failed to append debate block to {self._debate_path}: {exc}",
                phase=name, sink=str(self._debate_path),
            ) from exc

    def line(self, text: str) -> None:
        """Emit a single flushed line (used by harnesses / the red-team script for
        start/end markers outside a stage block)."""
        self.stream.write(text + "\n")
        self.stream.flush()


# --------------------------------------------------------------------------- #
# Per-stage render helpers (pure, deterministic — no LLM, no wall-clock).
#
# Each returns a REASONABLE-LENGTH block of KEY fields (~3-8 lines), NOT a raw
# state dump and NOT a single line. ``render_albert`` is the exception: it shows
# Albert's FULL output (every challenge, no slicing/truncation) because that is
# the debate core the colleague most needs to watch.
# --------------------------------------------------------------------------- #
def _first_line(text: str, limit: int = 120) -> str:
    """The first non-empty line of a (possibly multi-line) text, length-clamped —
    used ONLY for the scope/brief one-liners, never for Albert's challenges."""
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if ln:
            return ln if len(ln) <= limit else ln[: limit - 1] + "…"
    return ""


def render_scope(state: "ResearchState") -> str:
    """scope — the objective + north-star (1-2 lines)."""
    lines = [f"objective: {state.original_question}"]
    if state.research_brief:
        lines.append(f"north-star: {_first_line(state.research_brief)}")
    return "\n".join(lines)


def render_expand(state: "ResearchState") -> str:
    """expand — N issues + the top issue titles (by impact)."""
    issues = sorted(state.issue_map.values(), key=lambda n: n.impact, reverse=True)
    lines = [f"{len(issues)} issues"]
    for n in issues[:6]:
        lines.append(f"  • [{n.issue_type.value} impact={n.impact}] {n.title}")
    if len(issues) > 6:
        lines.append(f"  … +{len(issues) - 6} more")
    return "\n".join(lines)


def render_research(state: "ResearchState") -> str:
    """research — per researched issue: a 1-line finding + its top source. Shows the
    most recent few bundles (KEY info, not the whole evidence history)."""
    if not state.evidence:
        return "(no evidence yet)"
    lines = []
    for b in state.evidence[-3:]:
        top_claim = b.claims[0].claim if b.claims else "(no claim)"
        top_src = b.sources[0].title if b.sources else "(no source)"
        lines.append(f"  • {b.query}: {top_claim}  [src: {top_src}]")
    return "\n".join(lines)


def render_critique(state: "ResearchState") -> str:
    """critique / skeptic — the counterarguments raised this round (deduped)."""
    seen: list[str] = []
    for n in state.issue_map.values():
        for c in n.counterarguments:
            if c not in seen:
                seen.append(c)
    if not seen:
        return "(no counterarguments)"
    lines = [f"{len(seen)} counterargument(s):"]
    for c in seen[:6]:
        lines.append(f"  • {c}")
    if len(seen) > 6:
        lines.append(f"  … +{len(seen) - 6} more")
    return "\n".join(lines)


def render_albert(audit: "AuditResult") -> str:
    """albert_audit — Albert's FULL output (the debate core, NOT truncated).

    Shows EVERY ``AlbertChallenge`` (challenge text + why_albert_would_ask +
    status + current_answer if any), then verdict + premature_end_risk +
    research_drift_risk + recommended_next_action. No slicing, no [:N], no
    ellipsis on the challenge bodies — the colleague must see the whole debate.
    """
    lines = [f"verdict: {audit.verdict.value}"]
    rec = audit.recommended_next_action.value if audit.recommended_next_action else "-"
    lines.append(
        f"premature_end_risk: {audit.premature_end_risk.value}   "
        f"research_drift_risk: {audit.research_drift_risk.value}   "
        f"recommended_next_action: {rec}"
    )
    if audit.rationale:
        lines.append(f"rationale: {audit.rationale}")
    n = len(audit.challenges)
    lines.append(f"challenges ({n}):" if n else "challenges (0): (none)")
    # FULL loop — every challenge, in full, no truncation.
    for ch in audit.challenges:
        lines.append(f"  [{ch.id}] ({ch.status.value}, conf={ch.confidence}) {ch.challenge}")
        if ch.why_albert_would_ask:
            lines.append(f"      why: {ch.why_albert_would_ask}")
        if ch.current_answer:
            lines.append(f"      current answer: {ch.current_answer}")
        if ch.next_action:
            lines.append(f"      next: {ch.next_action}")
    return "\n".join(lines)


def render_convergence(state: "ResearchState") -> str:
    """convergence — resolved N / open M this round + which challenge ids resolved
    (the debate progressing toward 0 open)."""
    from ..decision import convergence

    resolved = convergence.resolved_count(state)
    open_n = convergence.open_count(state)
    escalated = convergence.escalated_count(state)
    resolved_ids = [
        c.id for c in state.albert_challenge_map.values()
        if c.status.value == "resolved"
    ]
    open_ids = [c.id for c in convergence.unresolved_challenges(state)]
    lines = [f"resolved {resolved} / open {open_n} / escalated-to-human {escalated}"]
    if resolved_ids:
        lines.append(f"  resolved: {', '.join(resolved_ids)}")
    if open_ids:
        lines.append(f"  still open: {', '.join(open_ids)}")
    return "\n".join(lines)


def render_readiness(score: "ReadinessScore") -> str:
    """readiness — the 4 scores + should_continue + the one-line reason."""
    lines = [
        f"albert_challenge={score.albert_challenge_readiness}/5  "
        f"decision={score.decision_readiness}/5  "
        f"research_exhaustion={score.research_exhaustion_readiness}/5  "
        f"human_bottleneck={score.human_bottleneck_clarity}/5",
        f"should_continue: {score.should_continue}",
    ]
    if score.reason:
        lines.append(f"reason: {score.reason}")
    return "\n".join(lines)


def render_decision(decision: "Decision", rationale: str = "") -> str:
    """decision — the COS next action + its rationale."""
    lines = [f"next action: {decision.value}"]
    if rationale:
        lines.append(f"rationale: {rationale}")
    return "\n".join(lines)
