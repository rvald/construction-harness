"""Phase 2e — Door Schedule parser (Milestone 7).

Parses the door and interior opening schedule on drawings page 38 (sheet A9.3.1)
into DoorEntry records. This is the anchor for the Door N107B end-to-end trace.

Findings from exploration:
  * Page 38 is rotated 90 degrees and the schedule is a ruled grid. Despite that,
    pdfplumber's extract_tables() locks onto it cleanly: among many noise tables,
    exactly one is 14 columns wide (the schedule's 14 columns).
  * Header spans two rows (group header 'SIZE/DOOR/FRAME' then sub-headers); data
    rows begin after, each keyed by a door mark like 'N107B' in column 0.
  * 58 data rows -> matches the spec's ~58 ground truth.

Door mark grammar: building prefix (N=North, S=South) + room number + optional
letter suffix, e.g. N107B.
"""
from __future__ import annotations

import pathlib
import re

import pdfplumber

from src.models.schedule import DoorEntry, FinishEntry
from src.pipeline.schedule_resolver import (
    DOOR_SCHEMA, FINISH_SCHEMA, ColumnMap, resolve_columns, select_schedule_table,
)

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"
_PAGE_INDEX = 37                       # 0-indexed -> PDF page 38
_EXPECTED_COLUMNS = 14

DOOR_MARK_RE = re.compile(r"^[NS][A-Z]?\d{2,}[A-Z]{0,2}$")   # N107B, N120CA, NE180B, S101
_MARK_TOKEN_RE = re.compile(r"[NS][A-Z]?\d{2,}[A-Z]{0,2}")   # same, for splitting merged cells

# Columns are resolved by header label (schedule_resolver), not by fixed index.


def _clean(cell: str | None) -> str:
    return re.sub(r"\s*\n\s*", " ", (cell or "").strip())


def _fire_rating(cell: str | None) -> int | None:
    m = re.search(r"\d+", cell or "")
    return int(m.group()) if m else None


def _select_schedule_table(tables: list[list[list]]) -> list[list] | None:
    """Pick the 14-column table whose header names the door schedule columns."""
    for t in tables:
        if not t or len(t[0]) != _EXPECTED_COLUMNS:
            continue
        header_blob = " ".join(_clean(c) for row in t[:3] for c in row).upper()
        if "FIRE RATING" in header_blob and "HARDWARE SET" in header_blob:
            return t
    return None


def _expand_merged(row: list, mark_col: int = 0) -> list[list]:
    """Split a row that merged N identical doors ('N105A N105B N106A') into N rows.

    Each column's tokens divide evenly across the N doors; a column that doesn't
    divide evenly gives its value to the first door and blanks to the rest.
    Merged rows are the exception, not the rule.
    """
    n = len(_clean(row[mark_col]).split())
    per_col: list[list[str]] = []
    for cell in row:
        toks = _clean(cell).split()
        if toks and len(toks) % n == 0:
            k = len(toks) // n
            per_col.append([" ".join(toks[i * k:(i + 1) * k]) for i in range(n)])
        else:
            per_col.append([_clean(cell)] + [""] * (n - 1))
    return [[per_col[c][r] for c in range(len(row))] for r in range(n)]


def _build_entry(row: list, cm: ColumnMap) -> DoorEntry:
    """Build a DoorEntry using the resolved column map (field -> column index)."""
    def get(field: str) -> str:
        c = cm.by_field.get(field)
        return _clean(row[c]) if (c is not None and c < len(row)) else ""

    mark = get("door_mark")
    frc = cm.by_field.get("fire_rating_minutes")
    fire = _fire_rating(row[frc]) if (frc is not None and frc < len(row)) else None
    return DoorEntry(
        door_mark=mark,
        fire_rating_minutes=fire,
        width=get("width"),
        height=get("height"),
        door_elevation_type=get("door_elevation_type"),
        door_material=get("door_material"),
        door_finish=get("door_finish"),
        frame_elevation_type=get("frame_elevation_type") or None,
        frame_material=get("frame_material"),
        frame_finish=get("frame_finish"),
        hardware_set=get("hardware_set"),
        glass_film=get("glass_film") or None,
        glass_type=get("glass_type") or None,
        special_notes=get("special_notes") or None,
        building={"N": "North", "S": "South"}.get(mark[0], "") if mark else "",
    )


