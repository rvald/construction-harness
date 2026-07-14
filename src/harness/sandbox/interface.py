from typing import Protocol


class ToolSandbox(Protocol):
    async def execute(self, command: list[str], stdin: str = "",
                      timeout_seconds: int = 30,
                      cwd: str = "/workspace") -> tuple[int, str, str]:
        """Run a command in an isolated environment.

        Returns (exit_code, stdout, stderr).
        """
        ...
