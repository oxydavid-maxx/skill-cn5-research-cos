"""One-shot re-synthesis: turn the EXISTING gathered evidence of a finished run
into the PARTIAL FILLED PK table the question asked for (NOT a meta-analysis of
why the full table is impossible), and email it as ONE email.

Why this exists: the findings-first synthesizer led the dogfood deliverable with
"why I can't deliver the full public-spec PK" instead of the partial table that
IS fillable from public evidence (NXP public specs filled, N/A for NDA-gated,
every value cited [S-…]). This runner re-synthesizes from the SAME evidence
already in runs/<run_id>/state.json — no new research, no extra loop.

Usage:
    py -3 scripts/resynth_partial_table.py --run-dir runs/dogfood-final-switchpk \
        --email kuangyu@realtek.com [--no-email]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cn5_research_cos.llm.sdk_client import call_structured  # noqa: E402
from cn5_research_cos.notify import email as E  # noqa: E402

_SYSTEM = (
    "你是一位資深 Automotive Ethernet Switch IC 競品分析研究員，正在交付一次研究"
    "的『部分填好的規格 PK』。為了精簡且誠實，採『只列有證據的格子』格式，鐵律：\n"
    "1. 先輸出『# 1 Product coverage』表：每個證據能確認的產品一列 "
    "| Vendor | Product | Product type | Switch? Y/N | [S-…] |。\n"
    "2. 再輸出『# 2 已知規格（filled cells only）』：用『長格式』，每一個『有證據"
    "支持的規格值』一列 | Product | Spec 欄位 | 值 | [S-…] |。**只列有值的格子**，"
    "不要印 100+ 欄的空表、不要為 N/A 開列。每個值必標 [S-…]（證據裡的 source id），"
    "絕不臆測、絕不捏造 [S-…]。\n"
    "3. 最後『# 3 資料缺口附註』：用條列說明哪些規格群（如 packet buffer、TCAM、"
    "MACsec SA、gate control list、process node、power）在公開來源整群查不到、為什麼"
    "（NDA / myICP 受限 / 非公開 datasheet），以及補齊各群需要什麼內部資料。簡短。\n"
    "4. 不要用『為什麼無法交付完整表』當開頭——表格在前、缺口附註在後。\n"
    "5. 繁體中文，技術名詞不翻譯。回傳嚴格 JSON：{\"report_md\": \"...\"}。"
)


def _render_evidence(state: dict) -> str:
    ev = state.get("evidence", [])
    claims, sources, seen = [], [], set()
    for b in ev:
        for c in b.get("claims", []):
            refs = " ".join(f"[{r}]" for r in c.get("source_refs", [])) or "[no-src]"
            note = (c.get("notes") or "").strip()
            line = f"- {c.get('claim','').strip()} {refs}"
            if note:
                line += f"  〔note: {note}〕"
            claims.append(line)
        for s in b.get("sources", []):
            sid = s.get("id")
            if sid in seen:
                continue
            seen.add(sid)
            exc = (s.get("excerpt") or "").strip().replace("\n", " ")
            sources.append(
                f"- [{sid}] {s.get('title','').strip()} {s.get('url') or ''}\n"
                f"    excerpt: {exc[:600]}"
            )
    return (
        f"原始問題:\n{state.get('original_question','')}\n\n"
        f"研究 brief:\n{state.get('research_brief') or '(none)'}\n\n"
        f"=== 證據 CLAIMS（{len(claims)} 條，填表時引用這些 [S-…]）===\n"
        + "\n".join(claims)
        + f"\n\n=== 來源 SOURCES（{len(sources)} 個，含 excerpt 可抽取實際數值）===\n"
        + "\n".join(sources)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--email", default="kuangyu@realtek.com")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    evidence_txt = _render_evidence(state)
    n_claims = sum(len(b.get("claims", [])) for b in state.get("evidence", []))
    n_src = len({s.get("id") for b in state.get("evidence", []) for s in b.get("sources", [])})
    print(f"loaded {n_claims} claims / {n_src} sources from {run_dir}")

    user = (
        evidence_txt
        + "\n\n請依上面證據輸出三段：# 1 Product coverage 表；# 2 已知規格（長格式，"
        "只列有 [S-…] 證據的格子，不印空表）；# 3 資料缺口附註（哪些規格群整群 N/A、"
        "為什麼、補齊需要什麼內部資料）。表格在前，附註在後。絕不臆測、絕不捏造 [S-…]。"
    )
    schema = {
        "type": "object",
        "properties": {"report_md": {"type": "string"}},
        "required": ["report_md"],
        "additionalProperties": False,
    }
    out = call_structured(_SYSTEM, user, schema, model=args.model, timeout_sec=600, attempts=2)
    report = str(out.get("report_md", "")).strip()
    if not report:
        print("ERROR: empty report", file=sys.stderr)
        return 2

    out_path = run_dir / "partial_pk_table.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"wrote {out_path} ({len(report)} chars)")

    if not args.no_email:
        body = (
            "這是從既有研究證據（"
            f"{n_claims} claims / {n_src} sources，run={run_dir.name}）重新合成的"
            "『部分填好的 Automotive Ethernet Switch PK 表』。\n"
            "原則：只填證據明確支持的值並標 [S-…]，查不到的填 N/A、不臆測。表格在前，"
            "資料缺口附註在後。\n\n"
            "—— 以下為報告 ——\n\n" + report
        )
        E._default_send(
            to=args.email,
            subject="[CN5 Research COS] Switch PK — 部分填好的表（從現有證據重合成）",
            body=body,
        )
        print("EMAIL SENT to", args.email)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
