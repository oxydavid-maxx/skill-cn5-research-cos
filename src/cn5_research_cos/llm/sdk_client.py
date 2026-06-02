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

Prompt caching (P2 acceleration Task 4): the installed claude-agent-sdk (0.1.63)
exposes `ClaudeAgentOptions.system_prompt` as `str | SystemPromptPreset |
SystemPromptFile | None` — there is NO structured content-block array on which an
explicit Anthropic `cache_control:{type:ephemeral}` marker can be attached (that
is a raw Messages-API construct the SDK hides behind the `claude` CLI). The CLI
caches the system prompt automatically; the application's only obligation for a
cache-hit is to keep each brain's large static system prompt BYTE-IDENTICAL
across calls. We satisfy that by keeping every brain system prompt a module-level
constant (see brains/real.py + albert/simulator.py) — never rebuilt per call —
and lock it with tests/test_prompt_caching.py. So explicit cache_control is not
applicable to this SDK shape; byte-identical constants are how caching is applied.
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


# Module-level handles for the SDK client/options classes. They are bound lazily
# (on first session use) from claude_agent_sdk so importing this module never
# requires the SDK installed, AND so deterministic tests can monkeypatch
# `sdk_client.ClaudeSDKClient` with a fake. None until first `_load_sdk()`.
ClaudeSDKClient: Any = None
ClaudeAgentOptions: Any = None


def _load_sdk() -> None:
    """Bind ClaudeSDKClient / ClaudeAgentOptions from the SDK if not already set
    (a test monkeypatch sets them first, so we never clobber a fake)."""
    global ClaudeSDKClient, ClaudeAgentOptions
    if ClaudeSDKClient is None or ClaudeAgentOptions is None:
        from claude_agent_sdk import ClaudeAgentOptions as _O
        from claude_agent_sdk import ClaudeSDKClient as _C
        if ClaudeSDKClient is None:
            ClaudeSDKClient = _C
        if ClaudeAgentOptions is None:
            ClaudeAgentOptions = _O


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
    """Aggregate an SDK async message iterator into a result dict.

    Keys: text, structured, is_error, and — for cost/latency instrumentation —
    cost_usd (ResultMessage.total_cost_usd) + usage (ResultMessage.usage).
    """
    text_parts: list[str] = []
    structured: dict | None = None
    is_error = False
    cost_usd: float | None = None
    usage: dict = {}
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
        c = getattr(msg, "total_cost_usd", None)
        if c is not None:
            cost_usd = float(c)
        u = getattr(msg, "usage", None)
        if isinstance(u, dict) and u:
            usage = u
    return {
        "text": "\n".join(text_parts),
        "structured": structured,
        "is_error": is_error,
        "cost_usd": cost_usd,
        "usage": usage,
    }


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


# --------------------------------------------------------------------------- #
# Persistent session (P2 acceleration) — port of escape-mrc's ClaudeSession
# --------------------------------------------------------------------------- #
async def _session_turn(client, user: str, timeout_sec: int) -> dict[str, Any]:
    """Run ONE turn on an already-connected ClaudeSDKClient and aggregate it."""
    async def _run():
        await client.query(user)
        return await _collect(client.receive_response())

    return await asyncio.wait_for(_run(), timeout=timeout_sec)


