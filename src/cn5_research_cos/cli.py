"""Typer CLI: cos init / run / show / validate.

Supplies run_id + ISO timestamps into the deterministic core (no wall-clock in
nodes/models). Base dir overridable via CN5_COS_BASE_DIR (used by tests).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import typer
from rich.console import Console

import sys

from . import render
from .graph import apply_steer, compile_with_checkpoint, run_auto
from .observability import StageReporter
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


def _refuse_if_hidden_or_exit(allow_redirect: bool) -> bool:
    """P5d guarantee #3: refuse (exit 2) when BOTH stdout and stderr are
    non-interactive and no escape was chosen, so the live debate can't be
    ACCIDENTALLY hidden. Returns True iff the caller should stop (the message was
    printed + a typer.Exit(2) raised is preferred, but we return a sentinel so the
    command can ``return`` cleanly). Escapes honored inside ``refuse_if_hidden``:
    ``--allow-redirect`` / cockpit / ``CN5_COS_ALLOW_REDIRECT=1``."""
    from .observability.guard import refuse_if_hidden

    msg = refuse_if_hidden((sys.stdout, sys.stderr), allow_redirect=allow_redirect)
    if msg is not None:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
        raise typer.Exit(code=2)
    return False


def _run_dir_for(base_dir: str, rid: str) -> str:
    return os.path.join(base_dir, rid)


def _announce_debate_path(rid: str, run_dir: str) -> None:
    """Print where the durable debate transcript lives + the one-command watcher,
    so a colleague can follow the war-room debate with no knowledge of paths."""
    console.print(f"[dim]💬 辯論全文（即時存檔）：{os.path.join(run_dir, 'debate.md')}[/dim]")
    console.print(f"[dim]   跟看：cos watch {rid}[/dim]")


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


def _print_pull_ask(rid: str, payload: dict) -> None:
    """Print a §9.1 human-pull ask payload + how to resume (the run is PAUSED)."""
    console.rule("[bold yellow]需要人類介入（PAUSED）[/bold yellow]")
    console.print(f"[bold]背景：[/bold]{payload.get('context','')}")
    console.print(f"[bold]為何要問：[/bold]{payload.get('why','')}")
    console.print("[bold]選項：[/bold]")
    for opt in payload.get("options", []):
        console.print(f"  • {opt}")
    console.print(f"[bold]AI 建議：[/bold]{payload.get('ai_recommendation','')}")
    if payload.get("impact_per_option"):
        console.print("[bold]各選項影響：[/bold]")
        for k, v in payload["impact_per_option"].items():
            console.print(f"  {k}: {v}")
    console.print(f"[bold]無回應時的預設：[/bold]{payload.get('default_if_no_response','')}")
    console.print("")
    console.print("[dim]此 run 已暫停（PAUSED），state 已存於 checkpoint。回答後續跑：[/dim]")
    console.print(f'  [green]cos resume {rid} --choice <A|B|C>[/green]  或  '
                  f'[green]cos resume {rid} --answer "..."[/green]')


@app.command()
def run(
    question: str = typer.Option(None, "--question", "-q"),
    run_id: str = typer.Option(None, "--run-id"),
    max_iterations: int = typer.Option(8, "--max-iterations"),
    llm: str = typer.Option("mock", "--llm"),
    research_source: str = typer.Option("auto", "--research-source",
                                        help="證據來源：web|internal|auto|both（預設 auto）"),
    resume: bool = typer.Option(False, "--resume",
                                help="從上次 checkpoint 續跑（需 --run-id），不重頭跑"),
    resume_state: bool = typer.Option(False, "--resume-state",
                                      help="從已存的 state.json 起一個互動式 run（需 --run-id）"),
    stream: bool = typer.Option(True, "--stream/--no-stream",
                                help="即時把每個 stage 的辯論摘要（含 Albert 全文）串流到 stdout"),
    allow_redirect: bool = typer.Option(False, "--allow-redirect",
                                        help="允許在非互動式終端機（pipe/重導/背景）執行；辯論仍存於 runs/<id>/debate.md"),
):
    """跑研究收斂迴圈（互動式）：跑到 gate interrupt 就暫停並印 ask payload + 如何 resume。

    無 gate 時跑到收斂，逐輪印中文 summary，最後印停止原因 + 四項 readiness 分數。
    """
    if llm not in ("mock", "real"):
        console.print(f"[red]--llm 僅支援 mock|real；收到 {llm!r}[/red]")
        raise typer.Exit(code=2)
    if research_source not in ("web", "internal", "auto", "both"):
        console.print(f"[red]--research-source 僅支援 web|internal|auto|both；收到 {research_source!r}[/red]")
        raise typer.Exit(code=2)

    # P5d guarantee #3: refuse to run when the live debate would be ACCIDENTALLY
    # hidden (no interactive tty on stdout/stderr) unless an escape was chosen.
    if _refuse_if_hidden_or_exit(allow_redirect):
        return

    now = _now()
    base_dir = _base_dir()

    final_state: ResearchState | None = None
    last_decision: Decision | None = None
    last_printed_iter = -1
    cfg_base = {"recursion_limit": 200}

    if resume:
        if not run_id:
            console.print("[red]--resume 需要 --run-id[/red]")
            raise typer.Exit(code=2)
        rid = run_id
        app_graph, _saver, conn = compile_with_checkpoint(os.path.join(base_dir, rid))
        cfg = {**cfg_base, "configurable": {"thread_id": rid}}
        stream_input = None  # replay from checkpoint, do not restart
    elif resume_state:
        if not run_id:
            console.print("[red]--resume-state 需要 --run-id[/red]")
            raise typer.Exit(code=2)
        rid = run_id
        try:
            initial = load_snapshot(rid, base_dir=base_dir)
        except FileNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)
        initial.mode = "interactive"
        app_graph, _saver, conn = compile_with_checkpoint(os.path.join(base_dir, rid))
        cfg = {**cfg_base, "configurable": {"thread_id": rid}}
        stream_input: GraphState | None = {
            "research_state": initial, "base_dir": base_dir, "now": now,
            "max_iterations": max_iterations, "llm": llm,
            "research_source": research_source,
            "mode": "interactive", "enable_h6": True,
        }
    else:
        if not question:
            console.print("[red]--question 為必填（除非 --resume / --resume-state）[/red]")
            raise typer.Exit(code=2)
        rid = run_id or "run-" + now.replace(":", "").replace("-", "")
        initial = ResearchState(run_id=rid, original_question=question,
                                created_at=now, updated_at=now)
        app_graph, _saver, conn = compile_with_checkpoint(os.path.join(base_dir, rid))
        cfg = {**cfg_base, "configurable": {"thread_id": rid}}
        stream_input: GraphState | None = {
            "research_state": initial, "base_dir": base_dir, "now": now,
            "max_iterations": max_iterations, "llm": llm,
            "research_source": research_source,
            "mode": "interactive", "enable_h6": True,
        }

    from .llm import sdk_client
    from .llm.metrics import RunMetrics

    metrics = RunMetrics()

    # P5d: announce the durable debate transcript + the one-command watcher.
    run_dir = _run_dir_for(base_dir, rid)
    _announce_debate_path(rid, run_dir)

    def _stream() -> None:
        nonlocal final_state, last_decision, last_printed_iter
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
                # P5 soft budget warning: cumulative cost/iter/calls each iteration
                # (informational only — never auto-truncates research).
                console.print(f"[dim]{metrics.summary_line(iteration=rs.iteration_count)}[/dim]")
                console.print("")
                last_printed_iter = rs.iteration_count

    # P5b: stream the live adversarial debate (per-stage block incl. Albert's full
    # output) to stdout as the loop runs. The checkpointed graph cannot carry the
    # reporter in GraphState, so publish it on the loop's contextvar for the
    # duration of the run. flushed + non-tty-safe → survives pipe/redirect/bg.
    from .graph import _REPORTER_CV
    # P5d: the reporter gets run_dir so the debate persists to runs/<id>/debate.md
    # (fail-closed durable sink) regardless of the live stream's fate.
    _reporter = StageReporter(sys.stdout, run_dir=run_dir) if stream else None
    _tok = _REPORTER_CV.set(_reporter) if _reporter is not None else None
    try:
        # P2 acceleration: for a real run, open ONE persistent ClaudeSession pool
        # so the cheap-LLM brains reuse a `claude` across calls (pay ~12s startup
        # once, not per call) and accumulate cost/latency into `metrics`.
        if llm == "real":
            with sdk_client.use_session_pool(metrics=metrics):
                _stream()
        else:
            _stream()

        # Did a gate interrupt() pause the run? If so, print the ask + how to resume.
        snap = app_graph.get_state(cfg)
        if snap.next:
            payload = snap.interrupts[0].value if snap.interrupts else {}
            paused_state = snap.values.get("research_state")
            if paused_state is not None:
                save_snapshot(paused_state, base_dir=base_dir)
            _print_pull_ask(rid, payload)
            return
    finally:
        conn.close()
        if _tok is not None:
            _REPORTER_CV.reset(_tok)

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
    # P2 acceleration: one-line cost/latency/calls summary (real runs accumulate
    # real $ + wall-clock; a mock run prints zeros, which is also useful signal).
    console.print("")
    console.print(f"[dim]{metrics.summary_line()}[/dim]")


@app.command()
def resume(
    run_id: str = typer.Argument(...),
    answer: str = typer.Option(None, "--answer", "-a", help="自由文字回答 gate 的提問"),
    choice: str = typer.Option(None, "--choice", "-c", help="選項代號 A/B/C"),
    max_iterations: int = typer.Option(8, "--max-iterations"),
):
    """回答一個暫停中的 gate：Command(resume=...) 從 checkpoint 續跑（不重頭）。"""
    if answer is None and choice is None:
        console.print("[red]需要 --answer 或 --choice 至少一個[/red]")
        raise typer.Exit(code=2)
    from langgraph.types import Command

    base_dir = _base_dir()
    app_graph, _saver, conn = compile_with_checkpoint(os.path.join(base_dir, run_id))
    cfg = {"recursion_limit": 200, "configurable": {"thread_id": run_id}}
    resume_value = {"choice": choice, "answer": answer or ""}
    final_state = None
    try:
        snap0 = app_graph.get_state(cfg)
        if not snap0.next:
            console.print(f"[yellow]run {run_id} 沒有暫停中的 gate（可能已完成）[/yellow]")
            raise typer.Exit(code=1)
        for chunk in app_graph.stream(Command(resume=resume_value), config=cfg,
                                      stream_mode="values"):
            rs = chunk.get("research_state")
            if rs is not None:
                final_state = rs
        snap = app_graph.get_state(cfg)
        if final_state is not None:
            save_snapshot(final_state, base_dir=base_dir)
        if snap.next:
            payload = snap.interrupts[0].value if snap.interrupts else {}
            console.print(f"[yellow]續跑後又遇到下一個 gate（PAUSED）[/yellow]")
            _print_pull_ask(run_id, payload)
            return
    finally:
        conn.close()
    console.print(f"[green]已回答並續跑[/green] run_id={run_id} "
                  f"choice={choice!r} answer={answer!r}")
    if final_state is not None:
        console.print(f"目前 iteration={final_state.iteration_count}")


@app.command()
def steer(
    run_id: str = typer.Argument(...),
    text: str = typer.Argument(..., help="臨時導引指令（H4），下一輪 COS 會重排/分支"),
):
    """注入一個臨時導引事件（H4）：append 到 checkpointed state，下一輪重排。"""
    base_dir = _base_dir()
    now = _now()
    try:
        state = load_snapshot(run_id, base_dir=base_dir)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    apply_steer(state, text, now=now)
    save_snapshot(state, base_dir=base_dir)
    console.print(f"[green]已注入 steer 事件[/green] run_id={run_id}：{text}")
    console.print("[dim]下一次 cos run --resume / run-auto 的下一輪會重排。[/dim]")


@app.command("run-auto")
def run_auto_cmd(
    question: str = typer.Option(..., "--question", "-q"),
    run_id: str = typer.Option(None, "--run-id"),
    max_iterations: int = typer.Option(8, "--max-iterations"),
    llm: str = typer.Option("mock", "--llm"),
    research_source: str = typer.Option("auto", "--research-source",
                                        help="證據來源：web|internal|auto|both（預設 auto）"),
    default_priority: str = typer.Option(None, "--default-priority",
                                         help="auto 模式無人時的預設研究優先序"),
    stream: bool = typer.Option(True, "--stream/--no-stream",
                                help="即時把每個 stage 的辯論摘要（含 Albert 全文）串流到 stdout"),
    allow_redirect: bool = typer.Option(False, "--allow-redirect",
                                        help="允許在非互動式終端機（pipe/重導/背景）執行；辯論仍存於 runs/<id>/debate.md"),
):
    """隔夜 AUTO 模式：低風險 gate 自動套預設、高風險硬停（可 resume）；印每輪 + 停止原因。"""
    if llm not in ("mock", "real"):
        console.print(f"[red]--llm 僅支援 mock|real；收到 {llm!r}[/red]")
        raise typer.Exit(code=2)
    if research_source not in ("web", "internal", "auto", "both"):
        console.print(f"[red]--research-source 僅支援 web|internal|auto|both；收到 {research_source!r}[/red]")
        raise typer.Exit(code=2)
    # P5d guarantee #3: refuse if the live debate would be ACCIDENTALLY hidden.
    if _refuse_if_hidden_or_exit(allow_redirect):
        return
    now = _now()
    base_dir = _base_dir()
    rid = run_id or "run-" + now.replace(":", "").replace("-", "")
    _announce_debate_path(rid, _run_dir_for(base_dir, rid))
    initial = ResearchState(run_id=rid, original_question=question,
                            mode="auto", created_at=now, updated_at=now)
    # P5b/P5d: stream the live debate (incl. Albert's full output) to stdout as the
    # auto loop runs — flushed + non-tty-safe — AND persist it durably (fail-closed)
    # to runs/<id>/debate.md via run_dir (survives pipe/redirect/background/no-tty).
    _reporter = StageReporter(sys.stdout, run_dir=_run_dir_for(base_dir, rid)) if stream else None
    result = run_auto(initial, base_dir=base_dir, max_iterations=max_iterations,
                      now=now, llm=llm, research_source=research_source,
                      default_priority=default_priority, run_id=rid,
                      reporter=_reporter)
    final = result["state"]

    console.rule(f"[bold]AUTO run {rid}[/bold]")
    console.print(f"共執行 [bold]{final.iteration_count}[/bold] 輪")
    if result["paused"]:
        console.print("[bold yellow]高風險硬停（PAUSED，可 resume）[/bold yellow]")
        if result["ask"] is not None:
            _print_pull_ask(rid, result["ask"])
    else:
        console.print(f"[bold]停止原因[/bold]（{result['reason_kind']}）：{result['stop_reason']}")
        console.print("")
        console.print("最終 readiness 分數：")
        console.print(render.render_readiness(final))
    # P5 soft budget warning: cumulative cost/iter/calls (informational only; the
    # auto loop never auto-truncates research on budget — see spec cost-governance).
    _metrics = result.get("metrics")
    if _metrics is not None:
        console.print("")
        console.print(f"[dim]{_metrics.summary_line(iteration=final.iteration_count)}[/dim]")


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
def watch(
    run_id: str = typer.Argument(..., help="要跟看的 run id"),
    follow: bool = typer.Option(True, "--follow/--no-follow",
                                help="持續跟看新增的辯論區塊（tail -f 等效）；--no-follow 只印一次"),
    poll_seconds: float = typer.Option(0.5, "--poll-seconds",
                                       help="follow 模式的輪詢間隔（秒）"),
):
    """跟看某個 run 的辯論全文：印出 runs/<run_id>/debate.md，並（預設）持續跟看新增區塊。

    一個指令、不必懂 tail/路徑就能即時看 war-room 辯論。Ctrl-C 結束。
    """
    base_dir = _base_dir()
    debate_path = os.path.join(_run_dir_for(base_dir, run_id), "debate.md")
    if not os.path.exists(debate_path):
        console.print(f"[red]找不到辯論存檔：{debate_path}[/red]")
        console.print("[dim]（run 尚未開始寫 debate.md，或 run_id 有誤）[/dim]")
        raise typer.Exit(code=1)

    # Print everything already on disk, then (optionally) follow new appends. Read
    # in binary + decode utf-8 so a partially-written CJK tail never raises.
    with open(debate_path, "rb") as f:
        existing = f.read()
        sys.stdout.write(existing.decode("utf-8", errors="replace"))
        sys.stdout.flush()
        if not follow:
            return
        pos = f.tell()
    console.print(f"[dim]— 跟看中（Ctrl-C 結束）：{debate_path} —[/dim]")
    import time as _time
    try:
        while True:
            with open(debate_path, "rb") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
            if chunk:
                sys.stdout.write(chunk.decode("utf-8", errors="replace"))
                sys.stdout.flush()
            _time.sleep(poll_seconds)
    except KeyboardInterrupt:
        console.print("\n[dim]— 結束跟看 —[/dim]")


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
