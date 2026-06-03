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

from dataclasses import dataclass, field

from ..brains.synthesis import FINDINGS_KEY, SECTION_KEYS
from ..citation import policy as cpolicy
from ..citation import verify as cverify
from ..decision import risk as crisk
from ..models import (Blocker, Claim, Decision, HumanTask, HumanTaskStatus, Memo,
                      MemoSection, ResearchState, Source)
from .blockers import label_blockers

# Confidence at/above which a claim is "KEY" (decision-critical) — an unverified
# KEY claim blocks emission (Task 7's citation gate reads memo.unverified_key_claims).
KEY_CLAIM_CONF = 4

# Single source of truth for the 9 section keys (mirrors brains.synthesis.SECTION_KEYS).
NINE_SECTION_KEYS = list(SECTION_KEYS)

# Component A: the FINDINGS section title (the primary deliverable, leads).
FINDINGS_TITLE = "研究發現（Findings — 已引用 [S-…]，答覆原始問題）"

# Component A — the deliverable EMISSION ORDER (findings-first). The findings (the
# answer/artifact synthesized from evidence) LEAD; the evidence-facing §22 sections
# follow; the decision/audit sections (Albert challenge map, blocking, required
# human decisions, recommended next action, appendix) are the SUPPORTING TAIL.
# This is distinct from the synthesis schema order (SECTION_KEYS): the synthesizer
# fills the 9 §22 keys; assembly re-orders them so the deliverable leads with the
# findings, not the §22 questions dump.
_DECISION_TAIL_KEYS = [
    "executive_answer",
    "can_cannot_say",
    "risks_assumptions",
    "albert_challenge_map",
    "blocking",
    "required_human_decisions",
    "recommended_next_action",
    "appendix",
]
MEMO_ORDER = [FINDINGS_KEY, "evidence_summary", *_DECISION_TAIL_KEYS]

