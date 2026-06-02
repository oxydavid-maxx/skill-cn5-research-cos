"""Real cheap-LLM narrow brains (P2b).

Each brain is a NARROW LLM node: one job, a small in-file system prompt, a JSON
schema mirroring its target model's fields, returning a TYPED object. ALL
loop/convergence/stop/routing/COS-decision control stays DETERMINISTIC in the
graph (unchanged from P1); these nodes only emit structured data.

- RealIssueExpander : state -> list[IssueNode]   (LLM decompose; NO web grounding)
- RealResearcher    : (state, issue) -> EvidenceBundle  (ONE real WebSearch)
- RealSourceCritic  : EvidenceBundle -> annotated EvidenceBundle
- RealSkeptic       : (state, bundle) -> list[str]
- RealCompressor    : EvidenceBundle -> EvidenceBundle (light cited summary)
- RealScorer        : state -> ReadinessScore

Cheap `haiku` model everywhere (sdk_client default). No fabrication: the sdk
wrapper raises LLMUnavailableError rather than inventing output.
"""
from __future__ import annotations

from ..artifacts import issue_map
from ..llm import sdk_client
from ..models import (Claim, EvidenceBundle, IssueNode, IssueStatus, IssueType,
                      ReadinessScore, ResearchState, Source, SourceQuality,
                      SourceType)

_ISSUE_TYPES = [t.value for t in IssueType]
_SOURCE_TYPES = [t.value for t in SourceType]
_SOURCE_QUALITIES = [q.value for q in SourceQuality]


# --------------------------------------------------------------------------- #
# IssueExpander
# --------------------------------------------------------------------------- #
_ISSUE_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "issue_type": {"type": "string", "enum": _ISSUE_TYPES},
                    "impact": {"type": "integer", "minimum": 0, "maximum": 5},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 5},
                },
                "required": ["title", "description", "issue_type", "impact", "confidence"],
                "additionalProperties": False,
            },
            "minItems": 1,
        }
    },
    "required": ["issues"],
    "additionalProperties": False,
}

_ISSUE_SYSTEM = (
    "You decompose a research question into a SMALL set of distinct sub-issues a "
    "chief-of-staff must investigate before answering. One job: enumerate the "
    "issues. Cover intent, ROI/business value, risks/assumptions, and the root "
    "question. Do NOT browse the web. Return STRICT JSON per the schema."
)


class RealIssueExpander:
    def expand(self, state: ResearchState, now: str) -> list[IssueNode]:
        if state.issue_map:
            return []  # already expanded — no double-seed (mirrors stub)
        user = (
            f"RESEARCH QUESTION:\n{state.original_question}\n\n"
            f"BRIEF:\n{state.research_brief or '(none)'}\n\n"
            "Decompose into distinct sub-issues (each with a type, impact 0-5, "
            "confidence 0-5)."
        )
        raw = sdk_client.call_structured(_ISSUE_SYSTEM, user, _ISSUE_SCHEMA)
        created: list[IssueNode] = []
        for item in raw.get("issues", []):
            try:
                itype = IssueType(item["issue_type"])
            except ValueError:
                itype = IssueType.technical
            node = issue_map.add(
                state, title=item["title"], description=item.get("description", item["title"]),
                issue_type=itype, status=IssueStatus.open, now=now,
                impact=int(item.get("impact", 3)), confidence=int(item.get("confidence", 1)),
            )
            created.append(node)
        return created


# --------------------------------------------------------------------------- #
# Researcher (ONE real WebSearch)
# --------------------------------------------------------------------------- #
_RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "source_type": {"type": "string", "enum": _SOURCE_TYPES},
                    "quality": {"type": "string", "enum": _SOURCE_QUALITIES},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 5},
                    "source_indices": {"type": "array", "items": {"type": "integer"}},
                    "notes": {"type": "string"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
        },
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
        "coverage_gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sources", "claims"],
    "additionalProperties": False,
}

_RESEARCH_SYSTEM = (
    "You are a research worker. Use the WebSearch tool to run ONE focused search "
    "for the given sub-issue, then extract grounded claims and their sources from "
    "the results. One job: gather evidence for THIS issue only — do not fan out. "
    "Map each claim to the source(s) it came from via source_indices (0-based into "
    "your sources array). Return STRICT JSON per the schema."
)


