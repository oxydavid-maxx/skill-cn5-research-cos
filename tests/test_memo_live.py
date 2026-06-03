"""Live opt-in §22 memo end-to-end test (CN5_COS_LLM_TESTS=1). Skips cleanly
without the opt-in.

Proves the full P5 path on REAL LLMs: a short real run reaches readiness (or an
explicit emit command), the synthesize seam assembles the §22 memo (9 sections, a
non-empty Albert Challenge Map, cited evidence), the four emission gates run, and
the memo emits.

Do NOT run this yourself in the build harness — the controller runs the long live
test after implementation returns. Without the opt-in it is skipped.
"""
from __future__ import annotations

import os

import pytest

from cn5_research_cos.brains import build_brains
from cn5_research_cos.graph import run_auto
from cn5_research_cos.synthesis.gates import check_emission
from cn5_research_cos.synthesis.memo import NINE_SECTION_KEYS, assemble_memo
from cn5_research_cos.models import ResearchState


@pytest.mark.llm
def test_real_run_emits_section22_memo(tmp_path):
    if os.environ.get("CN5_COS_LLM_TESTS") != "1":
        pytest.skip("set CN5_COS_LLM_TESTS=1 to run live LLM tests")

    rs = ResearchState(
        run_id="live-memo",
        original_question="Should our BU build an autonomous overnight research agent?",
    )
    result = run_auto(rs, base_dir=tmp_path, max_iterations=3, now="t0", llm="real")
    final = result["state"]

    assert final.iteration_count >= 1
    assert final.last_audit is not None

    # Assemble + gate the §22 memo on the REAL synthesizer (explicit emit so a short
    # run that has not hit the readiness target still produces the memo for review).
    synth = build_brains(llm="real").synthesizer
    memo = assemble_memo(final, synth)
    check_emission(final, memo, explicit=True)

    # 9 §22 sections, in order.
    assert memo.section_keys() == NINE_SECTION_KEYS
    assert len(memo.sections) == 9
    # every section has prose.
    for s in memo.sections:
        assert s.body.strip(), f"section {s.key} is empty"
    # a non-empty Albert Challenge Map section.
    alb = next(s for s in memo.sections if s.key == "albert_challenge_map")
    assert alb.body.strip()
    # the memo emitted (degraded-audit / convergence / citation gates passed; the
    # readiness gate honored the explicit command).
    assert memo.emitted is True, f"refused: {memo.refused_reason}"
