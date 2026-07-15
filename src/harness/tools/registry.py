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

    def __init__(
        self,
        tools: list[Tool] | None = None,
        permission_manager: "PermissionManager | None" = None,
        call_history: list[tuple[str, str]] | None = None,
    ) -> None:
        self.tools = {}
        # Run-scoped when the caller threads a list in — so cross-turn repeats
        # stay visible across the fresh registries the loop builds each turn;
        # otherwise per-registry, for standalone use.
        self._call_history = call_history if call_history is not None else []
        # A single manager is threaded in per turn so its session-approval
        # cache persists across the fresh registries the loop builds.
        self.permission_manager = permission_manager
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

        try:
            if tool.arun is not None:
                content = wrap_if_untrusted(tool, await tool.arun(**args))
            elif tool.run is not None:
                content = wrap_if_untrusted(tool, tool.run(**args))
            else:
                raise RuntimeError(f"tool {name!r} has no implementation")

        except Exception as e:
            return ToolResult(
                call_id=call_id,
                content=f"{name} raised {type(e).__name__}: {e}",
                is_error=True,
            )
        return ToolResult(call_id=call_id, content=content)
    


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
