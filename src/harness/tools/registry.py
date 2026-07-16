from __future__ import annotations

from dataclasses import dataclass, field
import asyncio

from ..permissions.manager import PermissionManager
from ..permissions.trust import wrap_if_untrusted

from ..messages import MALFORMED_ARGS_KEY, ToolResult
from .base import Tool
from .validation import validate, ValidationError

MAX_REPEAT_CALLS = 3


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)
    _call_history: list[tuple[str, str]] = field(default_factory=list, init=False)
    permission_manager: "PermissionManager | None" = None
    write_gate: "asyncio.Lock | None" = None

    def __init__(
        self,
        tools: list[Tool] | None = None,
        permission_manager: "PermissionManager | None" = None,
        call_history: list[tuple[str, str]] | None = None,
        write_gate: "asyncio.Lock | None" = None,
    ) -> None:
        self.tools = {}
        # Run-scoped when the caller threads a list in — so cross-turn repeats
        # stay visible across the fresh registries the loop builds each turn;
        # otherwise per-registry, for standalone use.
        self._call_history = call_history if call_history is not None else []
        # A single manager is threaded in per turn so its session-approval
        # cache persists across the fresh registries the loop builds.
        self.permission_manager = permission_manager
        # Optional mutual-exclusion gate for mutating tools. Threaded in — and
        # SHARED — across the sibling sub-agents of one parallel batch, so their
        # write/mutate calls can't interleave at an await point. None (the
        # default) for a single agent, whose dispatch is already serial.
        self.write_gate = write_gate
        for t in tools or []:
            self.add(t)

    def add(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self.tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [t.schema_for_provider() for t in self.tools.values()]

    async def dispatch(self, name: str, args: dict, call_id: str) -> ToolResult:
        if name not in self.tools:
            return self._unknown_tool(name, call_id)

        # Before schema validation: if the provider couldn't parse the args as
        # JSON it stashed the raw buffer here. Catch it now so the model gets a
        # parse-specific message — and so the sentinel never reaches the tool
        # body as a stray kwarg.
        if MALFORMED_ARGS_KEY in args:
            return self._malformed_args(name, args[MALFORMED_ARGS_KEY], call_id)

        tool = self.tools[name]
        errors = validate(args, tool.input_schema)
        if errors:
            return self._validation_failure(name, errors, call_id)
        
        if self.permission_manager is not None:
            outcome = await self.permission_manager.check(tool, args)
            if outcome.decision == "deny":
                return ToolResult(
                    call_id=call_id,
                    content=f"{name}: permission denied — {outcome.reason}",
                    is_error=True,
                )

        self._record(name, args)
        loop_result = self._check_loop(name, args, call_id)
        if loop_result is not None:
            return loop_result

        # Serialize mutating tools against their siblings when a shared write
        # gate is present (parallel sub-agents). Read-only tools never take the
        # gate, so concurrent reads still overlap — this is codex's read/write
        # split (a full RwLock there) reduced to what a single-threaded event
        # loop needs. A gated registry never holds spawn tools (the spawner
        # strips them), so a gated call can't itself spawn and re-enter → no
        # nested acquisition, no deadlock.
        #
        # Fail CLOSED on the label: a call takes the gate unless it is provably
        # pure-read (side_effects ⊆ {"read"} and non-empty). An empty/omitted
        # effect set is "unknown" → gated, not waved through. This keeps the
        # guarantee from resting on a positive write/mutate label that a tool
        # might under-declare — e.g. `bash`, which can write the filesystem —
        # while pure reads still overlap. (network-labelled tools also gate;
        # the only concurrency that survives today is pure-{read} local calls.)
        read_only = bool(tool.side_effects) and tool.side_effects <= {"read"}
        mutates = not read_only
        try:
            if self.write_gate is not None and mutates:
                async with self.write_gate:
                    content = await self._invoke(tool, args)
            else:
                content = await self._invoke(tool, args)

        except Exception as e:
            # The exception *message* is data from the same (possibly untrusted)
            # source as the tool's return value — fence it exactly as we fence a
            # successful return, or a network/MCP tool could smuggle instructions
            # into the trusted channel via its error text. The harness-generated
            # prefix stays outside the fence as a trusted, provider-independent
            # error signal; wrap_if_untrusted no-ops for non-network tools, so
            # trusted tools' messages are unchanged.
            return ToolResult(
                call_id=call_id,
                content=(
                    f"{name} raised {type(e).__name__}: "
                    + wrap_if_untrusted(tool, str(e))
                ),
                is_error=True,
            )
        return ToolResult(call_id=call_id, content=content)

    async def _invoke(self, tool: Tool, args: dict) -> str:
        """Call the tool's implementation and fence its (possibly untrusted)
        return value. Sync or async; exactly one is present (Tool.__post_init__)."""
        if tool.arun is not None:
            return wrap_if_untrusted(tool, await tool.arun(**args))
        if tool.run is not None:
            return wrap_if_untrusted(tool, tool.run(**args))
        raise RuntimeError(f"tool {tool.name!r} has no implementation")



    def _unknown_tool(self, name: str, call_id: str) -> ToolResult:
        # Try to suggest a close match. We drop difflib's default cutoff
        # of 0.6 to 0.5 — the ratio for `calculator` vs `calc` is ~0.57,
        # and prefix-heavy misspellings like that are exactly the case
        # we want to catch. 0.5 still rejects unrelated names.
        import difflib
        close = difflib.get_close_matches(
            name, list(self.tools.keys()), n=1, cutoff=0.5,
        )
        suggestion = f" Did you mean {close[0]!r}?" if close else ""
        return ToolResult(
            call_id=call_id,
            content=(
                f"unknown tool: {name!r}.{suggestion} "
                f"Available: {sorted(self.tools.keys())}"
            ),
            is_error=True,
        )

    def _malformed_args(self, name: str, raw: str, call_id: str) -> ToolResult:
        # The model's tool-call arguments were not valid JSON (often a truncated
        # or unquoted value). Tell it exactly that, so it re-emits the call
        # rather than "fixing" a field it never got wrong. The preview is the
        # model's own current-turn output echoed back — no new content, capped.
        preview = raw if len(raw) <= 200 else raw[:200] + "…"
        return ToolResult(
            call_id=call_id,
            content=(
                f"{name}: arguments were not valid JSON and could not be parsed. "
                f"Re-issue the call with a single well-formed JSON object. "
                f"Received: {preview!r}"
            ),
            is_error=True,
        )

    def _validation_failure(
        self, name: str, errors: list[ValidationError], call_id: str
    ) -> ToolResult:
        summary = "; ".join(str(e) for e in errors)
        return ToolResult(
            call_id=call_id,
            content=f"{name}: invalid arguments. {summary}",
            is_error=True,
        )

    def _record(self, name: str, args: dict) -> None:
        import json
        self._call_history.append((name, json.dumps(args, sort_keys=True)))
        if len(self._call_history) > 100:
            # In-place: a threaded (run-scoped) history must stay the same list
            # object, or rebinding would silently detach it from the caller.
            self._call_history[:] = self._call_history[-100:]

    def _check_loop(self, name: str, args: dict, call_id: str) -> ToolResult | None:
        import json
        key = (name, json.dumps(args, sort_keys=True))
        repeats = sum(1 for k in self._call_history[-MAX_REPEAT_CALLS:] if k == key)
        if repeats >= MAX_REPEAT_CALLS:
            return ToolResult(
                call_id=call_id,
                content=(
                    f"tool-call loop detected: {name} called with identical "
                    f"arguments {MAX_REPEAT_CALLS} times in a row. "
                    "Try a different approach or different arguments, or "
                    "stop and return your current best answer."
                ),
                is_error=True,
            )
        return None
