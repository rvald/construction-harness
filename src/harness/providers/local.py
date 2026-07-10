from __future__ import annotations
from typing import Any

from .openai import OpenAIProvider

class LocalProvider(OpenAIProvider):
    name = "local"

    def __init__(self, model: str = "llama-3.1-8b-instruct",
                 base_url: str = "http://localhost:8000/v1",
                 api_key: str = "not-needed",
                 client: Any | None = None,
                 max_output_tokens: int = 4096) -> None:
        if client is None:
            from openai import AsyncOpenAI  # external SDK
            client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        super().__init__(model=model, client=client,
                         max_output_tokens=max_output_tokens)

