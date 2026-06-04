"""Outlook-COM supplement-needed email notifier (P5c Component 2, fail-soft).

When the confidence-citation policy (``synthesis.memo.route_citations``) routes a
decision-critical claim to ``needs_supplement`` (it could NOT be verified), the
loop emails the user — it does NOT fabricate and does NOT block. The email carries:

  * the ``run_id``;
  * WHAT is needed (each unverified-critical claim + why it could not be verified);
  * COPY-PASTE-READY commands to supplement asynchronously:
      - text answer:      ``cos steer <run_id> "<your answer>"``
      - a document:       drop the file into ``runs/<run_id>/reference/`` then
                          ``cos steer <run_id> "added <filename>"`` (PDF/PPT/Word/
                          Excel/HTML/Markdown supported).

The win32com Outlook send MIRRORS daily_brief's proven pattern
(``win32com.client.Dispatch("Outlook.Application")`` -> ``CreateItem(0)`` ->
set ``.To``/``.Subject``/``.Body`` -> ``.Send()``). It is NOT cross-imported from
the sibling project. The import lives INSIDE the default send callable so tests can
inject a fake ``send`` and need no Outlook installed.

FAIL-SOFT: any send exception is caught, logged as a VISIBLE warning, and the
function returns ``False`` — it NEVER raises. The HumanTask the supplement maps to
is recorded by the loop regardless, so the user still sees the need via ``cos show``.
"""
from __future__ import annotations

import logging
from typing import Callable, Sequence

from ..models import HumanTask

logger = logging.getLogger("cn5_research_cos.notify")

# Send-to-self default (the cockpit is terminal-run on the user's Windows box with
# their Outlook signed in). Overridable per call.
DEFAULT_RECIPIENT = "kuangyu@realtek.com"

# A SendFn takes keyword args so callers/tests cannot mix up positional order.
SendFn = Callable[..., None]


def _is_internal_data_item(t: HumanTask) -> bool:
    """Classify a consolidated item as an H3 internal-data ask (vs a B-4 unverified-
    critical claim). Same textual signal used by the graph wiring: ``內部`` appears
    across the task's user-facing fields (``node_human_push`` builds it with
    ``requested_input='內部資料 / 受限文件'`` / ``task_title='提供內部資料：…'``)."""
    blob = f"{t.requested_input}\n{t.why_needed}\n{t.task_title}"
    return "內部" in blob


def build_supplement_email(run_id: str, items: Sequence[HumanTask]) -> str:
    """Compose the (pure) email body: run_id + each item's need + copy-paste
    supplement commands + the reference-folder drop instruction. Deterministic.

    The consolidated email (P8 §5) groups items under two headings:
      * ``需驗證補充（決策關鍵主張）`` — B-4 unverified-critical claims, and
      * ``需內部資料`` — H3 internal/restricted-data asks.
    Each item keeps clear per-item context so an ambiguous classification is still
    actionable."""
    b4 = [t for t in items if not _is_internal_data_item(t)]
    internal = [t for t in items if _is_internal_data_item(t)]
    lines = [
        f"研究 run {run_id} 有 {len(items)} 項需要您補充（{len(b4)} 項需驗證補充、"
        f"{len(internal)} 項需內部資料）。系統並未捏造，也沒有停下來等您——迴圈已繼續，"
        "這些項目目前只列在 memo 的『不能說 / 需人類決策』區，標記為 needs human "
        "supplement，不會當作事實。",
        "",
    ]

    def _emit(heading: str, group: Sequence[HumanTask]) -> None:
        if not group:
            return
        lines.append(heading + "：")
        for i, t in enumerate(group, 1):
            need = t.requested_input or t.task_title or t.blocking_question
            lines.append(f"  {i}. {need}")
            if t.why_needed:
                lines.append(f"     （為何需要：{t.why_needed}）")
        lines.append("")

    _emit("需驗證補充（決策關鍵主張）", b4)
    _emit("需內部資料", internal)
    lines += [
        "",
        "如何補充（擇一，可重複）：",
        "",
        "  A. 文字回答（直接把答案/判斷貼給系統）：",
        f'       cos steer {run_id} "<您的回答>"',
        "",
        "  B. 文件補充（PDF / PPT / Word / Excel / HTML / Markdown）：",
        f"       1) 把檔案放進資料夾： runs/{run_id}/reference/",
        f'       2) 然後執行：        cos steer {run_id} "added <檔名>"',
        "",
        "系統下一輪會自動讀取您補充的資料，重新研究 / 重新驗證這些項目。",
    ]
    return "\n".join(lines)


def _default_send(*, to: str, subject: str, body: str) -> None:
    """The real Outlook-COM send (mirrors daily_brief/publishers/email_sender.py).

    win32com is imported HERE (not at module load) so tests injecting a fake
    ``send`` never require Outlook / pywin32. A missing win32com or a Dispatch/Send
    failure propagates as an exception that ``notify_supplement_needed`` catches
    (fail-soft)."""
    import win32com.client  # local import: only the real send needs it

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # 0 = olMailItem
    mail.To = to
    mail.Subject = subject
    mail.Body = body
    mail.Send()


def notify_supplement_needed(run_id: str, items: Sequence[HumanTask], *,
                             base_dir: str = "runs",
                             recipient: str = DEFAULT_RECIPIENT,
                             send: SendFn | None = None) -> bool:
    """Email the user that ``items`` need supplementing for ``run_id``. Fail-soft.

    Returns True iff an email was composed AND ``send`` returned without raising.
    No items -> no email, returns False. A send exception -> a VISIBLE warning is
    logged and False is returned (NEVER raises): the supplement HumanTasks are
    already recorded on the state, so the need is not lost.

    ``base_dir`` is accepted for signature stability / future use (the body's
    drop-folder path is run-relative ``runs/<run_id>/reference/`` per the manual).
    """
    if not items:
        return False
    send_fn = send or _default_send
    subject = f"[CN5 Research COS] run {run_id}：需要您補充 {len(items)} 項決策關鍵主張"
    body = build_supplement_email(run_id, items)
    try:
        send_fn(to=recipient, subject=subject, body=body)
    except Exception as e:  # noqa: BLE001 - fail-soft: notify must never crash the loop
        logger.warning(
            "[notify] supplement-needed email for run %s FAILED to send: %s — "
            "the %d HumanTask(s) are still recorded; see them via `cos show %s`. "
            "NO fabrication; the loop continues.",
            run_id, e, len(items), run_id,
        )
        return False
    logger.info("[notify] sent supplement-needed email for run %s to %s (%d items)",
                run_id, recipient, len(items))
    return True
