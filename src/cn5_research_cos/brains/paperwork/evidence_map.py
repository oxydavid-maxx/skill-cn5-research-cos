"""Map paperwork artifacts -> our EvidenceBundle schema (deterministic, no LLM).

Two entry points:

* ``bundle_from_survey(folder, ...)`` — TIER 1 consume: read an existing
  paperwork survey folder (``reference-map.yaml`` + ``spec-index.yaml`` +
  ``fragments/`` + ``spec.md``) and assemble a full ``EvidenceBundle``.
* ``record_from_fragment(...)`` — TIER 2 generate: from one freshly generated
  fragment markdown + the chosen page range, build a minimal reference-map-shaped
  ``Source`` + cited ``Claim``(s).

Mapping rules (spec §"EvidenceBundle mapping"):
  Source.source_type  <- reference-map role enum (see ROLE_MAP)
  Source.url          <- locator "fragment_path#pages" (origin = internal)
  Claim.notes         <- verbatim quote pulled from the fragment text (C2 seed)
  Claim.source_refs   <- the owning Source id (resolvable)
  coverage_gaps       <- reference-map coverage_gaps (tier 1) / missing fragments

Confidence / contradiction are NOT set here — the downstream RealSourceCritic /
RealSkeptic derive them. We only PRESERVE the verbatim quote paperwork carries;
the ≥0.85 fuzzy enforcement + flatten-to-primary is P4b.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ...models import Claim, EvidenceBundle, Source, SourceType

# reference-map role enum -> our SourceType.
# standard / datasheet are authoritative primary-ish technical refs -> standard.
# internal-research -> internal. application-note / whitepaper / market-report
# are secondary-tier commentary -> secondary. Unknown roles fall back to secondary.
ROLE_MAP: dict[str, SourceType] = {
    "standard": SourceType.standard,
    "datasheet": SourceType.standard,
    "internal-research": SourceType.internal,
    "application-note": SourceType.secondary,
    "whitepaper": SourceType.secondary,
    "market-report": SourceType.secondary,
}

# How many leading sentences of a fragment to keep as the verbatim quote seed.
_QUOTE_MAX_CHARS = 280


def role_to_source_type(role: str | None) -> SourceType:
    """Map a reference-map role enum value to our SourceType (secondary fallback)."""
    if not role:
        return SourceType.secondary
    return ROLE_MAP.get(str(role).strip().lower(), SourceType.secondary)


def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _pages_label(source_pages) -> str:
    """Render a compact pages label from a spec-index ``source_pages`` list."""
    if not source_pages:
        return ""
    nums = [int(p) for p in source_pages if isinstance(p, int)]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    return str(lo) if lo == hi else f"{lo}-{hi}"


def _verbatim_quote(fragment_text: str) -> str:
    """Pull a short verbatim quote from a fragment (first prose, headers skipped)."""
    for raw in fragment_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        return line[:_QUOTE_MAX_CHARS].strip()
    return fragment_text.strip()[:_QUOTE_MAX_CHARS]


def _coverage_gaps_from_map(ref_map: dict) -> list[str]:
    gaps: list[str] = []
    for g in ref_map.get("coverage_gaps") or []:
        if isinstance(g, dict):
            topic = g.get("topic", "")
            note = (g.get("note") or "").strip().replace("\n", " ")
            gaps.append(f"{topic}: {note}".strip(": ").strip() or topic or str(g))
        elif g:
            gaps.append(str(g))
    return gaps


def _role_by_reference_id(ref_map: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for ref in ref_map.get("references") or []:
        if not isinstance(ref, dict):
            continue
        rid = ref.get("reference_id")
        if rid:
            out[str(rid)] = ref.get("role_confirmed") or ref.get("role_proposed") or ""
    return out


def bundle_from_survey(folder: Path | str, *, issue_id: str | None,
                       query: str) -> EvidenceBundle:
    """TIER 1: assemble an EvidenceBundle from an existing paperwork survey folder.

    Reads ``reference-map.yaml`` (roles + coverage_gaps), ``spec-index.yaml``
    (per-fragment source_pages + fragment_path), and the fragment markdown files
    (verbatim quotes). A fragment file that is referenced but absent on disk is
    recorded as a coverage gap (the Source is still emitted).
    """
    folder = Path(folder)
    ref_map = _load_yaml(folder / "reference-map.yaml")
    spec_index = _load_yaml(folder / "spec-index.yaml")

    role_by_id = _role_by_reference_id(ref_map)
    sources: list[Source] = []
    claims: list[Claim] = []
    coverage_gaps: list[str] = _coverage_gaps_from_map(ref_map)

    for ref in spec_index.get("references") or []:
        if not isinstance(ref, dict):
            continue
        rid = str(ref.get("reference_id", "ref"))
        title = ref.get("title", rid)
        role = role_by_id.get(rid, ref.get("role_confirmed") or ref.get("role_proposed"))
        stype = role_to_source_type(role)
        for sec in ref.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            sec_id = str(sec.get("section_id", "sec"))
            frag_rel = sec.get("fragment_path", "")
            pages = _pages_label(sec.get("source_pages"))
            locator = f"{frag_rel}#{pages}" if pages else frag_rel
            src = Source(
                id=f"S-{issue_id or 'INT'}-{rid}-{sec_id}",
                title=f"{title} — {sec.get('title', sec_id)}",
                url=locator,
                source_type=stype,
            )
            sources.append(src)

            frag_path = folder / frag_rel if frag_rel else None
            if frag_path is not None and frag_path.is_file():
                quote = _verbatim_quote(frag_path.read_text(encoding="utf-8"))
                if quote:
                    claims.append(Claim(
                        claim=f"{sec.get('title', sec_id)} ({title})",
                        source_refs=[src.id], notes=quote,
                    ))
            else:
                coverage_gaps.append(
                    f"fragment missing on disk: {frag_rel or sec_id} "
                    f"(ref {rid})"
                )

    return EvidenceBundle(
        query=query, issue_id=issue_id, claims=claims, sources=sources,
        coverage_gaps=coverage_gaps,
    )


def record_from_fragment(*, reference_id: str, title: str, role: str,
                         fragment_path: Path | str, pages: str,
                         issue_id: str | None) -> tuple[Source, list[Claim], list[str]]:
    """TIER 2: build a minimal reference-map-shaped Source + cited Claim from a
    freshly generated fragment markdown.

    Returns ``(source, claims, coverage_gaps)``. ``coverage_gaps`` is non-empty
    only when the fragment file is missing/empty.
    """
    frag = Path(fragment_path)
    rel = frag.name
    locator = f"{rel}#{pages}" if pages else rel
    src = Source(
        id=f"S-{issue_id or 'INT'}-{reference_id}",
        title=title,
        url=locator,
        source_type=role_to_source_type(role),
    )
    claims: list[Claim] = []
    gaps: list[str] = []
    if frag.is_file():
        text = frag.read_text(encoding="utf-8")
        quote = _verbatim_quote(text)
        if quote:
            claims.append(Claim(
                claim=f"{title} (pages {pages})",
                source_refs=[src.id], notes=quote,
            ))
        else:
            gaps.append(f"empty fragment for {reference_id} pages {pages}")
    else:
        gaps.append(f"fragment not produced for {reference_id} pages {pages}")
    return src, claims, gaps
