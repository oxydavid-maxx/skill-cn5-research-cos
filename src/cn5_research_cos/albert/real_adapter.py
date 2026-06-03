"""Real Albert adapter (P6) — subprocess + JSON contract -> cockpit AuditResult.

scripts-as-toolbox / contract pattern (same family as paperwork + the P2b
simulator seam). This adapter NEVER imports Albert's python package and NEVER
vendors it: it resolves ``ALBERT_HOME`` (``albert/locate.py``), writes an
``albert_input.json`` from the cockpit ``ResearchState``, invokes::

    py -3 <ALBERT_HOME>/run_albert.py --input <input.json> --json-out [<speed flag>]

and parses the JSON-out. ``run_albert.py --json-out`` prints the *path* to its
``albert_challenge.json`` on stdout (the last stdout line that resolves to an
existing file); we read that file and map it via the cockpit's existing
``contract.to_audit_result`` -> our :class:`AuditResult`.

Degrade guard (spec decision #8, already enforced for the simulator): if the home
is absent, the subprocess exits non-zero / times out, or the JSON is unparseable,
``audit`` returns a DEGRADED ``AuditResult`` that is VISIBLY warned (stderr) and
CANNOT drive ``terminal_stop`` (verdict=rework, no terminal/exhausted, degraded
flag set). The loop continues; it just does not count this as a passed audit.

Determinism: input assembly, speed selection (``audit_tier_for``), contract parse,
and the degrade guard are pure Python. Only the subprocess (the real Albert FSM)
is non-deterministic, and control stays in our Python.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

from ..decision import convergence
from ..decision.audit_tier import audit_tier_for, speed_to_cli_flag
from ..models import AuditResult, AuditVerdict, Decision, ResearchState, Risk
from . import locate
from .contract import to_audit_result

# Per-speed subprocess timeouts (seconds). The real Albert FSM runs ~5/10/20min at
# quick/fast/normal; flash is a single Opus call (~secs) but allow slack for SDK
# startup. Generous so a slow-but-progressing run is not falsely degraded.
_SPEED_TIMEOUT = {
    "flash": 180,     # 3 min — one Opus call + SDK startup
    "quick": 600,     # 10 min — ~5 min run + margin
    "fast": 1200,     # 20 min — ~10 min run + margin
    "normal": 1800,   # 30 min — ~20 min run + margin
}
_DEFAULT_TIMEOUT = 1800


def _open_challenges_payload(state: ResearchState) -> list[dict]:
    """The current UNRESOLVED challenges (id + text + current answer + evidence) so
    Albert tracks/resolves them instead of re-asking — feeds P4b convergence."""
    out: list[dict] = []
    for c in convergence.unresolved_challenges(state):
        out.append({
            "id": c.id,
            "challenge": c.challenge,
            "current_answer": c.current_answer,
            "status": c.status.value,
            "evidence_refs": list(c.evidence_refs),
        })
    return out


def build_albert_input(state: ResearchState) -> dict:
    """Assemble the ``albert_input.json`` dict from ``state`` (pure).

    Carries the current answer/proposal + the SOT brief + the prior OPEN
    challenges. ``mode="cockpit"`` so Albert's ``input_adapter.build_input`` takes
    the cockpit path. NO wall-clock, no I/O.
    """
    draft = state.final_memo or state.research_brief or ""
    issues = [
        {"title": n.title, "status": n.status.value, "impact": n.impact}
        for n in list(state.issue_map.values())[:20]
    ]
    return {
        "mode": "cockpit",
        "proposal_title": state.original_question,
        "proposal_summary": state.original_question,
        "current_answer": draft,
        "original_objective": state.original_question,
        "meeting_context": state.meeting_context or "",
        "research_brief": state.research_brief or "",
        "output_purpose": state.output_purpose or "decision_readiness",
        "issue_map": issues,
        # the prior OPEN challenges — the convergence dialogue Albert must carry
        # forward (resolve / escalate / reference-by-id, never re-raise verbatim).
        "challenge_map": _open_challenges_payload(state),
        "research_state": {
            "iteration_count": state.iteration_count,
            "open_challenge_count": convergence.open_count(state),
        },
    }


def _degraded_audit(reason: str) -> AuditResult:
    """A VISIBLY-warned degraded audit that can NOT drive terminal_stop.

    verdict=rework (never exhausted -> cannot count as a passed audit);
    recommended_next_action=continue_research (never terminal_stop/synthesize);
    degraded=True so the convergence/risk layers treat it as non-authoritative.
    """
    sys.stderr.write(f"[real_adapter] DEGRADED Albert audit: {reason}\n")
    sys.stderr.flush()
    return AuditResult(
        verdict=AuditVerdict.rework,
        premature_end_risk=Risk.low,
        research_drift_risk=Risk.low,
        recommended_next_action=Decision.continue_research,
        rationale=f"Albert audit degraded ({reason}); loop continues but this audit "
                  "is NOT authoritative and cannot drive a stop.",
        degraded=True,
    )


def _parse_json_out(stdout: str) -> dict:
    """Resolve the albert_challenge.json path printed by ``--json-out`` and load it.

    ``run_albert.py --json-out`` prints the *path* to its challenge JSON (plus
    trailing report-path lines). We take the LAST stdout line that resolves to an
    existing ``*.json`` file. Raises on no resolvable path / unparseable JSON
    (the caller turns the exception into a degraded audit).
    """
    candidates = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
    json_path: Path | None = None
    for line in reversed(candidates):
        p = Path(line)
        if p.suffix == ".json" and p.is_file():
            json_path = p
            break
    if json_path is None:
        raise ValueError("no albert_challenge.json path on --json-out stdout")
    return json.loads(json_path.read_text(encoding="utf-8"))


def _to_audit(raw: dict) -> AuditResult:
    """Map a raw albert_challenge dict -> AuditResult via the cockpit contract,
    stashing the gap-audit A2 enrichment (mirrors RealAlbertSimulator)."""
    mapped = to_audit_result(raw)
    audit = AuditResult.model_validate(mapped["audit_result"])
    enr = mapped.get("enrichment", {})
    if not audit.missing_business_context and enr.get("missing_business_context"):
        audit.missing_business_context = list(enr["missing_business_context"])
    if not audit.questions_albert_would_ask_next and enr.get("questions_albert_would_ask"):
        audit.questions_albert_would_ask_next = list(enr["questions_albert_would_ask"])
    if not audit.readiness_score_delta and enr.get("readiness_score_delta"):
        audit.readiness_score_delta = int(enr["readiness_score_delta"])
    probes = enr.get("recommended_next_probe") or []
    if probes and audit.recommended_next_probe is None:
        first = probes[0]
        audit.recommended_next_probe = (
            first.get("probe") if isinstance(first, dict) else str(first)
        )
    return audit


class RealAlbert:
    """Real-Albert :class:`Auditor` — subprocess ``run_albert.py`` + contract parse.

    ``work_dir`` is where the per-call ``albert_input.json`` is written (a tmp file
    under it). ``stage`` selects the speed via :func:`audit_tier_for` (defaults to
    the per-iteration ``sentinel`` tier; the deep-audit node passes a gate stage).
    ``python`` overrides the interpreter (default ``py -3`` on Windows, else the
    current ``sys.executable``).
    """

    def __init__(self, *, work_dir: str | Path = ".", stage: str = "sentinel",
                 python: list[str] | None = None) -> None:
        self._work_dir = Path(work_dir)
        self._stage = stage
        self._python = python or (["py", "-3"] if sys.platform.startswith("win")
                                  else [sys.executable])

    def audit(self, state: ResearchState) -> AuditResult:
        home = locate.find_albert_home()
        if home is None:
            return _degraded_audit("ALBERT_HOME not resolvable (absent / no checkout)")

        speed = audit_tier_for(self._stage, state)
        flag = speed_to_cli_flag(speed)
        timeout = _SPEED_TIMEOUT.get(speed, _DEFAULT_TIMEOUT)

        self._work_dir.mkdir(parents=True, exist_ok=True)
        input_path = self._work_dir / f"albert_input_{uuid.uuid4().hex[:8]}.json"
        try:
            input_path.write_text(
                json.dumps(build_albert_input(state), ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            return _degraded_audit(f"could not write albert_input.json: {e}")

        argv = [*self._python, str(Path(home) / "run_albert.py"),
                "--input", str(input_path), "--json-out", "--allow-redirect"]
        if flag:
            argv.append(flag)

        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _degraded_audit(f"run_albert.py timed out after {timeout}s ({speed})")
        except OSError as e:
            return _degraded_audit(f"could not launch run_albert.py: {e}")

        if proc.returncode != 0:
            tail = (proc.stderr or "")[-300:]
            return _degraded_audit(f"run_albert.py exit={proc.returncode}: {tail}")

        try:
            raw = _parse_json_out(proc.stdout)
        except (ValueError, OSError) as e:
            return _degraded_audit(f"unparseable --json-out: {e}")

        try:
            return _to_audit(raw)
        except Exception as e:  # contract-shape surprise -> degrade, never crash the loop
            return _degraded_audit(f"contract mapping failed: {type(e).__name__}: {e}")
