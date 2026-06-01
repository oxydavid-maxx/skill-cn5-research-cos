"""Claude Agent SDK transport — thin, cheap-model, structured-JSON wrapper.

Mirrors the escape-mrc / Albert `sdk_client` pattern (retry/backoff, the
`StructuredOutput` tool-block contract), trimmed to exactly what P2a needs: one
synchronous `call_structured(system, user, schema)` that returns a
schema-validated dict.

Failure policy: this wrapper NEVER fabricates a fake result. When no key is
present or the SDK cannot produce structured output (after retries), it RAISES
`LLMUnavailableError` so the caller makes an explicit decision — it does not
emit a stub-shaped artifact.

Design contract (verified against escape-mrc's working client):
- Synchronous API; bridges to the async SDK via `asyncio.run`.
- env per call:
    CLAUDECODE=""               -> bypass nested-session rejection (SDK Issue #573)
    CLAUDE_SDK_CALL="1"         -> trigger superpowers SessionStart short-circuit
    CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK="1" -> skip per-spawn version HTTP round-trip
- setting_sources=None          -> no CLAUDE.md / auto-memory loading.
- output_format={"type":"json_schema","schema":schema}: Claude emits the schema
  data as a ToolUseBlock(name="StructuredOutput", input={...}) inside the
  AssistantMessage content (NOT on ResultMessage.structured_output).
- max_turns>=2 with a schema (tool_use + tool_result cycle).
- Key-gated: `has_api_key()` lets callers skip live tests cleanly without a key.

Cheap model by default (Haiku-tier) per the P2a fork decision F5.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

# --- Windows: patch anyio.open_process so SDK-spawned `claude` children don't
# open a console window (mirrors escape-mrc/Albert no_console.py). Applied at
# import, before any SDK call spawns a subprocess. ---
_CREATE_NO_WINDOW = 0x08000000
_ANYIO_PATCHED = False


def _patch_anyio_no_console() -> bool:
    global _ANYIO_PATCHED
    if _ANYIO_PATCHED or os.name != "nt":
        return _ANYIO_PATCHED
    try:
        import anyio
    except Exception:
        return False
    original = anyio.open_process
    if getattr(original, "_cn5_no_console", False):
        _ANYIO_PATCHED = True
        return True

    async def _open_process_no_console(*args: Any, **kwargs: Any):
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0) or 0) | _CREATE_NO_WINDOW
        return await original(*args, **kwargs)

    _open_process_no_console._cn5_no_console = True  # type: ignore[attr-defined]
    anyio.open_process = _open_process_no_console
    _ANYIO_PATCHED = True
    return True


_patch_anyio_no_console()

# Default cheap/Haiku-tier model for the clarification front-end.
DEFAULT_MODEL = os.environ.get("CN5_COS_LLM_MODEL", "haiku")

# Environment handed to every SDK call.
_SDK_ENV: dict[str, str] = {
    "CLAUDECODE": "",
    "CLAUDE_SDK_CALL": "1",
    "CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK": "1",
}


class LLMUnavailableError(RuntimeError):
    """Raised when the SDK cannot produce structured output (no key / transport)."""


def has_api_key() -> bool:
    """True iff an Anthropic credential is present.

    Used by key-gated tests to skip cleanly (never fail) when no key is set.
    """
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    )


async def _collect(msg_iter) -> dict[str, Any]:
    """Aggregate an SDK async message iterator into {text, structured, is_error}."""
    text_parts: list[str] = []
    structured: dict | None = None
    is_error = False
    async for msg in msg_iter:
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                t = getattr(block, "text", None)
                if t:
                    text_parts.append(t)
                if getattr(block, "name", None) == "StructuredOutput":
                    structured = getattr(block, "input", None)
        if hasattr(msg, "is_error"):
            is_error = bool(getattr(msg, "is_error", False))
    return {"text": "\n".join(text_parts), "structured": structured, "is_error": is_error}


async def _query_structured(
    *, system: str, user: str, schema: dict, model: str, timeout_sec: int,
    allowed_tools: list[str] | None = None, max_turns: int = 3,
) -> dict[str, Any]:
    from claude_agent_sdk import ClaudeAgentOptions, query  # imported lazily

    options = ClaudeAgentOptions(
        system_prompt=system.rstrip(),
        setting_sources=None,
        allowed_tools=list(allowed_tools or []),
        max_turns=max_turns,
        env=dict(_SDK_ENV),
        model=model,
        output_format={"type": "json_schema", "schema": schema},
        # Isolate from the ambient MCP config so a nested run (inside a Claude
        # Code session) does NOT inherit other MCP servers' tool schemas — one
        # of which uses oneOf/allOf/anyOf and 400s the whole tools array.
        # `--strict-mcp-config` + empty mcp_servers => use ONLY what we pass.
        mcp_servers={},
        extra_args={"strict-mcp-config": None},
    )

    async def _run():
        return await _collect(query(prompt=user, options=options))

    return await asyncio.wait_for(_run(), timeout=timeout_sec)


def _retrying(fn, attempts: int, base_wait: float, max_wait: float):
    """tenacity-backed retry for transport errors; deterministic errors propagate."""
    from tenacity import retry, stop_after_attempt, wait_exponential

    @retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(min=base_wait, max=max_wait),
        reraise=True,
    )
    def _wrapped(*a, **k):
        return fn(*a, **k)

    return _wrapped


def _call(
    *, system: str, user: str, schema: dict, model: str | None,
    timeout_sec: int, attempts: int,
    allowed_tools: list[str] | None, max_turns: int,
) -> dict[str, Any]:
    """Shared structured-call core (no-tool and with-tool paths funnel here).

    NO env-var auth gate (mirrors escape-mrc/Albert sdk_client): the Agent SDK
    spawns the `claude` CLI which authenticates via the Claude subscription /
    OAuth login — an ANTHROPIC_API_KEY is NOT required. If auth genuinely fails,
    the SDK call below errors and is wrapped in LLMUnavailableError. Never
    fabricates a result.
    """
    used_model = model or DEFAULT_MODEL

    def _once() -> dict[str, Any]:
        return asyncio.run(
            _query_structured(
                system=system, user=user, schema=schema,
                model=used_model, timeout_sec=timeout_sec,
                allowed_tools=allowed_tools, max_turns=max_turns,
            )
        )

    try:
        result = _retrying(_once, attempts, 3.0, 60.0)()
    except Exception as e:  # noqa: BLE001 - wrap transport/timeout failures
        raise LLMUnavailableError(f"SDK call failed: {type(e).__name__}: {e}") from e

    structured = result.get("structured")
    if structured is None:
        raise LLMUnavailableError(
            f"SDK schema call returned no structured output "
            f"(is_error={result.get('is_error')}, text_len={len(result.get('text', ''))})"
        )
    return structured


def call_structured(
    system: str,
    user: str,
    schema: dict,
    *,
    model: str | None = None,
    timeout_sec: int = 300,
    attempts: int = 5,
) -> dict[str, Any]:
    """Call Claude (cheap model) for ONE structured-JSON result (NO tools).

    Returns the schema-conformant dict from the StructuredOutput tool block.

    Raises:
        LLMUnavailableError -- no API key, or the SDK produced no structured
            output (after retries). The caller decides what to do; this function
            never returns a fabricated result.

    The narrow LLM node is the ONLY place the model lives; all loop/convergence/
    stop control stays deterministic in `cn5_ask`.
    """
    return _call(
        system=system, user=user, schema=schema, model=model,
        timeout_sec=timeout_sec, attempts=attempts,
        allowed_tools=None, max_turns=3,
    )


def call_structured_websearch(
    system: str,
    user: str,
    schema: dict,
    *,
    model: str | None = None,
    timeout_sec: int = 300,
    attempts: int = 5,
    max_turns: int = 4,
) -> dict[str, Any]:
    """Call Claude (cheap model) WITH the built-in WebSearch tool, then return ONE
    structured-JSON result.

    WebSearch is a *built-in* SDK tool (not MCP), so the P2a `--strict-mcp-config`
    + empty `mcp_servers` isolation does NOT block it (verified live in this env).
    A tool cycle (search -> read result -> emit StructuredOutput) needs several
    turns, hence `max_turns>=4`.

    Same failure policy as `call_structured`: raises `LLMUnavailableError` rather
    than fabricating when no structured output is produced.
    """
    if max_turns < 4:
        max_turns = 4
    return _call(
        system=system, user=user, schema=schema, model=model,
        timeout_sec=timeout_sec, attempts=attempts,
        allowed_tools=["WebSearch"], max_turns=max_turns,
    )
