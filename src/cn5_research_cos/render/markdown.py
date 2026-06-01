"""Markdown renderers (Chinese headers) for the three artifacts + iteration summary."""
from __future__ import annotations

from ..artifacts import readiness_board
from ..models import (BoardColumn, Decision, IssueStatus, ResearchState)

_DECISION_REASON = {
    Decision.terminal_stop: "readiness 達標 → terminal stop（可定址問題已全部研究完且四項就緒度達標）",
    Decision.synthesize: "外部研究邊際效益低 → synthesize（進入整理模式；剩餘多為人類/內部資料瓶頸）",
    Decision.continue_research: "仍有高價值研究方向 → continue research",
    Decision.branch: "Albert 會挑戰新角度 → branch（建立新 issue 分支）",
    Decision.rerank: "目標改變 → rerank（重排既有 evidence）",
    Decision.pull_human: "需要方向判斷 → pull human（H1）",
    Decision.push_human: "需要人提供資料/驗證 → push human task（H3）",
    Decision.pause: "暫停",
}


def render_issue_map(state: ResearchState) -> str:
    if not state.issue_map:
        return "## Dynamic Issue Map\n\n（空）\n"
    lines = ["## Dynamic Issue Map", ""]
    lines.append("| id | 類型 | 標題 | 狀態 | impact | confidence |")
    lines.append("|---|---|---|---|---|---|")
    for n in state.issue_map.values():
        lines.append(
            f"| {n.id} | {n.issue_type.value} | {n.title} | {n.status.value} "
            f"| {n.impact} | {n.confidence} |"
        )
    return "\n".join(lines) + "\n"


def render_challenge_map(state: ResearchState) -> str:
    if not state.albert_challenge_map:
        return "## Albert Challenge Map\n\n（空）\n"
    lines = ["## Albert Challenge Map", ""]
    lines.append("| id | 挑戰 | 狀態 | 分類 |")
    lines.append("|---|---|---|---|")
    for c in state.albert_challenge_map.values():
        cls = c.classification.value if c.classification else "-"
        lines.append(f"| {c.id} | {c.challenge} | {c.status.value} | {cls} |")
    return "\n".join(lines) + "\n"


def render_board(state: ResearchState) -> str:
    board = readiness_board.derive_board(state)
    labels = {
        BoardColumn.answered: "已答",
        BoardColumn.pending: "進行中 / pending",
        BoardColumn.blocked: "blocked",
        BoardColumn.needs_human: "需要人",
    }
    lines = ["## Research Readiness Board", ""]
    for col in BoardColumn:
        ids = board[col]
        lines.append(f"- **{labels[col]}**: {', '.join(ids) if ids else '（無）'}")
    return "\n".join(lines) + "\n"


def render_readiness(state: ResearchState) -> str:
    rs = state.readiness_score
    lines = ["## Readiness Scoring", ""]
    if rs is None:
        lines.append("（尚未計分）")
        return "\n".join(lines) + "\n"
    lines.append(f"- Albert Challenge readiness: {rs.albert_challenge_readiness}/5")
    lines.append(f"- Decision readiness: {rs.decision_readiness}/5")
    lines.append(f"- Research Exhaustion readiness: {rs.research_exhaustion_readiness}/5")
    lines.append(f"- Human Bottleneck clarity: {rs.human_bottleneck_clarity}/5")
    lines.append(f"- should_continue: {rs.should_continue}")
    return "\n".join(lines) + "\n"


def iteration_summary(state: ResearchState) -> str:
    """Chinese per-iteration summary: 本輪新增 / Albert 會挑戰 / 已答 / pending /
    需要人 / 下一輪建議 + 四個 readiness 分數."""
    board = readiness_board.derive_board(state)
    answered = board[BoardColumn.answered]
    pending = board[BoardColumn.pending]
    needs_human = board[BoardColumn.needs_human] + board[BoardColumn.blocked]
    challenges = [c.challenge for c in state.albert_challenge_map.values()]
    rs = state.readiness_score

    lines = [f"=== 第 {state.iteration_count} 輪 Iteration Summary ==="]
    lines.append(f"本輪新增 issue 總數：{len(state.issue_map)}")
    lines.append(f"Albert 會挑戰：{('；'.join(challenges)) if challenges else '（暫無）'}")
    lines.append(f"已答：{', '.join(answered) if answered else '（無）'}")
    lines.append(f"pending：{', '.join(pending) if pending else '（無）'}")
    lines.append(f"需要人 / blocked：{', '.join(needs_human) if needs_human else '（無）'}")
    if rs is not None:
        lines.append(
            "下一輪建議：" + ("繼續研究" if rs.should_continue else "可進入整理 / 收斂")
        )
        lines.append(
            "readiness 分數 — "
            f"Albert={rs.albert_challenge_readiness} "
            f"Decision={rs.decision_readiness} "
            f"Exhaustion={rs.research_exhaustion_readiness} "
            f"Human={rs.human_bottleneck_clarity}"
        )
    return "\n".join(lines)


def stop_reason_line(decision: Decision | None) -> str:
    if decision is None:
        return "停止原因：未知"
    return "停止原因：" + _DECISION_REASON.get(decision, decision.value)
