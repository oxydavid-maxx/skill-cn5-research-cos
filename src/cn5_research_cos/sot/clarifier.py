"""The glue: configure the reusable `cn5_ask` engine for SOT clarification.

P2a does NOT build a loop or a convergence rule of its own. It CONFIGURES the
already-built deterministic engine (`cn5_ask`) by supplying three narrow pieces:

    * `sot_step_fn`     - one narrow LLM turn (ask 1-2 questions + assess C1-C4).
                          The ONLY place the LLM lives.
    * `sot_compile_fn`  - one narrow LLM call: converged dialogue -> SOTBrief dict.
    * `convergence_rule`- ConvergenceRule(["C1","C2","C3","C4"], k=3, window=2).

`ClarifySession` drives the engine TURN-BASED (one engine step per CLI
invocation) over a SqliteSaver at `runs/<id>/clarify_checkpoint.db`. Between
invocations the human supplies an answer; the next call resumes the same thread
with the new dialogue. On convergence (or the hard turn cap) it compiles the
dialogue into a SOTBrief, persists `brief.v1`, and returns it so the caller can
mirror it into `ResearchState.research_brief`.

ALL loop / convergence / stop / routing control is deterministic and lives in
`cn5_ask`; no `datetime.now()` here (the caller supplies `now`).
"""
from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Optional

from cn5_ask import (
    ConvergeConfig,
    ConvergenceRule,
    StepFn,
    StepResult,
    build_graph,
    make_saver,
    resume,
    run,
)

from ..llm import sdk_client
from .brief import SOTBrief, save as save_brief

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
SIGNALS = ["C1", "C2", "C3", "C4"]
THRESHOLD_K = 3
STABILITY_WINDOW = 2
DEFAULT_MAX_TURNS = 12


def convergence_rule() -> ConvergenceRule:
    """The C1-C4 convergence rule: >=3 of 4 active, stable for 2 rounds."""
    return ConvergenceRule(
        signals=list(SIGNALS), threshold_k=THRESHOLD_K, stability_window=STABILITY_WINDOW
    )


# --------------------------------------------------------------------------- #
# Prompt loading
# --------------------------------------------------------------------------- #
def _load_prompt(name: str) -> str:
    return resources.files("cn5_research_cos.sot.prompts").joinpath(name).read_text(
        encoding="utf-8"
    )


def _render_dialogue(dialogue: list[dict[str, str]]) -> str:
    lines = []
    for turn in dialogue:
        role = turn.get("role", "user")
        text = turn.get("text", "")
        lines.append(f"[{role}] {text}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Narrow LLM step + compile (the ONLY places the LLM lives)
# --------------------------------------------------------------------------- #
_ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
        "signals": {
            "type": "object",
            "properties": {s: {"type": "boolean"} for s in SIGNALS},
            "required": list(SIGNALS),
            "additionalProperties": False,
        },
        "signal_rationale": {
            "type": "object",
            "properties": {s: {"type": "string"} for s in SIGNALS},
            "additionalProperties": True,
        },
    },
    "required": ["questions", "signals"],
    "additionalProperties": False,
}


