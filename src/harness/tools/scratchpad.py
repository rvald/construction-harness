from __future__ import annotations

from pathlib import Path

from .base import Tool
from .decorator import tool

SCRATCHPAD_PROMPT = """
You have access to a scratchpad — a durable key-value store that survives
the context window. Use it whenever you discover or decide something you
expect to need more than two turns later.

Examples of what to write to the scratchpad:
- Plans you commit to. If you decide on a 5-step approach, write it to
  "plan" immediately. Read it back when you're unsure of your next step.
- Findings from expensive tools. If you ran a 10-second database query,
  store the result in "query-result-1" so you don't have to re-run it.
- Constraints the user has expressed. "No changes to production" goes to
  "constraints" and stays there for the session.
- Decisions you don't want to revisit. "Using port 8081 because 8080 is
  taken" goes to "port-decision".

Call scratchpad_list() at the start of a session to see what's already
stored. Call scratchpad_read(key) to retrieve values you remember writing.
Call scratchpad_write(key, content) to persist. Use short keys:
"plan", "constraints", "query-result-1".

The scratchpad is durable. What you write here will be readable by future
sessions (including yourself, tomorrow). Treat it like a shared notebook.
"""


class Scratchpad:
    """Durable per-session key-value store, exposed to the agent as tools."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # simple key sanitization: allow alphanumerics, dash, underscore
        safe = "".join(c for c in key if c.isalnum() or c in "-_")
        if safe != key:
            raise ValueError(f"invalid key {key!r}: use [A-Za-z0-9_-]+")
        if not safe:
            raise ValueError("key cannot be empty")
        return self.root / f"{safe}.txt"

    def write(self, key: str, content: str) -> str:
        path = self._path(key)
        path.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} chars to scratchpad[{key}]"

    def read(self, key: str) -> str:
        path = self._path(key)
        if not path.exists():
            raise KeyError(f"scratchpad[{key}] not found")
        return path.read_text(encoding="utf-8")

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.txt"))

    def as_tools(self) -> list[Tool]:
        pad = self

        @tool(side_effects={"write"})
        def scratchpad_write(key: str, content: str) -> str:
            """Store a value in the scratchpad under the given key.

            key: alphanumeric, dashes, underscores only. No slashes, dots.
            content: any string; overwrites existing value for this key.
            Side effects: writes one file to the scratchpad directory.

            Use this for: plans, discovered facts, decisions that should
            survive the context window. Write once, read on demand.
            """
            return pad.write(key, content)

        @tool(side_effects={"read"})
        def scratchpad_read(key: str) -> str:
            """Retrieve a value from the scratchpad.

            key: the key used when writing.
            Returns the stored content, or an error if not found.
            Side effects: reads one file.
            """
            return pad.read(key)

        @tool(side_effects={"read"})
        def scratchpad_list() -> str:
            """List keys currently in the scratchpad.

            Returns a newline-separated list of keys.
            Side effects: reads the scratchpad directory.

            Use this at the start of a session to discover what prior
            agents (or you, in a past turn) have stored.
            """
            keys = pad.list()
            return "\n".join(keys) if keys else "(empty)"

        return [scratchpad_write, scratchpad_read, scratchpad_list]
