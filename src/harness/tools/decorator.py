from __future__ import annotations

import inspect
import typing
import asyncio
from typing import Callable, get_type_hints

from .base import SideEffect, Tool


def tool(
    name: str | None = None,
    description: str | None = None,
    side_effects: set[SideEffect] | frozenset[SideEffect] = frozenset(),
) -> Callable[[Callable[..., str]], Tool]:
    """Turn a plain function into a Tool.

    The input schema is inferred from type hints. The function's docstring
    is used as the description if not provided explicitly.
    """
    def wrap(fn: Callable[..., str]) -> Tool:
        actual_name = name or fn.__name__
        actual_description = description or (fn.__doc__ or "").strip()
        if not actual_description:
            raise ValueError(f"tool {actual_name!r} has no description")

        schema = _schema_from_signature(fn)

        return Tool(
            name=actual_name,
            description=actual_description,
            input_schema=schema,
            run=fn,
            side_effects=frozenset(side_effects),
        )
    return wrap


def _schema_from_signature(fn: Callable[..., str]) -> dict:
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        hint = hints.get(pname, str)
        properties[pname] = _type_to_schema(hint)
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _type_to_schema(t: type) -> dict:
    origin = typing.get_origin(t)
    if origin is typing.Union or origin is types_union():
        args = [a for a in typing.get_args(t) if a is not type(None)]
        if len(args) == 1:
            return _type_to_schema(args[0])
    if t is str:
        return {"type": "string"}
    if t is int:
        return {"type": "integer"}
    if t is float:
        return {"type": "number"}
    if t is bool:
        return {"type": "boolean"}
    if origin is list:
        return {"type": "array", "items": _type_to_schema(typing.get_args(t)[0])}
    return {"type": "string"}  # fallback


def types_union():
    import types
    return types.UnionType

def async_tool(name: str | None = None,
               description: str | None = None,
               side_effects: set[SideEffect] | frozenset[SideEffect] = frozenset()):
    def wrap(fn):
        actual_name = name or fn.__name__
        actual_description = description or (fn.__doc__ or "").strip()
        if not actual_description:
            raise ValueError(f"tool {actual_name!r}: description required")
        if not asyncio.iscoroutinefunction(fn):
            raise TypeError(f"@async_tool target must be `async def`: {actual_name}")
        return Tool(
            name=actual_name,
            description=actual_description,
            input_schema=_schema_from_signature(fn),   # from Chapter 4
            arun=fn,
            side_effects=frozenset(side_effects),
        )
    return wrap