def _brief_schema() -> dict:
    """A JSON schema for the SOTBrief compile output (subset the LLM should fill)."""
    return {
        "type": "object",
        "properties": {
            "objective": {"type": "string"},
            "background": {"type": "string"},
            "in_scope": {"type": "array", "items": {"type": "string"}},
            "out_of_scope": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "forbidden_directions": {"type": "array", "items": {"type": "string"}},
            "available_sources": {"type": "array", "items": {"type": "string"}},
            "deliverable": {"type": "string"},
            "success_criteria": {"type": "array", "items": {"type": "string"}},
            "decision_served": {"type": ["string", "null"]},
            "decision_criterion": {"type": ["string", "null"]},
            "open_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["objective", "deliverable"],
        "additionalProperties": False,
    }


def sot_step_fn(state: dict[str, Any], context: dict[str, Any]) -> StepResult:
    """Narrow LLM step: (dialogue) -> {questions, signals C1-C4}.

    The dialogue-so-far is supplied via ``context["dialogue"]`` (the engine
    passes the build-time context to every step; each CLI invocation rebuilds
    the graph with the latest dialogue).
    """
    dialogue = context.get("dialogue", [])
    system = _load_prompt("ask_turn.md")
    user = (
        "以下是目前為止的釐清對話。請依指示提出 1–2 個釐清問題並評估 C1–C4 訊號。\n\n"
        f"{_render_dialogue(dialogue)}"
    )
    out = sdk_client.call_structured(system, user, _ASK_SCHEMA)
    signals = {s: bool(out.get("signals", {}).get(s, False)) for s in SIGNALS}
    return StepResult(
        output={
            "questions": out.get("questions", []),
            "signal_rationale": out.get("signal_rationale", {}),
        },
        signals=signals,
    )


def sot_compile_fn(state: dict[str, Any]) -> dict[str, Any]:
    """Narrow LLM compile: converged dialogue -> SOTBrief dict.

    The full dialogue is reconstructed from the engine's recorded turns plus the
    context-carried dialogue (made available on the state under ``dialogue``).
    """
    dialogue = state.get("dialogue", [])
    system = _load_prompt("brief_writer.md")
    user = (
        "以下是已收斂的釐清對話。請依指示編譯成 SOTBrief JSON。\n\n"
        f"{_render_dialogue(dialogue)}"
    )
    return sdk_client.call_structured(system, user, _brief_schema())


# --------------------------------------------------------------------------- #
# Turn-based driver over cn5_ask
# --------------------------------------------------------------------------- #
class ClarifySession:
    """Drives the cn5_ask engine one turn per call over a SqliteSaver thread.

    Each ``step()`` advances EXACTLY one engine turn (it clamps the engine's
    per-call ``max_turns`` to ``persisted_turn_count + 1``), persists the
    checkpoint, and:
      * if not yet converged / capped -> returns the LLM's questions for the
        human to answer; the next ``step()`` resumes the same thread.
      * if converged (>=3 of C1-C4, stable 2 rounds) OR the hard cap is reached
        -> runs ``compile_fn``, persists ``brief.v1``, returns the SOTBrief dict.
    """

    def __init__(
        self,
        *,
        run_id: str,
        db_path: str,
        step_fn: StepFn = sot_step_fn,
        compile_fn: Callable[[dict[str, Any]], dict[str, Any]] = sot_compile_fn,
        base_dir: str = "runs",
        max_turns: int = DEFAULT_MAX_TURNS,
    ):
        self.run_id = run_id
        self.db_path = db_path
        self.step_fn = step_fn
        self.compile_fn = compile_fn
        self.base_dir = base_dir
        self.hard_cap = max_turns
        self.thread_id = run_id

    # -- internal helpers -------------------------------------------------- #
    def _saver(self):
        return make_saver(self.db_path)

    def _persisted_turn_count(self, saver) -> int:
        """How many engine turns are already recorded on this thread (0 if new)."""
        # Build a throwaway graph bound to the same saver to read the snapshot.
        cfg = ConvergeConfig(max_turns=self.hard_cap, rule=convergence_rule(),
                             thread_id=self.thread_id)
        g = build_graph(self.step_fn, self._compile_wrapper(None), cfg,
                        context={"dialogue": []}, saver=saver)
        snap = g.get_state({"configurable": {"thread_id": self.thread_id}})
        if snap and snap.values:
            return int(snap.values.get("turn_count", 0))
        return 0

    def _compile_wrapper(self, dialogue: Optional[list[dict[str, str]]]):
        """Wrap compile_fn so the dialogue is available on the state it receives."""
        def _wrapped(state: dict[str, Any]) -> dict[str, Any]:
            merged = dict(state)
            if dialogue is not None:
                merged["dialogue"] = dialogue
            return self.compile_fn(merged)
        return _wrapped

    # -- the one public driver -------------------------------------------- #
    def step(self, *, dialogue: list[dict[str, str]], now: str) -> dict[str, Any]:
        """Advance exactly one engine turn with the supplied dialogue-so-far."""
        saver = self._saver()
        prior = self._persisted_turn_count(saver)
        is_first = prior == 0

        # Clamp per-call turns to advance exactly one step, but never exceed the
        # hard cap. The engine's stop precedence (converged > max_turns) means
        # this either converges or forced-stops after one more step.
        per_call_cap = min(self.hard_cap, prior + 1)
        cfg = ConvergeConfig(max_turns=per_call_cap, rule=convergence_rule(),
                             thread_id=self.thread_id)

        graph = build_graph(
            self.step_fn,
            self._compile_wrapper(dialogue),
            cfg,
            context={"dialogue": dialogue},
            saver=saver,
        )

        if is_first:
            result = run(graph, {"dialogue": dialogue}, cfg)
        else:
            result = resume(graph, {"dialogue": dialogue}, cfg)

        turn_count = result.get("turn_count", 0)
        status = result.get("status")
        assessment = result.get("last_assessment", {})
        latest = result.get("latest_step_output", {})

        converged = status == "converged"
        # A genuine forced-stop only happens at the HARD cap, not at the
        # per-call clamp (which is just our one-step-per-invocation mechanism).
        forced_stop = (status == "forced_stop") and (turn_count >= self.hard_cap)

        finished = converged or forced_stop
        brief_dict: Optional[dict[str, Any]] = None

        if finished:
            # The engine ran compile (status converged/forced_stop routes to
            # compile); use its artifact, fill in lifecycle fields, persist v1.
            artifact = result.get("artifact") or {}
            brief = self._finalize_brief(artifact, now=now)
            save_brief(brief, self.run_id, self.base_dir)
            brief_dict = brief.model_dump(mode="json")

        return {
            "run_id": self.run_id,
            "turn_count": turn_count,
            "converged": converged,
            "forced_stop": forced_stop,
            "finished": finished,
            "questions": list(latest.get("questions", [])) if not finished else [],
            "signal_rationale": latest.get("signal_rationale", {}),
            "active_signals": assessment.get("active_signals", []),
            "stop_reason": assessment.get("stop_reason", assessment.get("reason", "")),
            "brief": brief_dict,
        }

    def _finalize_brief(self, artifact: dict[str, Any], *, now: str) -> SOTBrief:
        """Turn the compile artifact dict into a versioned draft SOTBrief."""
        data = dict(artifact)
        data.setdefault("objective", "(objective not produced)")
        data.setdefault("deliverable", "(deliverable not produced)")
        data["version"] = 1
        data["created_at"] = now
        # status stays draft until a human confirms via the CLI.
        return SOTBrief(**{k: v for k, v in data.items()
                           if k in SOTBrief.model_fields})


# --------------------------------------------------------------------------- #
# Dialogue persistence (turn-based CLI carries the dialogue across processes)
# --------------------------------------------------------------------------- #
def _dialogue_path(run_id: str, base_dir: str) -> Path:
    return Path(base_dir) / run_id / "clarify_dialogue.json"


def load_dialogue(run_id: str, base_dir: str = "runs") -> list[dict[str, str]]:
    p = _dialogue_path(run_id, base_dir)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def save_dialogue(run_id: str, dialogue: list[dict[str, str]], base_dir: str = "runs") -> None:
    p = _dialogue_path(run_id, base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dialogue, ensure_ascii=False, indent=2), encoding="utf-8")