# Fixed display titles (Traditional Chinese, §22 wording).
SECTION_TITLES: dict[str, str] = {
    FINDINGS_KEY: FINDINGS_TITLE,
    "evidence_summary": "證據摘要（Evidence Summary，已引用）",
    "executive_answer": "Executive Answer（主管級結論）",
    "albert_challenge_map": "Albert Challenge Map（質疑地圖）",
    "can_cannot_say": "What We Can / Cannot Say（能說 / 不能說）",
    "blocking": "What Is Blocking Us（阻擋點）",
    "required_human_decisions": "Required Human Decisions / Inputs（需人類決策 / 輸入）",
    "risks_assumptions": "Risks & Assumptions（風險與假設）",
    "recommended_next_action": "Recommended Next Action（建議下一步）",
    "appendix": "Appendix（附錄）",
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


def _render_needs_supplement(items: list[str]) -> str:
    """Render the unverified-critical (needs-human-supplement) items, clearly
    flagged so they are NEVER read as verified fact."""
    if not items:
        return ""
    lines = ["⚠ 以下為決策關鍵但無法以引用驗證之項目（needs human supplement，"
             "非已驗證事實）："]
    for it in items:
        lines.append(f"- [needs human supplement] {it}")
    return "\n".join(lines)


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


# --------------------------------------------------------------------------- #
# P5c — confidence-based citation routing (cite / drop / notify-critical)
# --------------------------------------------------------------------------- #
@dataclass
class RouteResult:
    """The outcome of routing every memo claim through verify + criticality.

    * ``cited`` — verified claims (coverage >= 0.85). They are presented as fact.
    * ``dropped`` — unverified AND non-critical claims. Not cited, NO HumanTask,
      no fabrication: the claim simply is not presented as evidence.
    * ``needs_supplement`` — the HumanTasks created for unverified AND critical
      claims. These are surfaced (flagged) in the memo's cannot-say / required-
      decisions sections, NEVER presented as verified fact, and trigger a notify.
    """
    cited: list[Claim] = field(default_factory=list)
    dropped: list[Claim] = field(default_factory=list)
    needs_supplement: list[HumanTask] = field(default_factory=list)


def _claim_issue_ids(state: ResearchState) -> dict[int, str | None]:
    """Map each claim (by id()) to the issue_id of its owning evidence bundle, so
    a claim's criticality can read the owning issue's impact."""
    out: dict[int, str | None] = {}
    for b in state.evidence:
        for c in b.claims:
            out[id(c)] = b.issue_id
    return out


def _claim_is_critical(state: ResearchState, claim: Claim,
                       issue_id: str | None) -> bool:
    """Decision-criticality for ONE claim, reusing ``risk.classify_pull`` notions
    (no new magic number): the claim is critical iff its owning issue is high-
    impact (>= ``risk.HIGH_IMPACT``) AND the run is in a high-risk pull posture
    (``risk.classify_pull`` == "high") — i.e. picking a direction here without the
    missing verification gambles the high-impact frontier. A claim with no owning
    high-impact issue, or a run where the pull posture is low, is NOT critical."""
    node = state.issue_map.get(issue_id) if issue_id else None
    if node is None or node.impact < crisk.HIGH_IMPACT:
        return False
    return crisk.classify_pull(state, Decision.pull_human) == "high"


def route_citations(state: ResearchState) -> RouteResult:
    """Route every memo claim per the P5c confidence policy and create HumanTasks
    for the unverified-critical ones. Deterministic, no LLM, no wall-clock.

    Per claim: flatten-to-primary + verify (the EXISTING citation modules) ->
      verified            -> ``cited``;
      unverified + !crit   -> ``dropped`` (no task, no fabrication);
      unverified + crit    -> create a ``HumanTask`` (recorded on the state) ->
                              ``needs_supplement`` (surfaced, never faked).

    Idempotent on the state: a needs-supplement HumanTask for a claim already
    recorded (same ``requested_input``) is NOT re-created, so re-running across
    loop iterations does not mint duplicates.
    """
    claims, sources = _collect_claims_sources(state)
    source_texts = {sid: (s.excerpt or "") for sid, s in sources.items()}
    issue_of = _claim_issue_ids(state)
    existing_inputs = {t.requested_input for t in state.human_tasks.values()}

    res = RouteResult()
    for claim in claims:
        ok, repointed = cpolicy.flatten_to_primary(claim, sources)
        flat = claim.model_copy(update={"source_refs": repointed})
        result = cverify.verify_claim(flat, sources, source_texts)
        if result.verified:
            res.cited.append(claim)
            continue
        if not _claim_is_critical(state, claim, issue_of.get(id(claim))):
            res.dropped.append(claim)
            continue
        # unverified AND critical -> a HumanTask (supplement), surfaced not faked.
        if claim.claim in existing_inputs:
            # already recorded this run; still report it as needs_supplement.
            task = next(t for t in state.human_tasks.values()
                        if t.requested_input == claim.claim)
        else:
            tid = "HT-%03d" % (len(state.human_tasks) + 1)
            task = HumanTask(
                id=tid,
                task_title=f"補充驗證：{claim.claim}",
                owner=None,
                requested_input=claim.claim,
                why_needed=("決策關鍵主張無法以引用驗證（coverage < 0.85）；需人類補充"
                            "可驗證的資料或判斷，才能將其當作事實呈現。"),
                blocking_question=claim.claim,
                priority=5,
                can_continue_without_it=True,
                fallback_plan="先繼續其他分支；此項僅列於『不能說 / 需人類決策』，不當作事實。",
                status=HumanTaskStatus.open,
            )
            state.human_tasks[tid] = task
            existing_inputs.add(claim.claim)
        res.needs_supplement.append(task)
    return res


def assemble_memo(state: ResearchState, synthesizer) -> Memo:
    """Assemble the §22 memo: LLM prose + deterministic structure/labels.

    The only LLM call is ``synthesizer.write_sections`` (one structured call).
    Everything else — the 9-section SET, titles, blocker labels, challenge-status
    annotation — is pure Python. Does NOT set ``emitted`` (the gates do, Task 7).
    """
    prose = synthesizer.write_sections(state)
    blockers = label_blockers(state)

    # P5c confidence routing FIRST: cite / drop / needs-supplement (creates the
    # HumanTasks for unverified-critical claims). The unverified-critical claims
    # are surfaced (flagged) in the cannot-say / required-decisions sections —
    # never presented as fact — and the memo STILL emits (the loop never blocks).
    route = route_citations(state)
    needs_supplement = [t.requested_input for t in route.needs_supplement]

    # Component A: the findings answer LEADS. If the synthesizer returned no
    # findings prose (defensive), fall back to an honest N/A — never fabricated.
    findings_body = str(prose.get(FINDINGS_KEY, "") or "").strip()
    if not findings_body:
        findings_body = ("N/A（無可引用之證據，未臆測）。" if not state.evidence
                         else "（findings 缺失；請參考下方證據摘要。）")

    sections: list[MemoSection] = []
    for key in MEMO_ORDER:
        if key == FINDINGS_KEY:
            sections.append(MemoSection(key=key, title=SECTION_TITLES[key],
                                        body=findings_body))
            continue
        body = str(prose.get(key, "") or "").strip()
        if key == "blocking":
            labeled = _render_blockers(blockers)
            body = f"{body}\n\n{labeled}" if body else labeled
        elif key == "albert_challenge_map":
            statuses = _render_challenge_statuses(state)
            body = f"{body}\n\n{statuses}" if body else statuses
        elif key in ("can_cannot_say", "required_human_decisions") and needs_supplement:
            flagged = _render_needs_supplement(needs_supplement)
            body = f"{body}\n\n{flagged}" if body else flagged
        sections.append(MemoSection(
            key=key, title=SECTION_TITLES[key], body=body,
        ))

    # The citation CORRECTNESS gate (Task 7) still hard-blocks an unverified KEY
    # claim presented AS fact. P5c moves the unverified-CRITICAL claims to
    # needs_supplement (surfaced, not faked), so they are EXCLUDED here — the gate
    # no longer hard-blocks them; the honest cannot-say surfacing replaces the
    # block. A remaining unverified KEY claim (high-confidence web claim NOT
    # routed to supplement) still hard-blocks (it would otherwise be a lie).
    unverified_key = [c for c in citation_pass(state) if c not in needs_supplement]
    return Memo(sections=sections, blockers=blockers,
                unverified_key_claims=unverified_key,
                needs_supplement=needs_supplement)


def render_memo(memo: Memo) -> str:
    """Render the §22 memo to a Markdown string (the stored ``final_memo``)."""
    lines = ["# §22 Decision Memo"]
    if not memo.emitted and memo.refused_reason:
        lines.append(f"\n> ⚠ NOT EMITTED — {memo.refused_reason}\n")
    for s in memo.sections:
        lines.append(f"\n## {s.title}\n\n{s.body}")
    return "\n".join(lines)
