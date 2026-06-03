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
from ..citation import policy as cpolicy
from ..citation import verify as cverify
from ..models import (Blocker, Claim, Memo, MemoSection, ResearchState, Source)
from .blockers import label_blockers

# Confidence at/above which a claim is "KEY" (decision-critical) — an unverified
# KEY claim blocks emission (Task 7's citation gate reads memo.unverified_key_claims).
KEY_CLAIM_CONF = 4

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


def _collect_claims_sources(state: ResearchState) -> tuple[list[Claim], dict[str, Source]]:
    """Flatten every evidence bundle's claims + sources into the memo's claim set."""
    claims: list[Claim] = []
    sources: dict[str, Source] = {}
    for b in state.evidence:
        for s in b.sources:
            sources[s.id] = s
        claims.extend(b.claims)
    return claims, sources


def citation_pass(state: ResearchState) -> list[str]:
    """Run the WIRED-IN P4b citation pipeline over the memo's claims (closes the
    P4b "built but not in loop" caveat). Returns the list of KEY claims that are
    UNVERIFIED after flatten + verify + policy — the citation emission gate (Task 7)
    refuses a memo while this is non-empty.

    Pipeline per claim (uses the EXISTING citation modules, never reimplemented):
      1. ``flatten_to_primary`` — strip digest refs; a claim left with NO primary
         ref is flattened to zero refs (it can no longer be verified).
      2. ``verify.verify_claim`` — web: difflib >= 0.85 against ``Source.excerpt``;
         internal: carried as paperwork-verified.
      3. ``policy.classify`` — an unverified KEY (high-confidence) claim is recorded.
    """
    claims, sources = _collect_claims_sources(state)
    source_texts = {sid: (s.excerpt or "") for sid, s in sources.items()}

    unverified_key: list[str] = []
    for claim in claims:
        # 1. flatten-to-primary: drop digest refs (verify reads the flattened refs).
        ok, repointed = cpolicy.flatten_to_primary(claim, sources)
        flat = claim.model_copy(update={"source_refs": repointed})

        # 2. verify (origin-routed). A digest-only claim (ok is False) has no refs
        #    left -> web verify finds no source text -> unverified.
        result = cverify.verify_claim(flat, sources, source_texts)

        # 3. policy: an unverified KEY claim is decision-critical and must block.
        critical = claim.confidence >= KEY_CLAIM_CONF
        action = cpolicy.classify(result, critical=critical, reverify_attempted=True)
        if not result.verified and critical and action.kind in ("escalate_human", "flag"):
            unverified_key.append(claim.claim)

    return unverified_key


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

    unverified_key = citation_pass(state)
    return Memo(sections=sections, blockers=blockers,
                unverified_key_claims=unverified_key)


def render_memo(memo: Memo) -> str:
    """Render the §22 memo to a Markdown string (the stored ``final_memo``)."""
    lines = ["# §22 Decision Memo"]
    if not memo.emitted and memo.refused_reason:
        lines.append(f"\n> ⚠ NOT EMITTED — {memo.refused_reason}\n")
    for s in memo.sections:
        lines.append(f"\n## {s.title}\n\n{s.body}")
    return "\n".join(lines)
