"""Deterministic §22 decision-memo assembly (P5, no LLM except the synthesizer).

``assemble_memo(state, synthesizer)`` calls the LLM ``Synthesizer`` ONCE for the
per-section prose, then deterministically:

  * builds a ``MemoSection`` for EACH of the 9 §22 keys, in a fixed order, with a
    fixed display title;
  * labels the §4 blockers (``synthesis.blockers.label_blockers``, 6 kinds) and
    annotates the ``blocking`` section body with them;
  * annotates the ``albert_challenge_map`` section with each challenge's status.

Citation wiring (P4b verify/policy/flatten) is layered on in Task 6 (same module).
The emission gates (Task 7) decide ``emitted``; assembly never sets it.
"""
from __future__ import annotations

from ..brains.synthesis import SECTION_KEYS
from ..models import Blocker, Memo, MemoSection, ResearchState
from .blockers import label_blockers

# Single source of truth for the 9 section keys (mirrors brains.synthesis.SECTION_KEYS).
NINE_SECTION_KEYS = list(SECTION_KEYS)

# Fixed display titles (Traditional Chinese, §22 wording).
SECTION_TITLES: dict[str, str] = {
    "executive_answer": "一、Executive Answer（主管級結論）",
    "albert_challenge_map": "二、Albert Challenge Map（質疑地圖）",
    "can_cannot_say": "三、What We Can / Cannot Say（能說 / 不能說）",
    "blocking": "四、What Is Blocking Us（阻擋點）",
    "required_human_decisions": "五、Required Human Decisions / Inputs（需人類決策 / 輸入）",
    "evidence_summary": "六、Evidence Summary（證據摘要，已引用）",
    "risks_assumptions": "七、Risks & Assumptions（風險與假設）",
    "recommended_next_action": "八、Recommended Next Action（建議下一步）",
    "appendix": "九、Appendix（附錄）",
}


def _render_blockers(blockers: list[Blocker]) -> str:
    """A deterministic, labeled rendering of §4 blockers (one line per blocker)."""
    if not blockers:
        return "（目前沒有阻擋點。）"
    lines = []
    for b in blockers:
        owner = f" owner={b.owner}" if b.owner else ""
        lines.append(f"- [{b.blocker_type.value}] {b.description} "
                     f"(source={b.source_id}{owner})")
    return "\n".join(lines)


def _render_challenge_statuses(state: ResearchState) -> str:
    """Annotate each Albert challenge with its convergence status (§2)."""
    if not state.albert_challenge_map:
        return "（目前沒有 Albert 質疑。）"
    return "\n".join(
        f"- [{c.status.value}] {c.challenge}"
        for c in state.albert_challenge_map.values()
    )


def assemble_memo(state: ResearchState, synthesizer) -> Memo:
    """Assemble the §22 memo: LLM prose + deterministic structure/labels.

    The only LLM call is ``synthesizer.write_sections`` (one structured call).
    Everything else — the 9-section SET, titles, blocker labels, challenge-status
    annotation — is pure Python. Does NOT set ``emitted`` (the gates do, Task 7).
    """
    prose = synthesizer.write_sections(state)
    blockers = label_blockers(state)

    sections: list[MemoSection] = []
    for key in NINE_SECTION_KEYS:
        body = str(prose.get(key, "") or "").strip()
        if key == "blocking":
            labeled = _render_blockers(blockers)
            body = f"{body}\n\n{labeled}" if body else labeled
        elif key == "albert_challenge_map":
            statuses = _render_challenge_statuses(state)
            body = f"{body}\n\n{statuses}" if body else statuses
        sections.append(MemoSection(
            key=key, title=SECTION_TITLES[key], body=body,
        ))

    return Memo(sections=sections, blockers=blockers)
