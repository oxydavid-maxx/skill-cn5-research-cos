"""Dogfood runner — run the cockpit on a topic file end-to-end, capture the live
research process (per-stage flow + wall-clock timing) to runs/<id>/debate.md,
assemble the gated §22 memo, and email the result. Diagnostic harness (not product).

Usage:
  py -3 scripts/dogfood.py "<topic_file>" [--llm real|mock] [--albert sim|real]
       [--max-iterations N] [--email <addr>] [--no-email]

The user is AFK; this self-paces and emails the final output. Stage timing comes
from a timestamping StageReporter (records wall-clock at each stage block).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cn5_research_cos.observability.reporter import StageReporter
from cn5_research_cos.graph import run_auto
from cn5_research_cos.llm.metrics import RunMetrics
from cn5_research_cos.models import ResearchState


class TimingReporter(StageReporter):
    """StageReporter that records (stage, wall_clock) so we can report per-stage time."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.marks: list[tuple[str, float]] = []
        self._t0 = time.time()

    def stage(self, name: str, body: str) -> None:
        self.marks.append((name, time.time()))
        super().stage(name, body)

    def timing_table(self) -> str:
        if not self.marks:
            return "(no stages recorded)"
        rows = ["stage | at(s) | delta(s)", "---|---|---"]
        prev = self._t0
        for name, t in self.marks:
            rows.append(f"{name} | {t - self._t0:6.1f} | {t - prev:6.1f}")
            prev = t
        rows.append(f"TOTAL wall: {self.marks[-1][1] - self._t0:.1f}s over {len(self.marks)} stage-blocks")
        return "\n".join(rows)


def _state_of(result) -> ResearchState:
    for k in ("research_state", "state", "final"):
        if isinstance(result, dict) and k in result:
            return result[k]
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("topic")
    ap.add_argument("--llm", default="real")
    ap.add_argument("--albert", default="sim")
    ap.add_argument("--research-source", default="web")
    ap.add_argument("--max-iterations", type=int, default=3)
    ap.add_argument("--email", default="kuangyu@realtek.com")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)

    topic_path = Path(args.topic)
    question = topic_path.read_text(encoding="utf-8").strip()
    run_id = args.run_id or ("dogfood-" + topic_path.stem.replace(" ", "-"))
    base_dir = Path("runs")
    run_dir = base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    reporter = TimingReporter(sys.stdout, run_dir=run_dir)
    metrics = RunMetrics()
    rs = ResearchState(run_id=run_id, original_question=question, mode="auto")

    t0 = time.time()
    err = None
    paused = False
    try:
        result = run_auto(rs, base_dir=str(base_dir), max_iterations=args.max_iterations,
                          now="t0", llm=args.llm, research_source=args.research_source,
                          albert=args.albert, run_id=run_id, metrics=metrics, reporter=reporter)
        final = _state_of(result)
        paused = isinstance(result, dict) and bool(result.get("ask"))
    except Exception as e:  # always report what we have
        err = f"{type(e).__name__}: {e}"
        final = rs
    wall = time.time() - t0

    # Assemble + gate the §22 memo (explicit emit so a bounded run still produces one).
    memo_txt = ""
    try:
        from cn5_research_cos.brains import build_brains
        from cn5_research_cos.synthesis.memo import assemble_memo
        from cn5_research_cos.synthesis.gates import check_emission
        synth = build_brains(llm=args.llm, albert=args.albert).synthesizer
        memo = assemble_memo(final, synth)
        check_emission(final, memo, explicit=True)
        memo_txt = "\n\n".join(f"## {s.title}\n{s.body}" for s in memo.sections)
        (run_dir / "memo.md").write_text(memo_txt, encoding="utf-8")
    except Exception as e:
        memo_txt = f"(memo assembly failed: {type(e).__name__}: {e})"

    issues = len(final.issue_map)
    challenges = len(final.albert_challenge_map)
    summary = (
        f"DOGFOOD: {topic_path.name}\n"
        f"run_id={run_id}  llm={args.llm}  albert={args.albert}  max_iter={args.max_iterations}\n"
        f"wall={wall:.0f}s  cost={metrics.summary_line()}\n"
        f"iterations={final.iteration_count}  issues={issues}  challenges={challenges}  "
        f"paused={paused}  error={err}\n\n"
        f"=== STAGE FLOW + TIMING ===\n{reporter.timing_table()}\n\n"
        f"=== readiness ===\n{getattr(final, 'readiness_score', None)}\n\n"
        f"=== §22 MEMO (explicit emit) ===\n{memo_txt[:12000]}\n\n"
        f"(full debate stream: {run_dir/'debate.md'} ; full memo: {run_dir/'memo.md'})"
    )
    print(summary)

    if not args.no_email:
        try:
            from cn5_research_cos.notify import email as E
            E._default_send(to=args.email,
                            subject=f"[CN5 cockpit DOGFOOD] {topic_path.stem} — {issues} issues / {challenges} challenges / {wall:.0f}s",
                            body=summary)
            print("EMAIL SENT to", args.email)
        except Exception as e:
            print("EMAIL FAILED:", type(e).__name__, e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
