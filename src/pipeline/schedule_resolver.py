"""Header-driven schedule column resolver (Schedule Resolver, M1).

Maps a schedule table's columns to canonical fields by their HEADER LABELS instead
of fixed positions, so a reordered / renamed / extra column doesn't shift every
field. Multi-row grouped headers are handled by composing a group label
(DOOR/FRAME/SIZE) with an ambiguous sub-label (MATERIAL/FINISH/ELEVATION) into
door_material / frame_material / etc.

Validated against the real UCCS (14-col, ALL CAPS) and Pinney (16-col, mixed case,
'Door Schedule' title row, truncated cells) door schedules, and the UCCS finish
schedule. On UCCS the resolver reproduces the existing positional mapping exactly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def normalize(s: str | None) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


@dataclass
class ScheduleSchema:
    name: str
    fields: dict[str, list[str]]                 # canonical field -> normalized synonyms
    core_fields: list[str]                       # must resolve for a confident match
    group_tokens: set[str] = field(default_factory=set)
    ambiguous_labels: set[str] = field(default_factory=set)
    # --- quantity metadata (Tier 1 generic parser; defaults keep existing schemas inert) ---
    shape: str = "instance"                      # "instance" (row = one thing) | "catalog" (row = one type)
    row_key: str = ""                            # canonical field that keys a data row; "" -> first core field
    merge_rows: bool = False                     # row may pack N identical instances (door schedule)
    qty_field: str | None = None                 # canonical field holding an explicit quantity, if any
    qty_unit: str = "EA"                         # unit for row_count / qty_field quantities
    title_signature: tuple[str, ...] = ()        # lowercase substrings a page's text must all contain
                                                 # to be a parse candidate (page discovery, no constants)

    @property
    def key_field(self) -> str:
        return self.row_key or (self.core_fields[0] if self.core_fields else "")


# Canonical fields match the DoorEntry / FinishEntry model field names, so the
# header-driven parsers (M2/M5) reproduce the current positional output on UCCS.

DOOR_SCHEMA = ScheduleSchema(
    name="door",
    fields={
        "door_mark": ["number", "mark", "door number", "door no"],
        "fire_rating_minutes": ["fire rating", "fire rating minutes", "fire rating min", "rating"],
        "width": ["width"],
        "height": ["height"],
        "door_elevation_type": ["door elevation"],
        "door_material": ["door material"],
        "door_finish": ["door finish"],
        "frame_elevation_type": ["frame elevation"],
        "frame_material": ["frame material"],
        "frame_finish": ["frame finish"],
        "hardware_set": ["hardware set", "hardware", "hw set", "hw"],
        "glass_film": ["glass film", "film"],
        "glass_type": ["glass type", "glazing", "glass"],
        "special_notes": ["special notes and comments", "special notes", "notes", "comments", "remarks"],
        "location": ["location", "room"],
    },
    core_fields=["door_mark", "width", "height", "door_material"],
    group_tokens={"door", "frame", "size"},
    ambiguous_labels={"material", "finish", "elevation"},
    shape="instance",
    row_key="door_mark",
    merge_rows=True,                             # door rows can pack N identical doors
    title_signature=("door", "schedule"),
)

FINISH_SCHEMA = ScheduleSchema(
    name="finish",
    fields={
        "room_number": ["number", "room number", "room no", "room"],
        "room_name": ["name", "room name"],
        "floor_finish": ["floor", "flooring"],
        "base_finish": ["base"],
        "wall_finish": ["wall", "walls"],
        "ceiling_finish": ["ceiling"],
        "comments": ["special notes and comments", "special notes", "notes", "comments", "remarks"],
    },
    core_fields=["room_number", "floor_finish", "base_finish", "wall_finish", "ceiling_finish"],
    shape="instance",
    row_key="room_number",
    title_signature=("finish", "schedule"),
)

# A window schedule is keyed by a mark/type (one row = one window type), so it is a
# CATALOG: it carries size + glazing areas per type, but the count of each type lives
# on the elevations/plans (left as unknown_plan_count). Validated on Pinney (composite
# window schedule: MARK, TYPE, SIZE, DAYLIGHT AREA (S.F.), VENTILATION AREA, NOTES).
WINDOW_SCHEMA = ScheduleSchema(
    name="window",
    fields={
        "mark": ["mark", "window mark", "window", "type mark"],
        "window_type": ["type", "window type"],
        "size": ["size", "size width x height", "dimensions"],
        "daylight_area": ["daylight area", "glass area", "glazing area"],
        "ventilation_area": ["ventilation area", "vent area", "operable area"],
        "notes": ["notes", "remarks", "comments"],
    },
    core_fields=["mark", "window_type", "size"],
    shape="catalog",
    row_key="mark",
    title_signature=("window", "schedule"),
)

# A plumbing fixture schedule is a catalog: one row per fixture TAG (WC-1, L-1, ...)
# giving description + spec (manufacturer/model), but no instance count — that lives
# on the plumbing plans. `qty_field` is declared so that a schedule variant which DOES
# carry a real QUANTITY column yields basis "qty_column"; UCCS's does not, so its
# fixtures resolve as unknown_plan_count. Validated on UCCS (p59).
PLUMBING_FIXTURE_SCHEMA = ScheduleSchema(
    name="plumbing_fixture",
    fields={
        "fixture_tag": ["fixture tag", "tag", "mark", "fixture"],
        "description": ["description", "fixture description"],
        "fixture_type": ["type"],
        "manufacturer": ["manufacturer", "mfr", "manufacture"],
        "model": ["model", "model no", "model number"],
        "quantity": ["quantity", "qty", "count"],
        "remarks": ["plumbing remarks", "remarks", "notes", "comments"],
    },
    core_fields=["fixture_tag", "description"],
    shape="catalog",
    row_key="fixture_tag",
    qty_field="quantity",
    title_signature=("plumbing", "fixture"),
)


@dataclass
class ColumnMap:
    schema: str
    mapping: dict[int, str]              # column index -> canonical field
    data_start: int                      # first data row (rows above are header/title)
    coverage: float                      # fraction of core_fields resolved
    unmapped_columns: list[int]

    @property
    def by_field(self) -> dict[str, int]:
        return {f: c for c, f in self.mapping.items()}

    def field_at(self, col: int) -> str | None:
        return self.mapping.get(col)


def _match(label: str, schema: ScheduleSchema) -> str | None:
    """Match a normalized label to a canonical field: exact synonym, then
    prefix/containment (tolerates truncation and minor wording variation)."""
    if not label:
        return None
    for fld, syns in schema.fields.items():
        if label in syns:
            return fld
    for fld, syns in schema.fields.items():
        for syn in syns:
            if len(label) >= 3 and (label.startswith(syn) or syn.startswith(label)):
                return fld
    return None


def _is_title(cells: list[str]) -> bool:
    nonempty = [c for c in cells if c]
    return len(nonempty) <= 1 or all("schedule" in c for c in nonempty)


def _row_is_header(cells: list[str], htoks: set[str], min_hits: int = 2) -> bool:
    """A header row carries several known tokens; require >= min_hits so a stray
    data row that happens to contain one header-ish word doesn't extend the band."""
    hits = 0
    for c in cells:
        if len(c) < 2:
            continue
        if any(c == t or c.startswith(t) or t.startswith(c) for t in htoks):
            hits += 1
            if hits >= min_hits:
                return True
    return False