class ClaudeSession:
    """Persistent ``ClaudeSDKClient``: connect ONE `claude` subprocess, run many
    turns. (Mirrors skill-ai-escape-mrc's ClaudeSession, adapted to our P2a
    isolation args + `_collect` + cost/latency metrics.)

    Root cause this solves: the one-shot ``query()`` transport spawns a fresh
    `claude` CLI per call, paying ~12s session-startup EVERY call. Our brains
    issue several structured calls per loop iteration, so per-call spawn
    dominates wall-clock. Routing them through ONE persistent session pays
    startup once and cuts spawns.

    Same isolation as the one-shot path: ``setting_sources=None``,
    ``mcp_servers={}`` + ``extra_args={"strict-mcp-config": None}`` (so a nested
    run does not inherit ambient MCP tool schemas), ``env=_SDK_ENV``, and the
    Windows no-console anyio patch (applied at import).

    Usage::

        with ClaudeSession(system=SYS, schema=SCHEMA) as s:
            r1 = s.ask(user1, brain="expander")   # pays startup
            r2 = s.ask(user2, brain="scorer")     # reuses the live client

    ``ask()`` returns the schema dict (from the StructuredOutput tool block) when
    a schema was given, else the text string. On a transport error it reconnects
    a dead session and retries (up to ``max_attempts``); it raises
    ``LLMUnavailableError`` rather than fabricating when no structured output is
    produced. Threads an optional ``RunMetrics`` for cost/latency.
    """

    def __init__(
        self,
        *,
        system: str,
        model: str | None = None,
        schema: dict | None = None,
        allowed_tools: list[str] | None = None,
        timeout_sec: int = 300,
        max_attempts: int = 5,
        max_turns: int | None = None,
        metrics: Any = None,
        backoff_base: float = 3.0,
    ) -> None:
        self._system = system.rstrip()
        self._model = model or DEFAULT_MODEL
        self._schema = schema
        self._allowed_tools = list(allowed_tools or [])
        self._timeout = timeout_sec
        self._max_attempts = max_attempts
        # Default turn budget: a schema needs a tool_use + tool_result cycle;
        # WebSearch needs a few more. Matches the one-shot path's defaults.
        if max_turns is not None:
            self._max_turns = max_turns
        elif self._allowed_tools:
            self._max_turns = 4
        else:
            self._max_turns = 3
        self._metrics = metrics
        self._backoff_base = backoff_base
        self._loop: Any = None
        self._client: Any = None

    def _build_options(self):
        _load_sdk()
        return ClaudeAgentOptions(
            system_prompt=self._system,
            setting_sources=None,
            allowed_tools=list(self._allowed_tools),
            max_turns=self._max_turns,
            env=dict(_SDK_ENV),
            model=self._model,
            output_format=(
                {"type": "json_schema", "schema": self._schema}
                if self._schema is not None else None
            ),
            mcp_servers={},
            extra_args={"strict-mcp-config": None},
        )

    def _connect(self) -> None:
        _load_sdk()
        self._client = ClaudeSDKClient(options=self._build_options())
        self._loop.run_until_complete(self._client.connect())

    def _disconnect(self) -> None:
        if self._client is not None:
            try:
                self._loop.run_until_complete(self._client.disconnect())
            except Exception:
                pass
            self._client = None

    def __enter__(self) -> "ClaudeSession":
        self._loop = asyncio.new_event_loop()
        try:
            self._connect()
        except Exception as e:  # noqa: BLE001
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None
            raise LLMUnavailableError(
                f"ClaudeSession connect failed: {type(e).__name__}: {e}"
            ) from e
        return self

    def __exit__(self, *exc) -> None:
        self._disconnect()
        try:
            if self._loop is not None:
                self._loop.close()
        except Exception:
            pass
        self._loop = None

    def ask(self, user: str, *, schema: dict | None = None, brain: str = "unknown"):
        """Run one turn on the live client. ``schema`` overrides the session's
        default schema for this turn (used when one session serves brains with
        different schemas). Returns the structured dict (or text when no schema).
        """
        import time as _time

        effective_schema = schema if schema is not None else self._schema
        last_exc: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            t0 = _time.monotonic()
            try:
                result = self._loop.run_until_complete(
                    _session_turn(self._client, user, self._timeout)
                )
            except Exception as exc:  # noqa: BLE001 - transport/process error
                last_exc = exc
                if attempt < self._max_attempts:
                    wait = min(60.0, self._backoff_base * (2 ** (attempt - 1)))
                    if wait > 0:
                        _time.sleep(wait)
                    # reconnect a (possibly dead) session before retrying
                    self._disconnect()
                    try:
                        self._connect()
                    except Exception:
                        pass
                continue

            wall = _time.monotonic() - t0
            if self._metrics is not None:
                self._metrics.record(
                    cost_usd=result.get("cost_usd"), wall_s=wall,
                    brain=brain, usage=result.get("usage"),
                )

            if effective_schema is not None:
                structured = result.get("structured")
                if structured is None:
                    raise LLMUnavailableError(
                        f"SDK session turn returned no structured output "
                        f"(is_error={result.get('is_error')}, "
                        f"text_len={len(result.get('text', ''))})"
                    )
                return structured
            text = result.get("text", "")
            if not text:
                raise LLMUnavailableError(
                    f"SDK session turn returned empty text (brain={brain})"
                )
            return text

        raise LLMUnavailableError(
            f"SDK session turn failed after {self._max_attempts} attempts "
            f"(brain={brain}): {type(last_exc).__name__ if last_exc else 'unknown'}: "
            f"{last_exc}"
        )
