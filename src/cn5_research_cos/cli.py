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


if __name__ == "__main__":
    app()