class RealResearcher:
    def research(self, state: ResearchState, issue_id: str) -> EvidenceBundle:
        node = state.issue_map.get(issue_id)
        title = node.title if node else issue_id
        desc = node.description if node else ""
        user = (
            f"SUB-ISSUE:\n{title}\n{desc}\n\n"
            f"CONTEXT (original question): {state.original_question}\n\n"
            "Run ONE WebSearch for this sub-issue and return sources + grounded claims."
        )
        raw = sdk_client.call_structured_websearch(_RESEARCH_SYSTEM, user, _RESEARCH_SCHEMA)

        sources: list[Source] = []
        for i, s in enumerate(raw.get("sources", [])):
            try:
                stype = SourceType(s.get("source_type", "secondary"))
            except ValueError:
                stype = SourceType.secondary
            try:
                qual = SourceQuality(s.get("quality", "unknown"))
            except ValueError:
                qual = SourceQuality.unknown
            sources.append(Source(
                id=f"S-{issue_id}-{i}", title=s.get("title", "(untitled)"),
                url=s.get("url"), source_type=stype, quality=qual,
            ))

        claims: list[Claim] = []
        for c in raw.get("claims", []):
            refs = [
                sources[idx].id for idx in c.get("source_indices", [])
                if isinstance(idx, int) and 0 <= idx < len(sources)
            ]
            claims.append(Claim(
                claim=c["claim"], source_refs=refs,
                confidence=int(c.get("confidence", 0)), notes=c.get("notes", ""),
            ))

        return EvidenceBundle(
            query=title, issue_id=issue_id, claims=claims, sources=sources,
            missing_evidence=list(raw.get("missing_evidence", [])),
            coverage_gaps=list(raw.get("coverage_gaps", [])),
        )


# --------------------------------------------------------------------------- #
# SourceCritic
# --------------------------------------------------------------------------- #
_CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "quality": {"type": "string", "enum": _SOURCE_QUALITIES},
                    "source_type": {"type": "string", "enum": _SOURCE_TYPES},
                },
                "required": ["id", "quality"],
                "additionalProperties": False,
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 5},
                    "notes": {"type": "string"},
                },
                "required": ["index", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sources", "claims"],
    "additionalProperties": False,
}

_CRITIC_SYSTEM = (
    "You are a source critic. One job: judge the QUALITY of each source (primary/"
    "secondary/standard/marketing/internal; high/medium/low/unknown) and adjust "
    "each claim's confidence (0-5) to reflect source strength. Penalize marketing "
    "and unsourced claims. Return STRICT JSON per the schema."
)


class RealSourceCritic:
    def review(self, bundle: EvidenceBundle) -> EvidenceBundle:
        if not bundle.sources and not bundle.claims:
            return bundle
        srcs = "\n".join(
            f"{s.id}: {s.title} ({s.source_type.value}, {s.quality.value}) {s.url or ''}"
            for s in bundle.sources
        )
        clms = "\n".join(
            f"[{i}] {c.claim} (conf={c.confidence}, refs={c.source_refs})"
            for i, c in enumerate(bundle.claims)
        )
        user = f"SOURCES:\n{srcs}\n\nCLAIMS:\n{clms}\n\nAnnotate source quality + claim confidence."
        raw = sdk_client.call_structured(_CRITIC_SYSTEM, user, _CRITIC_SCHEMA)

        by_id = {s.id: s for s in bundle.sources}
        for s in raw.get("sources", []):
            tgt = by_id.get(s.get("id"))
            if tgt is None:
                continue
            try:
                tgt.quality = SourceQuality(s["quality"])
            except (ValueError, KeyError):
                pass
            if "source_type" in s:
                try:
                    tgt.source_type = SourceType(s["source_type"])
                except ValueError:
                    pass
        for c in raw.get("claims", []):
            idx = c.get("index")
            if isinstance(idx, int) and 0 <= idx < len(bundle.claims):
                bundle.claims[idx].confidence = int(c.get("confidence", bundle.claims[idx].confidence))
                if c.get("notes"):
                    bundle.claims[idx].notes = c["notes"]
        return bundle


