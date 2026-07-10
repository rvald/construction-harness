import os
import sys
import json
import asyncio

from src.harness.providers.anthropic import AnthropicProvider
from src.harness.providers.openai import OpenAIProvider
from src.harness.providers.local import LocalProvider

from src.harness.agent import arun
from src.harness.messages import Transcript, ToolCall, ToolResult
from src.harness.providers.events import TextDelta
from src.harness.tools.registry import ToolRegistry
from src.harness.tools.std import  calc, bash

# Choose the provider once. The rest of the script doesn't care which one.
provider_name = os.environ.get("PROVIDER", "openai")
required_env = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "local": None,  # local servers don't need a key
}
env_var = required_env.get(provider_name)
if env_var and not os.environ.get(env_var):
    sys.exit(
        f"error: PROVIDER={provider_name} requires {env_var}. "
        f"Set it and re-run. For the local provider, use PROVIDER=local."
    )

provider = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "local": LocalProvider,
}[provider_name]()


async def main():
    provider = OpenAIProvider()
    registry = ToolRegistry(tools=[calc, bash])

    def on_event(event):
        if isinstance(event, TextDelta):
            print(event.text, end="", flush=True)

    def on_tool_call(call: ToolCall) -> None:
        args = json.dumps(call.args, ensure_ascii=False)
        # 2-space indent so the call nests visually under the assistant text.
        print(f"\n  ⚙ {call.name}({args})", flush=True)

    def on_tool_result(result: ToolResult) -> None:
        marker = "✗" if result.is_error else "→"
        preview = result.content.strip().replace("\n", " ⏎ ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        print(f"  {marker} {preview}\n", flush=True)

    # One transcript, reused across every turn. This is the whole feature.
    transcript = Transcript(system="You are a helpful, concise assistant.")

    prompts = [
        "My favourite number is 42. Remember it.",
        "What's my favourite number times seven? Use the calculator.",
        "Now divide the number I first mentioned by two.",
    ]

    for prompt in prompts:
        print(f"\n\nUser: {prompt}\nAssistant: ", end="", flush=True)
        await arun(
            provider, registry, prompt,
            transcript=transcript,
            on_event=on_event,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )

    print(f"\n\n[session ended — {len(transcript.messages)} messages in transcript]")

asyncio.run(main())