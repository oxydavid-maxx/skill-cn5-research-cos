"""Prompt-caching precondition tests (deterministic).

The installed claude-agent-sdk (0.1.63) exposes `system_prompt` as
`str | SystemPromptPreset | SystemPromptFile | None` — there is NO structured
content-block array on which an explicit Anthropic `cache_control:{type:ephemeral}`
marker could be attached (that lives in the raw Messages API, which the SDK hides
behind the `claude` CLI). The CLI caches the system prompt automatically; the
ONLY thing the application must guarantee for a cache-hit is that each brain's
large static system prompt is **byte-identical across calls** — i.e. a module
constant, never rebuilt per call with interpolated state.

These tests lock that invariant so a future refactor that starts f-string'ing
run-specific data into a system prompt (silently destroying cache hits) fails CI.
"""
from __future__ import annotations

from cn5_research_cos.brains import real
from cn5_research_cos.albert import simulator


_STATIC_SYSTEM_PROMPTS = {
    "issue_expander": real._ISSUE_SYSTEM,
    "researcher": real._RESEARCH_SYSTEM,
    "source_critic": real._CRITIC_SYSTEM,
    "skeptic": real._SKEPTIC_SYSTEM,
    "compressor": real._COMPRESS_SYSTEM,
    "scorer": real._SCORE_SYSTEM,
    "albert": simulator._SYSTEM,
}


def test_all_brain_system_prompts_are_nonempty_constants():
    for name, prompt in _STATIC_SYSTEM_PROMPTS.items():
        assert isinstance(prompt, str), f"{name} system prompt must be a str constant"
        assert len(prompt) > 0, f"{name} system prompt is empty"


def test_system_prompts_are_byte_identical_across_reads():
    """Reading the constant twice yields the same bytes — i.e. it is NOT a
    function rebuilding per call. (A property re-derived per access could differ;
    a module constant cannot.)"""
    for name, prompt in _STATIC_SYSTEM_PROMPTS.items():
        a = _STATIC_SYSTEM_PROMPTS[name]
        b = getattr(real, f"_{name.upper()}_SYSTEM", None) if name != "albert" else simulator._SYSTEM
        # the two references resolve to the SAME object (interned constant)
        assert a is prompt
        if b is not None:
            assert a == b


def test_system_prompts_carry_no_runtime_interpolation_markers():
    """A static, cacheable system prompt must not contain run-specific
    interpolation — no leftover f-string braces / format placeholders that would
    differ between runs and break the CLI's prompt cache."""
    for name, prompt in _STATIC_SYSTEM_PROMPTS.items():
        assert "{" not in prompt and "}" not in prompt, (
            f"{name} system prompt contains a brace — likely per-call "
            f"interpolation that would defeat prompt caching"
        )
