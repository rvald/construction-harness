from __future__ import annotations

from typing import Callable
from .providers.base import ProviderResponse, Provider

MAX_ITERATIONS = 20

def run(
    provider: Provider,
    tools: dict[str, Callable[..., str]],
    tool_schemas: list[dict],
    user_message: str,
) -> str:
    
    transcript: list[dict] = [{"role": "user", "content": user_message}]

    for _ in range(MAX_ITERATIONS):
        response = provider.complete(transcript, tool_schemas)

        if response.kind == "text":
            transcript.append({"role": "assistant", "content": response.text})
            return response.text or ""
        
        if response.kind == "tool_call":
            if response.tool_name is None:
                raise RuntimeError("tool_call response missing tool_name")
            if response.tool_name not in tools:
                raise RuntimeError(f"unknown tool_name: {response.tool_name!r}")
            
            tool_fn = tools[response.tool_name]
            result = tool_fn(**(response.tool_args or {}))

            transcript.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "name": response.tool_name, "id": response.tool_call_id, "input": response.tool_args}]
            })

            transcript.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": response.tool_call_id, "content": result}]
            })

            continue
        
        raise RuntimeError(f"unknown response kind: {response.kind!r}")
    
    raise RuntimeError(f"agent did not finish in {MAX_ITERATIONS} iterations")