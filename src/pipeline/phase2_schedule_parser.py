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

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"
_PAGE_INDEX = 37                       # 0-indexed -> PDF page 38
_EXPECTED_COLUMNS = 14

DOOR_MARK_RE = re.compile(r"^[NS][A-Z]?\d{2,}[A-Z]{0,2}$")   # N107B, N120CA, NE180B, S101
_MARK_TOKEN_RE = re.compile(r"[NS][A-Z]?\d{2,}[A-Z]{0,2}")   # same, for splitting merged cells

# Column index -> DoorEntry field (14 columns, verified against the sheet).
_COLUMNS = [
    "door_mark", "fire_rating_minutes", "width", "height",
    "door_elevation_type", "door_material", "door_finish",
    "frame_elevation_type", "frame_material", "frame_finish",
    "hardware_set", "glass_film", "glass_type", "special_notes",
]


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


def _expand_merged(row: list) -> list[list]:
    """Split a row that merged N identical doors ('N105A N105B N106A') into N rows.

    Each column's tokens divide evenly across the N doors; a column that doesn't
    divide evenly gives its value to the first door and blanks to the rest.
    Merged rows are the exception, not the rule.
    """
    n = len(_clean(row[0]).split())
    per_col: list[list[str]] = []
    for cell in row:
        toks = _clean(cell).split()
        if toks and len(toks) % n == 0:
            k = len(toks) // n
            per_col.append([" ".join(toks[i * k:(i + 1) * k]) for i in range(n)])
        else:
            per_col.append([_clean(cell)] + [""] * (n - 1))
    return [[per_col[c][r] for c in range(len(row))] for r in range(n)]


def _build_entry(row: list) -> DoorEntry:
    v = {field: _clean(row[i]) for i, field in enumerate(_COLUMNS)}
    mark = v["door_mark"]
    return DoorEntry(
        door_mark=mark,
        fire_rating_minutes=_fire_rating(row[1]),
        width=v["width"],
        height=v["height"],
        door_elevation_type=v["door_elevation_type"],
        door_material=v["door_material"],
        door_finish=v["door_finish"],
        frame_elevation_type=v["frame_elevation_type"] or None,
        frame_material=v["frame_material"],
        frame_finish=v["frame_finish"],
        hardware_set=v["hardware_set"],
        glass_film=v["glass_film"] or None,
        glass_type=v["glass_type"] or None,
        special_notes=v["special_notes"] or None,
        building={"N": "North", "S": "South"}.get(mark[0], ""),
    )


def parse_door_schedule(
    pdf_path: str | pathlib.Path = _DEFAULT_PDF,
    page_index: int = _PAGE_INDEX,
) -> list[DoorEntry]:
    """Parse the door schedule into DoorEntry records."""
    with pdfplumber.open(pdf_path) as pdf:
        tables = pdf.pages[page_index].extract_tables()

    table = _select_schedule_table(tables)
    if table is None:
        raise ValueError("Door schedule table (14 columns) not found on page.")

    entries: list[DoorEntry] = []
    for row in table:
        c0 = _clean(row[0])
        tokens = c0.split()
        if len(tokens) >= 2 and all(_MARK_TOKEN_RE.fullmatch(t) for t in tokens):
            rows = _expand_merged(row)            # merged identical doors
        elif DOOR_MARK_RE.match(c0):
            rows = [row]                          # normal single-door row
        else:
            continue                              # title / header / stray
        entries.extend(_build_entry(r) for r in rows)
    return entries


def extraction_confidence(entries: list[DoorEntry]) -> float:
    """Simple confidence score for the extraction (0..1).

    Blends: door marks matching the N/S grammar, count plausibility (~58 expected),
    and coverage of the core door/frame material fields.
    """
    if not entries:
        return 0.0
    valid_marks = sum(1 for e in entries if DOOR_MARK_RE.match(e.door_mark)) / len(entries)
    count_score = min(len(entries), 58) / 58
    filled = sum(1 for e in entries if e.door_material and e.frame_material) / len(entries)
    return round((valid_marks + count_score + filled) / 3, 3)


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
        if not t or len(t[0]) != 7:
            continue
        header = " ".join(_clean(c) for row in t[:3] for c in row).upper()
        if "ROOM FINISH SCHEDULE" not in header and not ("FLOOR" in header and "CEILING" in header):
            continue
        for row in t:
            room = _clean(row[0])
            if not ROOM_RE.match(room) or room in seen:
                continue
            seen.add(room)
            entries.append(FinishEntry(
                room_number=room,
                room_name=_clean(row[1]),
                floor_finish=_clean(row[2]),
                base_finish=_clean(row[3]),
                wall_finish=_clean(row[4]),
                ceiling_finish=_clean(row[5]),
                comments=_clean(row[6]) or None,
            ))
    return entries


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