# --------------------------------------------------------------------------- #
# Skeptic
# --------------------------------------------------------------------------- #
_SKEPTIC_SCHEMA = {
    "type": "object",
    "properties": {"counterarguments": {"type": "array", "items": {"type": "string"}}},
    "required": ["counterarguments"],
    "additionalProperties": False,
}

_SKEPTIC_SYSTEM = (
    "You are a skeptic / devil's advocate. One job: produce concise counterarguments "
    "and alternative explanations that would weaken the current evidence — biases, "
    "confounders, missing context, over-generalization. Return STRICT JSON per schema."
)


class RealSkeptic:
    def counter(self, state: ResearchState, bundle: EvidenceBundle) -> list[str]:
        clms = "\n".join(f"- {c.claim}" for c in bundle.claims) or "(no claims yet)"
        user = (
            f"QUESTION: {state.original_question}\n\n"
            f"EVIDENCE CLAIMS:\n{clms}\n\nList counterarguments."
        )
        raw = sdk_client.call_structured(_SKEPTIC_SYSTEM, user, _SKEPTIC_SCHEMA)
        return list(raw.get("counterarguments", []))


# --------------------------------------------------------------------------- #
# Compressor
# --------------------------------------------------------------------------- #
_COMPRESS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
    "additionalProperties": False,
}

_COMPRESS_SYSTEM = (
    "You compress an evidence bundle into a LIGHT cited summary. One job: a short "
    "summary that cites sources by their [S-...] ids, plus a few key points. Do not "
    "add new facts. Return STRICT JSON per schema."
)


class RealCompressor:
    def compress(self, bundle: EvidenceBundle) -> EvidenceBundle:
        srcs = ", ".join(s.id for s in bundle.sources) or "(none)"
        clms = "\n".join(f"- {c.claim} {c.source_refs}" for c in bundle.claims) or "(none)"
        user = f"SOURCES: {srcs}\n\nCLAIMS:\n{clms}\n\nWrite a light cited summary."
        raw = sdk_client.call_structured(_COMPRESS_SYSTEM, user, _COMPRESS_SCHEMA)
        summary = raw.get("summary", "").strip()
        if summary and summary not in bundle.suggested_followups:
            bundle.suggested_followups.append(summary)
        return bundle


# --------------------------------------------------------------------------- #
# Scorer
# --------------------------------------------------------------------------- #
_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "albert_challenge_readiness": {"type": "integer", "minimum": 0, "maximum": 5},
        "decision_readiness": {"type": "integer", "minimum": 0, "maximum": 5},
        "research_exhaustion_readiness": {"type": "integer", "minimum": 0, "maximum": 5},
        "human_bottleneck_clarity": {"type": "integer", "minimum": 0, "maximum": 5},
        "should_continue": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["albert_challenge_readiness", "decision_readiness",
                 "research_exhaustion_readiness", "human_bottleneck_clarity",
                 "should_continue", "reason"],
    "additionalProperties": False,
}

_SCORE_SYSTEM = (
    "You score research readiness on 4 axes (0-5): albert_challenge_readiness, "
    "decision_readiness, research_exhaustion_readiness, human_bottleneck_clarity. "
    "One job: assess readiness honestly and say whether to continue. Return STRICT "
    "JSON per schema. NOTE: the loop's stop/continue control is deterministic; this "
    "is an advisory signal only."
)


class RealScorer:
    def score(self, state: ResearchState) -> ReadinessScore:
        issues = "; ".join(
            f"{n.title}[{n.status.value} c={n.confidence}]"
            for n in list(state.issue_map.values())[:15]
        ) or "(none)"
        ev = len(state.evidence)
        user = (
            f"QUESTION: {state.original_question}\n\n"
            f"ISSUES: {issues}\n\nEVIDENCE BUNDLES: {ev}\n\nScore readiness."
        )
        raw = sdk_client.call_structured(_SCORE_SYSTEM, user, _SCORE_SCHEMA)
        return ReadinessScore(
            albert_challenge_readiness=int(raw["albert_challenge_readiness"]),
            decision_readiness=int(raw["decision_readiness"]),
            research_exhaustion_readiness=int(raw["research_exhaustion_readiness"]),
            human_bottleneck_clarity=int(raw["human_bottleneck_clarity"]),
            should_continue=bool(raw["should_continue"]),
            reason=raw.get("reason", ""),
        )
