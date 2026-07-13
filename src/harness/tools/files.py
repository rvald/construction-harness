from __future__ import annotations

from pathlib import Path

from .base import Tool
from .decorator import tool


VIEWPORT_DEFAULT = 100
VIEWPORT_MAX = 500


@tool(side_effects={"read"})
def read_file_viewport(path: str, offset: int = 0, limit: int = VIEWPORT_DEFAULT) -> str:
    """Read a slice of a text file, like `less` or `head -n ... | tail -n ...`.

    path: filesystem path.
    offset: zero-based line number to start reading from. Default 0.
    limit: max lines to return. Default 100, max 500.

    Returns a rendered viewport with line numbers. The last line of the
    output describes what's visible and what's NOT, so you can call this
    tool again with a different offset to keep reading.

    Side effects: reads the filesystem.

    Use this in preference to reading whole files. For files <50 lines,
    the whole file fits in one call.
    """
    limit = min(max(1, limit), VIEWPORT_MAX)
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file does not exist: {path}")
    if not p.is_file():
        raise IsADirectoryError(f"not a regular file: {path}")

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    start = max(0, offset)
    end = min(total, start + limit)
    visible = lines[start:end]

    width = len(str(total))
    numbered = [f"{i + 1:>{width}}  {line}" for i, line in enumerate(visible, start=start)]
    body = "\n".join(numbered)
    footer = (f"\n[file {path}; lines {start + 1}-{end} of {total}"
              + (f"; MORE below — call with offset={end}" if end < total else "; end of file")
              + (f"; MORE above — call with offset=0" if start > 0 else "")
              + "]")
    return body + footer


@tool(side_effects={"write"})
def edit_lines(
    path: str,
    start_line: int,
    end_line: int,
    replacement: str,
) -> str:
    """Replace a line range in a file with new content.

    path: filesystem path (file must exist).
    start_line: one-based starting line (inclusive).
    end_line: one-based ending line (inclusive).
    replacement: text to insert in place of the removed lines. Empty string
                 deletes the range without replacement. Include trailing
                 newlines if you want blank lines.

    Returns a confirmation with the diff summary and the lines around the
    edit (for verification).

    Side effects: writes the file. Preserves content outside the range.

    To INSERT new lines at position N without removing: use start_line=N,
    end_line=N-1 and replacement=your_new_content.
    To APPEND: use start_line=last+1, end_line=last.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file does not exist: {path}")

    original = p.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    total = len(lines)

    if start_line < 1 or start_line > total + 1:
        raise ValueError(f"start_line {start_line} out of range (1..{total + 1})")
    if end_line < start_line - 1 or end_line > total:
        raise ValueError(f"end_line {end_line} out of range ({start_line - 1}..{total})")

    # normalize: start is zero-based slice, end is zero-based exclusive
    s = start_line - 1
    e = end_line  # slice end is exclusive of end_line, so this works for deletes too

    replacement_lines = replacement.splitlines(keepends=True)
    if replacement and not replacement.endswith("\n"):
        # make sure we don't glue onto the next line without a newline
        if e < total:
            replacement_lines[-1] = replacement_lines[-1] + "\n"

    new_lines = lines[:s] + replacement_lines + lines[e:]
    p.write_text("".join(new_lines), encoding="utf-8")

    removed = end_line - start_line + 1 if end_line >= start_line else 0
    added = len(replacement_lines)

    # render context around the edit
    context_start = max(0, s - 2)
    context_end = min(len(new_lines), s + len(replacement_lines) + 2)
    preview = "".join(
        f"{i + 1:>5}  {new_lines[i]}" for i in range(context_start, context_end)
    )
    return (f"edited {path}: removed {removed} lines, "
            f"added {added} lines at {start_line}..{end_line}\n"
            f"context:\n{preview}")
