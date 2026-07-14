from __future__ import annotations

import ast
from pathlib import Path

from .decorator import tool

import json

BASH_OUTPUT_LIMIT = 4000  # characters

@tool(side_effects={"read"})
def json_query(data: str, path: str) -> str:
    """Query JSON data with a simple dot-path expression.

    data: a JSON string (object or array).
    path: a dot-separated path; e.g. "items.0.name" or "user.email".
          Array indices are integers; object keys are dot-separated.

    Returns the queried value as JSON, or an error string if the path
    doesn't exist.
    Side effects: none.
    """
    obj = json.loads(data)  # will raise on invalid JSON; registry catches it
    current = obj
    for part in path.split("."):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            if part not in current:
                raise KeyError(f"path not found: {part}")
            current = current[part]
        else:
            raise TypeError(f"cannot index {type(current).__name__} with {part}")
    return json.dumps(current)

@tool(side_effects={"read"})
def calc(expression: str) -> str:
    """Evaluate a Python arithmetic expression.

    Accepts: +, -, *, /, **, parentheses, integer and float literals.
    Does NOT allow function calls, imports, attribute access, subscripts,
    comprehensions, names, or anything else not explicitly listed here.
    Side effects: none. Safe to retry.
    """
    ALLOWED = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
        ast.operator, ast.unaryop, ast.Load,
    )
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED):
            raise ValueError(f"forbidden in expression: {type(node).__name__}")
    return str(eval(compile(tree, "<expr>", mode="eval"),
                    {"__builtins__": {}}, {}))


@tool(side_effects={"read"})
def read_file(path: str) -> str:
    """Read a UTF-8 text file and return its contents.

    path: relative or absolute filesystem path.
    Side effects: reads the filesystem, no writes.
    Returns the file contents. For very large files, prefer chapter 11's
    viewport reader.
    """
    return Path(path).read_text(encoding="utf-8")


@tool(side_effects={"write"})
def write_file(path: str, content: str) -> str:
    """Overwrite a file with the given content.

    path: relative or absolute filesystem path. The file will be CREATED
    or OVERWRITTEN; its previous contents are lost.
    Side effects: writes to the filesystem. Not safe to call twice with
    different content expecting either version to survive.
    """
    Path(path).write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {path}"


@tool(side_effects={"read", "network"})
def bash(command: str, timeout_seconds: int = 30) -> str:
    """Run a shell command in the current working directory.

    command: a shell command line.
    timeout_seconds: hard time limit; default 30, cap 300.
    Side effects: MAY read/write files, MAY make network calls — depends on
    the command. Caller is responsible for the blast radius.
    Returns combined stdout+stderr with the exit code appended.
    """
    import subprocess
    timeout = min(int(timeout_seconds), 300)
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=timeout,
    )
    out = result.stdout
    err = result.stderr

    out_truncated = len(out) > BASH_OUTPUT_LIMIT
    err_truncated = len(err) > BASH_OUTPUT_LIMIT // 2
    if out_truncated:
        out = out[:BASH_OUTPUT_LIMIT] + f"\n...[truncated at {BASH_OUTPUT_LIMIT} chars]"
    if err_truncated:
        err = err[:BASH_OUTPUT_LIMIT // 2] + f"\n...[truncated]"

    note = ""
    if out_truncated or err_truncated:
        note = ("\n[note: output was truncated. For large output, "
                "pipe through `head`, `tail`, `grep`, or save to a file "
                "and use read_file_viewport.]")

    return (f"exit={result.returncode}\n"
            f"---stdout---\n{out}\n"
            f"---stderr---\n{err}"
            + note)