def checkpoint_db_path(run_id: str, base_dir: str = "runs") -> str:
    return str(Path(base_dir) / run_id / "clarify_checkpoint.db")


# --------------------------------------------------------------------------- #
# Deterministic scripted step/compile (test affordance — NO LLM)
# --------------------------------------------------------------------------- #
_SCRIPTED_PROGRAM = [
    {"C1": True, "C2": False, "C3": False, "C4": False},  # turn 1: 1/4
    {"C1": True, "C2": True, "C3": True, "C4": False},     # turn 2: 3/4
    {"C1": True, "C2": True, "C3": True, "C4": True},      # turn 3: 4/4 -> converge
    {"C1": True, "C2": True, "C3": True, "C4": True},
]


def scripted_step_fn(state: dict[str, Any], context: dict[str, Any]) -> StepResult:
    """A deterministic StepFn (no LLM) replaying _SCRIPTED_PROGRAM by turn index.

    Used by the CLI under CN5_COS_CLARIFY_STEP=scripted so the turn-based session
    state can be exercised end-to-end without a key.
    """
    idx = state.get("turn_count", 0)
    prog = _SCRIPTED_PROGRAM[min(idx, len(_SCRIPTED_PROGRAM) - 1)]
    return StepResult(
        output={"questions": [f"[Q:CLARIFY] scripted question (turn {idx + 1})"],
                "signal_rationale": {k: "scripted" for k in SIGNALS}},
        signals=dict(prog),
    )


def scripted_compile_fn(state: dict[str, Any]) -> dict[str, Any]:
    """Deterministic compile (no LLM): a fixed schema-valid SOTBrief dict."""
    return SOTBrief(
        objective="scripted converged objective",
        deliverable="scripted deliverable",
        in_scope=["scripted in-scope"],
        decision_served="scripted decision",
        created_at="0000",
    ).model_dump(mode="json")
