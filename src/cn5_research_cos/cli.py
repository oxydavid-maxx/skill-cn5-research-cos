"""Typer CLI: cos init / run / show / validate.

Supplies run_id + ISO timestamps into the deterministic core (no wall-clock in
nodes/models). Base dir overridable via CN5_COS_BASE_DIR (used by tests).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import typer
from rich.console import Console

from . import render
from .graph import compile_with_checkpoint
from .models import Decision, ResearchState
from .sot import brief as sot_brief
from .sot import clarifier as sot_clarifier
from .sot.conflict import detect as detect_conflict
from .state import GraphState
from .store import load_snapshot, new_run, save_snapshot

app = typer.Typer(add_completion=False, help="CN5 Research Chief-of-Staff (deterministic P1 spine)")
console = Console()


def _base_dir() -> str:
    return os.environ.get("CN5_COS_BASE_DIR", "runs")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


@app.command()
def init(
    question: str = typer.Option(..., "--question", "-q", help="原始問題"),
    run_id: str = typer.Option(None, "--run-id", help="自訂 run id"),
    mode: str = typer.Option("interactive", "--mode"),
):
    """初始化一個 run，寫出 runs/<id>/state.json。"""
    now = _now()
    rid = run_id or "run-" + now.replace(":", "").replace("-", "")
    state = new_run(question, run_id=rid, now=now, mode=mode)
    save_snapshot(state, base_dir=_base_dir())
    console.print(f"[green]initialized[/green] run_id=[bold]{rid}[/bold]")


@app.command()
def run(
    question: str = typer.Option(None, "--question", "-q"),
    run_id: str = typer.Option(None, "--run-id"),
    max_iterations: int = typer.Option(8, "--max-iterations"),
    llm: str = typer.Option("mock", "--llm"),
    resume: bool = typer.Option(False, "--resume",
                                help="從上次 checkpoint 續跑（需 --run-id），不重頭跑"),
):
    """跑完整研究收斂迴圈，逐輪印出中文 summary，最後印停止原因 + 四項 readiness 分數。"""
    if llm != "mock":
        console.print(f"[red]P1 僅支援 --llm mock（real brains 為 P2）；收到 {llm!r}[/red]")
        raise typer.Exit(code=2)

    now = _now()
    base_dir = _base_dir()

    final_state: ResearchState | None = None
    last_decision: Decision | None = None
    last_printed_iter = -1
    cfg_base = {"recursion_limit": 100}

    if resume:
        if not run_id:
            console.print("[red]--resume 需要 --run-id[/red]")
            raise typer.Exit(code=2)
        rid = run_id
        app_graph, _saver, conn = compile_with_checkpoint(os.path.join(base_dir, rid))
        cfg = {**cfg_base, "configurable": {"thread_id": rid}}
        stream_input = None  # replay from checkpoint, do not restart
    else:
        if not question:
            console.print("[red]--question 為必填（除非 --resume）[/red]")
            raise typer.Exit(code=2)
        rid = run_id or "run-" + now.replace(":", "").replace("-", "")
        initial = ResearchState(run_id=rid, original_question=question,
                                created_at=now, updated_at=now)
        app_graph, _saver, conn = compile_with_checkpoint(os.path.join(base_dir, rid))
        cfg = {**cfg_base, "configurable": {"thread_id": rid}}
        stream_input: GraphState | None = {
            "research_state": initial,
            "base_dir": base_dir,
            "now": now,
            "max_iterations": max_iterations,
        }

    try:
        for chunk in app_graph.stream(stream_input, config=cfg, stream_mode="values"):
            rs = chunk.get("research_state")
            if rs is None:
                continue
            final_state = rs
            dec = chunk.get("last_decision")
            if dec is not None:
                last_decision = dec
            if rs.readiness_score is not None and rs.iteration_count != last_printed_iter:
                console.print(render.iteration_summary(rs))
                console.print("")
                last_printed_iter = rs.iteration_count
    finally:
        conn.close()

    if final_state is None:
        console.print("[red]迴圈未產生任何狀態（resume 時可能已完成）[/red]")
        raise typer.Exit(code=1)

    save_snapshot(final_state, base_dir=base_dir)
    console.rule("[bold]研究迴圈結束[/bold]")
    console.print(f"run_id=[bold]{rid}[/bold] 共執行 [bold]{final_state.iteration_count}[/bold] 輪")
    console.print(render.stop_reason_line(last_decision))
    console.print("")
    console.print("最終 readiness 分數：")
    console.print(render.render_readiness(final_state))


@app.command()
def show(
    run_id: str = typer.Argument(...),
    artifact: str = typer.Option("all", "--artifact",
                                 help="issue|challenge|board|readiness|all"),
):
    """渲染某個 run 的三個 artifact + readiness。"""
    try:
        state = load_snapshot(run_id, base_dir=_base_dir())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    parts = []
    if artifact in ("issue", "all"):
        parts.append(render.render_issue_map(state))
    if artifact in ("challenge", "all"):
        parts.append(render.render_challenge_map(state))
    if artifact in ("board", "all"):
        parts.append(render.render_board(state))
    if artifact in ("readiness", "all"):
        parts.append(render.render_readiness(state))
    console.print("\n".join(parts))


@app.command()
def validate(run_id: str = typer.Argument(...)):
    """重新載入並驗證 state.json。"""
    try:
        state = load_snapshot(run_id, base_dir=_base_dir())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    # round-trip re-validate
    ResearchState.model_validate_json(state.model_dump_json())
    console.print(f"[green]OK[/green] run_id={run_id} valid; "
                  f"issues={len(state.issue_map)} challenges={len(state.albert_challenge_map)} "
                  f"iterations={state.iteration_count}")


def _make_clarify_session(rid: str, base_dir: str) -> sot_clarifier.ClarifySession:
    """Build a ClarifySession; use the deterministic scripted step when asked
    (CN5_COS_CLARIFY_STEP=scripted), otherwise the live LLM step."""
    if os.environ.get("CN5_COS_CLARIFY_STEP") == "scripted":
        step_fn = sot_clarifier.scripted_step_fn
        compile_fn = sot_clarifier.scripted_compile_fn
    else:
        step_fn = sot_clarifier.sot_step_fn
        compile_fn = sot_clarifier.sot_compile_fn
    return sot_clarifier.ClarifySession(
        run_id=rid,
        db_path=sot_clarifier.checkpoint_db_path(rid, base_dir),
        step_fn=step_fn,
        compile_fn=compile_fn,
        base_dir=base_dir,
    )


@app.command()
def clarify(
    question: str = typer.Option(None, "--question", "-q",
                                 help="第一回合：要釐清的（可能含糊的）研究主題"),
    answer: str = typer.Option(None, "--answer", "-a",
                               help="後續回合：回答上一輪的釐清問題"),
    run_id: str = typer.Option(None, "--run-id", help="clarify session 的 run id"),
):
    """多回合釐清研究主題，收斂後產出 SOTBrief（brief.v1）。

    第一回合用 --question 起頭；之後每回合用 --answer 回答上一輪問題並續跑同一
    session（turn-based，一次 CLI 呼叫推進一個 engine turn）。
    """
    base_dir = _base_dir()
    now = _now()
    rid = run_id or "run-" + now.replace(":", "").replace("-", "")

    dialogue = sot_clarifier.load_dialogue(rid, base_dir)
    if question:
        dialogue = [{"role": "user", "text": question}]
    elif answer:
        if not dialogue:
            console.print("[red]找不到既有 session；請先用 --question 起頭[/red]")
            raise typer.Exit(code=2)
        dialogue = dialogue + [{"role": "user", "text": answer}]
    else:
        console.print("[red]需要 --question（起頭）或 --answer（續答）[/red]")
        raise typer.Exit(code=2)

    sot_clarifier.save_dialogue(rid, dialogue, base_dir)

    sess = _make_clarify_session(rid, base_dir)
    result = sess.step(dialogue=dialogue, now=now)

    console.print(f"run_id=[bold]{rid}[/bold] turn=[bold]{result['turn_count']}[/bold] "
                  f"active={result['active_signals']}")

    if not result["finished"]:
        console.print("[yellow]未收斂[/yellow]，請回答以下釐清問題（用 "
                      f"`cos clarify --answer \"...\" --run-id {rid}`）：")
        for q in result["questions"]:
            console.print(f"  • {q}")
        raise typer.Exit(code=0)

    tag = "收斂 (converged)" if result["converged"] else "達上限 (forced_stop)"
    console.print(f"[green]{tag}[/green] — 已產出 SOTBrief brief.v1")
    # Mirror the confirmed brief into the run's ResearchState if one exists.
    _mirror_brief_into_state(rid, base_dir, result["brief"], now)
    console.print(render_brief_summary(result["brief"]))


def render_brief_summary(brief_dict: dict) -> str:
    if not brief_dict:
        return "(no brief)"
    b = sot_brief.SOTBrief(**brief_dict)
    return b.to_markdown()


def _mirror_brief_into_state(rid: str, base_dir: str, brief_dict, now: str) -> None:
    """Populate ResearchState.research_brief from the confirmed SOTBrief so the
    loop's write_brief node reads it instead of the P1 stub. No-op if no state."""
    if not brief_dict:
        return
    try:
        state = load_snapshot(rid, base_dir=base_dir)
    except FileNotFoundError:
        return
    b = sot_brief.SOTBrief(**brief_dict)
    state.research_brief = b.to_markdown()
    state.forbidden_directions = list(b.forbidden_directions)
    state.available_sources = list(b.available_sources)
    state.updated_at = now
    save_snapshot(state, base_dir=base_dir)


