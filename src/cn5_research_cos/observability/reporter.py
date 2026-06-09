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


def _force_utf8(stream) -> None:
    """Best-effort force UTF-8 on a text stream so CJK renders with no mojibake.

    ``errors='replace'`` so a console that cannot encode a glyph degrades it to
    '?' instead of raising ``UnicodeEncodeError`` (which would break the live
    sink). Fail-SILENT: any stream that cannot reconfigure (StringIO, an exotic
    wrapper) is left as-is. Mirrors ``run_albert.py::_force_utf8_console``."""
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - best-effort; never break the run
        pass


def _open_tty():
    """Open the real terminal device for an OPTIONAL bonus live write, or return
    None. ``CONOUT$`` on Windows / ``/dev/tty`` on POSIX. Best-effort: returns
    None on any failure (no terminal exists, headless, no permission). NEVER
    raises — the caller treats a missing tty as "no bonus", not an error."""
    path = "CONOUT$" if sys.platform.startswith("win") else "/dev/tty"
    try:
        return open(path, "w", encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - no real terminal here; that's fine
        return None


def _tty_bonus(block: str) -> None:
    """Write ``block`` to the real terminal device IF one opens. FAIL-SILENT in
    EVERY way: opening, writing, flushing, and closing errors are all swallowed.
    This is the OPTIONAL bonus from the spec — never the guarantee, never raises,
    and must never break the user's chosen ``> log`` / pipe."""
    handle = None
    try:
        handle = _open_tty()
        if handle is None:
            return
        handle.write(block)
        handle.flush()
    except Exception:  # noqa: BLE001 - bonus is fail-silent in EVERY way (open/write/flush)
        pass
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass


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
        # P5d guarantee #2: force UTF-8 on the live stream best-effort so CJK debate
        # cards render with no mojibake on any console. Fail-silent — a stream that
        # cannot reconfigure (StringIO, an exotic wrapper) must not break the run.
        _force_utf8(self.stream)
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
        # P5d optional bonus (fail-SILENT, never a guarantee): also write to the
        # real terminal device (CONOUT$ / /dev/tty) IF it opens — helps the
        # "piped-but-also-watching in a real terminal" case (e.g. `cos run | tee`).
        # ANY error here is swallowed: it must never break the user's `> log`.
        _tty_bonus(block)

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
def _delta_count(state, key: str, current: int) -> int:
    """current minus the value stored under obs_prev[key]; updates the store.
    Used by per-stage cards to show 'what changed since I last rendered'."""
    prev = (state.obs_prev or {}).get(key, 0)
    state.obs_prev[key] = current
    return current - prev


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
    """expand — DELTA: +N new issues since last render (lead) + the top issue titles
    (by impact). '本站無動作' when no new issues were added this cycle."""
    d = _delta_count(state, "expand_n", len(state.issue_map))
    if d <= 0:
        return "本站無動作"
    issues = sorted(state.issue_map.values(), key=lambda n: n.impact, reverse=True)
    lines = [f"+{d} issues"]
    for n in issues[:6]:
        lines.append(f"  • [{n.issue_type.value} impact={n.impact}] {n.title}")
    return "\n".join(lines)


def render_research(state: "ResearchState") -> str:
    """research — DELTA: +N new evidence bundles since last render (lead) + a 1-line
    finding per NEW bundle. '本站無動作' when no new evidence arrived this cycle."""
    d = _delta_count(state, "research_n", len(state.evidence))
    if d <= 0:
        return "本站無動作"
    lines = [f"+{d} evidence"]
    for b in state.evidence[-d:]:
        top = b.claims[0].claim if b.claims else "(no claim)"
        lines.append(f"  • {b.query}: {top}")
    return "\n".join(lines)


def render_critique(state: "ResearchState") -> str:
    """critique / skeptic — DELTA: +N new counterarguments since last render (lead),
    deduped. '本站無動作' when no new counterargument was raised this cycle."""
    seen: list[str] = []
    for n in state.issue_map.values():
        for c in n.counterarguments:
            if c not in seen:
                seen.append(c)
    d = _delta_count(state, "critique_n", len(seen))
    if d <= 0:
        return "本站無動作"
    lines = [f"+{d} 反論"]
    for c in seen[-d:]:
        lines.append(f"  • {c}")
    return "\n".join(lines)


def render_albert(audit: "AuditResult") -> str:
    """albert_audit — a one-line DELTA summary PREFIX (verdict + challenge count)
    followed by Albert's FULL body. The prefix gives a colleague the headline at a
    glance; the body (``_render_albert_body``) is kept intact (NOT truncated)."""
    body = _render_albert_body(audit)
    n = len(audit.challenges)
    return f"verdict {audit.verdict.value} · {n} challenge(s)\n{body}"


def _render_albert_body(audit: "AuditResult") -> str:
    """Albert's FULL output (the debate core, NOT truncated).

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
    """convergence — DELTA: the open-challenge count MOVE since last render. Shows the
    current open count + the signed change (↓ fewer open = progress, ↑ more open,
    → no change). Reads the real ``convergence.unresolved_challenges`` API."""
    from ..decision import convergence as _c

    open_n = len(_c.unresolved_challenges(state))
    d = _delta_count(state, "convergence_open", open_n)
    arrow = "→" if d == 0 else ("↓" if d < 0 else "↑")
    return f"open challenges {arrow} {open_n}" + (f" ({d:+d})" if d else " (no change)")


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


# --------------------------------------------------------------------------- #
# P8 orchestration-stage render helpers (clarify / orchestrator / plan_audit /
# plan_approval). Same pure/deterministic contract: take the ResearchState (rs),
# return a SHORT human-readable block. Guard against None (no grid / no audit /
# empty state) — return a clear "(…)" placeholder, NEVER crash.
# --------------------------------------------------------------------------- #
def render_clarify(state: "ResearchState") -> str:
    """clarify (H0) — converged? + which of the 4 criteria are still missing + the
    questions asked this round (read from the last ``clarify-*`` steering event)."""
    from ..decision import clarify as _clarify

    converged = bool(getattr(state, "clarify_converged", False))
    ok, missing = _clarify.clarify_converged(state)
    converged = converged or ok
    lines = [f"converged: {converged}"]
    if missing:
        lines.append(f"missing: {', '.join(missing)}")
    else:
        lines.append("missing: (none — all 4 criteria pinned)")
    # Surface the most recent clarify steering event (questions asked / assumed).
    last_clarify = None
    for e in getattr(state, "steering_events", []) or []:
        if isinstance(e, dict) and str(e.get("kind", "")).startswith("clarify"):
            last_clarify = e
    if last_clarify is not None:
        kind = last_clarify.get("kind", "clarify")
        questions = last_clarify.get("questions")
        if questions:
            lines.append(f"questions ({kind}):")
            for q in questions[:6]:
                lines.append(f"  • {q}")
        else:
            lines.append(f"event: {kind}")
    return "\n".join(lines)


def render_orchestrator(state: "ResearchState") -> str:
    """orchestrator (P8 ①) — the section-aware task grid: one line per cell
    ``[status] vendor / spec_group (impact=N): objective`` (capped at ~20)."""
    grid = getattr(state, "task_grid", None)
    if grid is None or not getattr(grid, "cells", None):
        return "(no task grid yet)"
    cells = list(grid.cells.values())
    lines = [f"任務格：{len(cells)} cells"]
    for c in cells[:20]:
        status = c.status.value if hasattr(c.status, "value") else str(c.status)
        lines.append(
            f"  [{status}] {c.vendor} / {c.spec_group} (impact={c.impact}): {c.objective}"
        )
    if len(cells) > 20:
        lines.append(f"  … +{len(cells) - 20} more")
    return "\n".join(lines)


def render_plan_audit(state: "ResearchState") -> str:
    """plan_audit (P8 ②b) — the plan-audit verdict from ``rs.last_audit``: verdict
    + both risks + a couple of weak_points / challenges (if present). Short."""
    audit = getattr(state, "last_audit", None)
    if audit is None:
        return "(no plan audit yet)"
    verdict = audit.verdict.value if hasattr(audit.verdict, "value") else str(audit.verdict)
    pre = audit.premature_end_risk.value if hasattr(audit.premature_end_risk, "value") \
        else str(audit.premature_end_risk)
    drift = audit.research_drift_risk.value if hasattr(audit.research_drift_risk, "value") \
        else str(audit.research_drift_risk)
    lines = [
        f"verdict: {verdict}",
        f"premature_end_risk: {pre}   research_drift_risk: {drift}",
    ]
    weak = list(getattr(audit, "weak_points", []) or [])
    if weak:
        lines.append("weak points:")
        for w in weak[:3]:
            lines.append(f"  • {w}")
    challenges = list(getattr(audit, "challenges", []) or [])
    if challenges:
        lines.append(f"challenges ({len(challenges)}):")
        for ch in challenges[:3]:
            lines.append(f"  • {ch.challenge}")
    return "\n".join(lines)


def render_plan_approval(state: "ResearchState") -> str:
    """plan_approval (P8 §5 H7) — the cells presented for human approval +
    whether this is the first cycle (read the last ``plan-approval`` /
    ``plan-assumed`` steering event), else just list the grid cell ids. Short."""
    grid = getattr(state, "task_grid", None)
    cell_ids = list(grid.cells.keys()) if grid and getattr(grid, "cells", None) else []
    last_evt = None
    for e in getattr(state, "steering_events", []) or []:
        if isinstance(e, dict) and str(e.get("kind", "")) in (
            "plan-approval", "plan-assumed", "plan_approval", "plan_assumed",
        ):
            last_evt = e
    lines = [f"cells presented: {len(cell_ids)}"]
    if cell_ids:
        lines.append(f"  {', '.join(cell_ids[:20])}" + (" …" if len(cell_ids) > 20 else ""))
    if last_evt is not None:
        first = last_evt.get("first_cycle")
        if first is not None:
            lines.append(f"first_cycle: {first}")
        lines.append(f"event: {last_evt.get('kind')}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# P10b — per-round research-status dashboard (pure/deterministic, no LLM).
# Coverage bars + round delta (left) and an action panel (right), as two
# side-by-side columns via rich.Columns rendered to a string (so it still
# appends to debate.md as text). One line when nothing moved this cycle.
# --------------------------------------------------------------------------- #
_STALL_THRESHOLD = 2
_BAR_WIDTH = 10


def _bar(filled: int, total: int) -> str:
    total = max(1, total)
    n = round(_BAR_WIDTH * filled / total)
    return "█" * n + "░" * (_BAR_WIDTH - n)


def _coverage(grid) -> tuple[int, int]:
    """(filled fields, total criteria) across all cells with criteria."""
    f = sum(c.last_filled for c in grid.cells.values())
    t = sum(len(c.success_criteria) for c in grid.cells.values())
    return f, t


def render_research_status(state: "ResearchState") -> str:
    """P10b — per-round research-status dashboard: coverage + round delta (left) and
    the action panel (right), as two columns. One line when nothing moved this cycle.
    Pure/deterministic: reads TaskGrid cell statuses + the delta bookkeeping."""
    grid = getattr(state, "task_grid", None)
    if grid is None or not grid.cells:
        return ""
    filled, total = _coverage(grid)
    prev = getattr(state, "prev_coverage", 0)
    moved = list((state.obs_prev or {}).get("grid_moved", []))
    state.prev_coverage = filled

    pct = round(100 * filled / max(1, total))
    prev_pct = round(100 * prev / max(1, total))
    if not moved and filled == prev:
        blocked = [c for c in grid.cells.values() if c.status.value == "blocked"]
        stalled = [c for c in grid.cells.values() if c.stalled_cycles >= _STALL_THRESHOLD]
        flags = []
        if blocked:
            flags.append("/".join(sorted({c.vendor for c in blocked})) + " 卡住")
        if stalled:
            flags.append("/".join(sorted({c.vendor for c in stalled})) + " 停滯")
        tail = ("（" + " · ".join(flags) + "）") if flags else ""
        return f"研究現況：無新進展{tail}"

    from collections import defaultdict
    by_vendor: dict = defaultdict(lambda: [0, 0, [], 0])
    for c in grid.cells.values():
        agg = by_vendor[c.vendor]
        agg[0] += c.last_filled
        agg[1] += len(c.success_criteria)
        agg[2].append(c.status.value)
        agg[3] = max(agg[3], c.stalled_cycles)
    moved_vendors = {grid.cells[cid].vendor for cid in moved if cid in grid.cells}
    head = f"研究現況  {prev_pct}%→{pct}%  ▲+{pct - prev_pct}%"
    left = [head]
    for vendor in sorted(by_vendor):
        f, t, statuses, st = by_vendor[vendor]
        mark = "▲" if vendor in moved_vendors else ("—停滯" if st >= _STALL_THRESHOLD else "")
        blk = sum(1 for s in statuses if s == "blocked")
        tag = f" ⛔{blk}" if blk else ""
        left.append(f"{vendor:<10} {_bar(f, t)} {f}/{t}{tag} {mark}")

    right = ["待處理:"]
    blocked_vendors = sorted({c.vendor for c in grid.cells.values() if c.status.value == "blocked"})
    if blocked_vendors:
        right.append("需要你出手: " + ", ".join(blocked_vendors) + " 需內部")
    empty = sorted({v for v, agg in by_vendor.items() if agg[0] == 0})
    if empty:
        right.append("最大缺口: " + ", ".join(empty) + " 全空白")
    stalled_v = sorted({c.vendor for c in grid.cells.values() if c.stalled_cycles >= _STALL_THRESHOLD})
    if stalled_v:
        right.append("停滯: " + ", ".join(stalled_v))

    try:
        from rich.columns import Columns
        from rich.panel import Panel
        from rich.console import Console
        import io
        console = Console(file=io.StringIO(), width=88)
        console.print(Columns([Panel("\n".join(left)), Panel("\n".join(right))]))
        return console.file.getvalue().rstrip("\n")
    except Exception:  # noqa: BLE001
        return "\n".join(left) + "\n--\n" + "\n".join(right)