_MIN_BUILTIN_MARKS = 5                              # trust [NS] convention if it clearly applies
_DISCOVER_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _looks_like_mark(cell: str) -> bool:
    """Firm-agnostic door-mark shape: a short single alnum token containing a digit
    (e.g. 'B01w', '101w', 'N101A'). Rejects multi-word section headers like
    'BASEMENT - EAST' and dimension strings."""
    return (2 <= len(cell) <= 8
            and _DISCOVER_TOKEN_RE.fullmatch(cell) is not None
            and any(ch.isdigit() for ch in cell))


def _select_door_rows(table: list[list], mark_col: int, is_mark, is_token) -> list[list]:
    out: list[list] = []
    for row in table:
        c0 = _clean(row[mark_col]) if mark_col < len(row) else ""
        tokens = c0.split()
        if len(tokens) >= 2 and all(is_token(t) for t in tokens):
            out.extend(_expand_merged(row, mark_col))   # merged identical doors
        elif c0 and is_mark(c0):
            out.append(row)                             # single-door row
    return out


def _select_door_rows_auto(table: list[list], mark_col: int) -> list[list]:
    """Select data rows by mark grammar. The built-in [NS] convention is tried
    first (keeps UCCS identical); if it barely matches, a discovered grammar takes
    over for other firms' mark schemes."""
    builtin = _select_door_rows(
        table, mark_col,
        lambda s: bool(DOOR_MARK_RE.match(s)),
        lambda s: bool(_MARK_TOKEN_RE.fullmatch(s)),
    )
    if len(builtin) >= _MIN_BUILTIN_MARKS:
        return builtin
    return _select_door_rows(table, mark_col, _looks_like_mark, _looks_like_mark)


def parse_door_schedule(
    pdf_path: str | pathlib.Path = _DEFAULT_PDF,
    page_index: int = _PAGE_INDEX,
) -> list[DoorEntry]:
    """Parse the door schedule into DoorEntry records."""
    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[page_index].extract_tables()

    table = select_schedule_table(tables, DOOR_SCHEMA)
    if table is None:
        raise ValueError("No door schedule table (by header coverage) found on page.")

    cm = resolve_columns(table, DOOR_SCHEMA)
    mark_col = cm.by_field.get("door_mark", 0)
    rows = _select_door_rows_auto(table, mark_col)
    return [_build_entry(r, cm) for r in rows]


def extraction_confidence(entries: list[DoorEntry]) -> float:
    """Intrinsic confidence for the extraction (0..1) — no answer-key count term.

    Blends: door marks matching the mark grammar, and coverage of the core
    door/frame material fields. (Dropped the old `/58` UCCS-count term, C10.)
    """
    if not entries:
        return 0.0
    valid_marks = sum(1 for e in entries if DOOR_MARK_RE.match(e.door_mark)) / len(entries)
    filled = sum(1 for e in entries if e.door_material and e.frame_material) / len(entries)
    return round((valid_marks + filled) / 2, 3)


# ---------------------------------------------------------------------------
# Phase 2f — room finish schedule + applied finish list (Milestone 8)
# ---------------------------------------------------------------------------

_FINISH_PAGE_INDEX = 48                 # 0-indexed -> PDF page 49 (AF2.4)
ROOM_RE = re.compile(r"^[NS]\d{3}[A-Z]?$")
_FINISH_CODE_ANCHOR = re.compile(r"\b([A-Z]{1,4}-\d+[A-Z]?)\s+TYPE:")