@app.command()
def brief(run_id: str = typer.Argument(...)):
    """顯示某個 run 的最新 SOTBrief。"""
    try:
        b = sot_brief.load_latest(run_id, base_dir=_base_dir())
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    console.print(b.to_markdown())


@app.command("revise-brief")
def revise_brief(
    run_id: str = typer.Argument(...),
    field: str = typer.Option(..., "--field", help="要修訂的欄位名"),
    value: str = typer.Option(..., "--value", help="新值（list 欄位用逗號分隔）"),
):
    """修訂 SOTBrief 的某個欄位，寫出 brief.v<N+1> 並 supersede 舊版。

    若新值與現有 SOT 值矛盾，先印出 conflict（不靜默覆蓋），仍寫出新版供人類審視。
    """
    base_dir = _base_dir()
    now = _now()
    try:
        current = sot_brief.load_latest(run_id, base_dir=base_dir)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if field not in sot_brief.SOTBrief.model_fields:
        console.print(f"[red]未知欄位：{field}[/red]")
        raise typer.Exit(code=2)

    list_fields = {name for name, f in sot_brief.SOTBrief.model_fields.items()
                   if "list" in str(f.annotation)}
    new_value = [v.strip() for v in value.split(",") if v.strip()] if field in list_fields else value

    conflict = detect_conflict(current, {field: new_value}, source="revise-brief")
    if conflict is not None:
        console.print(f"[yellow]! 偵測到與 SOT 矛盾（不靜默覆蓋）[/yellow] "
                      f"field={conflict.field} severity={conflict.severity.value}")
        console.print(f"  SOT: {conflict.sot_value!r}")
        console.print(f"  新值: {conflict.new_value!r}")

    new_version = current.version + 1
    data = current.model_dump()
    data[field] = new_value
    data["version"] = new_version
    data["status"] = sot_brief.BriefStatus.draft
    data["created_at"] = now
    revised = sot_brief.SOTBrief(**data)
    sot_brief.save(revised, run_id, base_dir=base_dir)
    superseded = sot_brief.supersede(run_id, up_to_version=current.version,
                                     base_dir=base_dir, now=now)
    _mirror_brief_into_state(run_id, base_dir, revised.model_dump(mode="json"), now)
    console.print(f"[green]已寫出[/green] brief.v{new_version}；supersede 版本={superseded}")


if __name__ == "__main__":
    app()