def _header_tokens(schema: ScheduleSchema) -> set[str]:
    toks: set[str] = set()
    for syns in schema.fields.values():
        toks |= set(syns)
    return toks | schema.group_tokens | schema.ambiguous_labels


def _nearest_group(norm: list[list[str]], band: list[int], primary_row: int,
                   col: int, group_tokens: set[str]) -> str | None:
    """Nearest group token at column <= col in a header row above primary_row."""
    for r in (r for r in band if r < primary_row):
        for cc in range(min(col, len(norm[r]) - 1), -1, -1):
            if norm[r][cc] in group_tokens:
                return norm[r][cc]
    return None


def resolve_columns(table: list[list], schema: ScheduleSchema) -> ColumnMap:
    """Resolve a schedule table's columns to canonical fields by header label."""
    norm = [[normalize(c) for c in row] for row in table]
    htoks = _header_tokens(schema)

    band: list[int] = []
    data_start = len(table)
    for i, cells in enumerate(norm):
        if _is_title(cells):
            continue                                  # skip title, keep scanning
        if _row_is_header(cells, htoks):
            band.append(i)
        else:
            data_start = i
            break

    ncols = max((len(r) for r in table), default=0)
    mapping: dict[int, str] = {}
    unmapped: list[int] = []
    for c in range(ncols):
        primary, primary_row = "", None
        for r in band:
            cell = norm[r][c] if c < len(norm[r]) else ""
            if cell:
                primary, primary_row = cell, r
        if not primary:
            continue
        if primary in schema.ambiguous_labels:
            group = _nearest_group(norm, band, primary_row, c, schema.group_tokens)
            label = f"{group} {primary}" if group else primary
        else:
            label = primary
        fld = _match(label, schema)
        if fld and fld not in mapping.values():        # first column to claim a field wins
            mapping[c] = fld
        else:
            unmapped.append(c)

    resolved_core = sum(1 for f in schema.core_fields if f in mapping.values())
    coverage = resolved_core / len(schema.core_fields) if schema.core_fields else 0.0
    return ColumnMap(schema.name, mapping, data_start, round(coverage, 3), unmapped)


def select_schedule_table(
    tables: list[list[list]], schema: ScheduleSchema,
    min_coverage: float = 0.75, min_cols: int = 6,
) -> list[list] | None:
    """Pick the table on a page that best resolves to `schema` by header coverage.

    Replaces the old exactly-N-columns + literal-anchor test: order/count-agnostic,
    so a differently-shaped schedule from another firm is still selected. Ties break
    toward the table with more rows (the real schedule, not a stray fragment)."""
    best: list[list] | None = None
    best_key = (min_coverage - 1e-9, -1)
    for t in tables:
        if not t or len(t[0]) < min_cols:
            continue
        cov = resolve_columns(t, schema).coverage
        key = (cov, len(t))
        if cov >= min_coverage and key > best_key:
            best, best_key = t, key
    return best


if __name__ == "__main__":
    import pdfplumber
    from src.pipeline.phase2_schedule_parser import _select_schedule_table

    with pdfplumber.open("data/uccs/drawings.pdf") as pdf:
        t = _select_schedule_table(pdf.pages[37].extract_tables())
    cm = resolve_columns(t, DOOR_SCHEMA)
    print(f"UCCS door: data_start={cm.data_start} coverage={cm.coverage}")
    for c in sorted(cm.mapping):
        print(f"  col {c:>2} -> {cm.mapping[c]}")