def parse_finish_schedule(
    pdf_path: str | pathlib.Path = _DEFAULT_PDF,
    page_index: int = _FINISH_PAGE_INDEX,
) -> list[FinishEntry]:
    """Parse the room finish schedule into FinishEntry records.

    The schedule renders as two 7-column tables (its two room columns on the sheet).
    Columns: NUMBER, NAME, FLOOR, BASE, WALL, CEILING, SPECIAL NOTES.
    """
    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[page_index].extract_tables()

    seen: set[str] = set()
    entries: list[FinishEntry] = []
    for t in tables:
        if not t or len(t[0]) < 6:
            continue
        cm = resolve_columns(t, FINISH_SCHEMA)
        if cm.coverage < 0.75:                      # not a room-finish table
            continue
        room_col = cm.by_field.get("room_number", 0)
        for row in _select_finish_rows_auto(t, room_col):
            room = _clean(row[room_col]) if room_col < len(row) else ""
            if room in seen:
                continue
            seen.add(room)
            entries.append(_build_finish_entry(row, cm))
    return entries


def _build_finish_entry(row: list, cm: ColumnMap) -> FinishEntry:
    def get(field: str) -> str:
        c = cm.by_field.get(field)
        return _clean(row[c]) if (c is not None and c < len(row)) else ""

    return FinishEntry(
        room_number=get("room_number"),
        room_name=get("room_name"),
        floor_finish=get("floor_finish"),
        base_finish=get("base_finish"),
        wall_finish=get("wall_finish"),
        ceiling_finish=get("ceiling_finish"),
        comments=get("comments") or None,
    )


def _select_finish_rows(table: list[list], room_col: int, is_room) -> list[list]:
    return [row for row in table
            if room_col < len(row) and is_room(_clean(row[room_col]))]


def _select_finish_rows_auto(table: list[list], room_col: int) -> list[list]:
    """Built-in [NS] room grammar first (keeps UCCS identical), discovered grammar
    as fallback for other firms' room numbering."""
    builtin = _select_finish_rows(table, room_col, lambda s: bool(ROOM_RE.match(s)))
    if len(builtin) >= _MIN_BUILTIN_MARKS:
        return builtin
    return _select_finish_rows(table, room_col, _looks_like_mark)


def parse_applied_finish_list(
    pdf_path: str | pathlib.Path = _DEFAULT_PDF,
    page_index: int = _FINISH_PAGE_INDEX,
    room_region_top: float = 1620,
) -> dict[str, str]:
    """Parse the applied finish list (upper portion) into {code: definition}.

    Codes are delimited by the pattern 'CODE TYPE:'; each definition runs to the
    next such anchor.
    """
    with pdfplumber.open(pdf_path) as pdf:
        words = [w for w in pdf.pages[page_index].extract_words(keep_blank_chars=False)
                 if w["top"] < room_region_top]
    text = " ".join(w["text"] for w in sorted(words, key=lambda w: (round(w["top"] / 8), w["x0"])))

    anchors = list(_FINISH_CODE_ANCHOR.finditer(text))
    applied: dict[str, str] = {}
    for i, m in enumerate(anchors):
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
        applied.setdefault(m.group(1), text[m.start():end].strip())
    return applied


if __name__ == "__main__":
    doors = parse_door_schedule()
    print(f"door entries : {len(doors)}")
    print(f"confidence   : {extraction_confidence(doors)}")
    print(f"all N/S marks: {all(DOOR_MARK_RE.match(d.door_mark) for d in doors)}")
    for d in doors:
        if d.door_mark in ("N101A", "N107B"):
            print(f"  {d.door_mark}: {d.width} x {d.height} | door {d.door_material}/{d.door_finish} "
                  f"| frame {d.frame_material}/{d.frame_finish} | HW {d.hardware_set} | glass {d.glass_type}")