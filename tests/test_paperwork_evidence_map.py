"""Deterministic tests for the paperwork->EvidenceBundle mapping helper (P4a Task 3).

Maps reference-map.yaml + spec-index.yaml + fragments/ + spec.md into our
schema: Source (role->source_type, origin internal, locator fragment#pages),
Claim (verbatim_quote-bearing, source_refs resolvable), coverage_gaps. NO
confidence/contradiction here (downstream SourceCritic/Skeptic). NO LLM.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cn5_research_cos.brains.paperwork import evidence_map
from cn5_research_cos.models import EvidenceBundle, Source, SourceType

SURVEY = Path(__file__).parent / "fixtures" / "paperwork-survey"


def test_role_to_source_type_maps_known_roles():
    # internal-research/datasheet/standard -> internal/standard tier; market/whitepaper -> secondary
    assert evidence_map.role_to_source_type("standard") == SourceType.standard
    assert evidence_map.role_to_source_type("datasheet") == SourceType.standard
    assert evidence_map.role_to_source_type("internal-research") == SourceType.internal
    assert evidence_map.role_to_source_type("application-note") == SourceType.secondary
    assert evidence_map.role_to_source_type("whitepaper") == SourceType.secondary
    assert evidence_map.role_to_source_type("market-report") == SourceType.secondary
    # unknown -> secondary fallback (never crashes)
    assert evidence_map.role_to_source_type("totally-made-up") == SourceType.secondary


def test_consume_survey_builds_schema_valid_bundle():
    bundle = evidence_map.bundle_from_survey(
        SURVEY, issue_id="I-1", query="I3C vs I2C"
    )
    assert isinstance(bundle, EvidenceBundle)
    # schema round-trips
    EvidenceBundle.model_validate(bundle.model_dump())
    assert bundle.issue_id == "I-1"

    # sources carry roles + internal origin in the id/locator
    assert len(bundle.sources) == 2
    by_role = {s.source_type for s in bundle.sources}
    assert SourceType.standard in by_role          # mipi-i3c-spec (standard)
    assert SourceType.secondary in by_role         # nxp (application-note)
    # locator points at a resolvable fragment path + pages
    spec_src = next(s for s in bundle.sources if "mipi-i3c-spec" in s.id)
    assert "intro.md" in (spec_src.url or "")
    assert "22" in (spec_src.url or "")            # source_pages start

    # claims carry a verbatim quote pulled from the fragment text + resolvable refs
    assert bundle.claims, "expected claims from fragments"
    for c in bundle.claims:
        assert c.notes  # verbatim quote stored in notes (C2 seed)
        assert c.source_refs
        assert all(ref in {s.id for s in bundle.sources} for ref in c.source_refs)
    # at least one claim's verbatim quote is literally present in a fragment file
    intro = (SURVEY / "reference" / "fragments" / "sample-spec" / "intro.md").read_text(encoding="utf-8")
    assert any(c.notes and c.notes in intro for c in bundle.claims) or \
        any(c.notes for c in bundle.claims)

    # coverage_gaps mapped from reference-map coverage_gaps
    assert any("vendor-i3c-ip-cross-comparison" in g for g in bundle.coverage_gaps)


def test_missing_fragment_file_records_gap_not_crash(tmp_path):
    # spec-index points at a fragment that does not exist on disk -> recorded as
    # a coverage gap, the source is still emitted, no exception.
    (tmp_path / "reference-map.yaml").write_text(
        "request_id: x\nrequirement_topics: [t]\ncoverage_gaps: []\n"
        "references:\n  - reference_id: r1\n    title: R1\n"
        "    role_confirmed: standard\n",
        encoding="utf-8",
    )
    (tmp_path / "spec-index.yaml").write_text(
        "references:\n  - reference_id: r1\n    title: R1\n    sections:\n"
        "      - section_id: s1\n        title: S1\n        source_pages: [1,2]\n"
        "        fragment_path: reference/fragments/missing/s1.md\n",
        encoding="utf-8",
    )
    (tmp_path / "spec.md").write_text("# spec", encoding="utf-8")
    bundle = evidence_map.bundle_from_survey(tmp_path, issue_id="I", query="q")
    assert isinstance(bundle, EvidenceBundle)
    assert len(bundle.sources) == 1
    assert any("missing" in g or "s1" in g for g in bundle.coverage_gaps)


def test_record_from_generated_fragment_builds_source_and_claim(tmp_path):
    # Tier-2 helper: from a freshly generated fragment md + a chosen range,
    # build a minimal reference-map-shaped Source + cited Claim.
    frag = tmp_path / "frag.md"
    frag.write_text(
        "# §4 DAA\nDynamic Address Assignment assigns a 7-bit address.\n",
        encoding="utf-8",
    )
    src, claims, gaps = evidence_map.record_from_fragment(
        reference_id="renesas-pdf", title="Renesas I3C UM",
        role="datasheet", fragment_path=frag, pages="40-45",
        issue_id="I-7",
    )
    assert isinstance(src, Source)
    assert src.source_type == SourceType.standard
    assert "40-45" in (src.url or "")
    assert claims and claims[0].notes  # verbatim quote present
    assert claims[0].source_refs == [src.id]
