"""Tier 1 — schema-driven quantity extraction from schedules.

One generic parser turns any resolved schedule table into uniform `ScheduleItem`
records, so downstream (WBS / pricing) treats every schedule alike. It reuses the
header-driven column resolver and the existing, firm-agnostic row selectors — the
new part is quantity assignment + the uniform record, not new table logic.

Quantity, by schedule shape:
  * instance (door, finish, ...) -> each row is one thing: quantity 1, basis
    "row_count"; the aggregate count is len(items).
  * catalog (fixtures, ...)      -> each row is one TYPE. If the schedule carries an
    explicit quantity column, use it (basis "qty_column"); otherwise the count lives
    on the drawings and is left explicit-unknown (basis "unknown_plan_count").

Door/finish DoorEntry/FinishEntry parsers are untouched (they feed the golden graph);
this is an additive, parallel path proven row-for-row equal to them (see tests).
"""
from __future__ import annotations

import re

from src.models.schedule import ScheduleItem
from src.pipeline.phase2_schedule_parser import (
    _clean, _select_door_rows_auto, _select_finish_rows_auto,
)
from src.pipeline.schedule_resolver import ColumnMap, ScheduleSchema, resolve_columns

# A catalog/type tag: a single mark letter (window "A") or a coded tag with a digit
# ("WC-1", "L1", "GPO-2"). Requiring a digit for multi-letter tags rejects header
# words like "TYPE"/"NAME" that are otherwise short all-caps tokens.
_CATALOG_TAG_RE = re.compile(r"^[A-Z]$|^[A-Z]{1,4}-?\d+[A-Z]?$")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

# unknown -> deferred to plan counting (Tier 3)
BASIS_ROW_COUNT = "row_count"
BASIS_QTY_COLUMN = "qty_column"
BASIS_UNKNOWN = "unknown_plan_count"


def _num(cell: str) -> float | None:
    m = _NUM_RE.search(cell or "")
    return float(m.group()) if m else None


def _looks_like_tag(cell: str) -> bool:
    return bool(_CATALOG_TAG_RE.match(cell.strip()))


def _select_catalog_rows(table: list[list], key_col: int) -> list[list]:
    """Rows whose key column is a catalog tag and that carry real data (>=2 cells)."""
    out: list[list] = []
    seen: set[str] = set()
    for row in table:
        key = _clean(row[key_col]) if key_col < len(row) else ""
        if not _looks_like_tag(key) or key in seen:
            continue
        if sum(1 for c in row if _clean(c)) < 2:            # header/stray fragment
            continue
        seen.add(key)
        out.append(row)
    return out


def select_rows(table: list[list], cm: ColumnMap, schema: ScheduleSchema) -> list[list]:
    """Pick data rows using the row selector appropriate to the schedule's shape."""
    key_col = cm.by_field.get(schema.key_field, 0)
    if schema.shape == "catalog":
        return _select_catalog_rows(table, key_col)
    if schema.merge_rows:                                    # instance, may pack N (doors)
        return _select_door_rows_auto(table, key_col)
    return _select_finish_rows_auto(table, key_col)          # instance, one key per row


def _quantity(schema: ScheduleSchema, attrs: dict[str, str]) -> tuple[float | None, str | None, str]:
    """(quantity, unit, basis) for one row, per the schedule's shape/qty column."""
    if schema.qty_field and attrs.get(schema.qty_field):
        v = _num(attrs[schema.qty_field])
        if v is not None:
            return v, schema.qty_unit, BASIS_QTY_COLUMN
    if schema.shape == "instance":
        return 1.0, schema.qty_unit, BASIS_ROW_COUNT
    return None, None, BASIS_UNKNOWN


def build_item(row: list, cm: ColumnMap, schema: ScheduleSchema, source: dict) -> ScheduleItem:
    attrs = {fld: _clean(row[c]) for c, fld in cm.mapping.items() if c < len(row)}
    qty, unit, basis = _quantity(schema, attrs)
    return ScheduleItem(
        schedule=schema.name,
        shape=schema.shape,
        mark=attrs.get(schema.key_field, ""),
        quantity=qty,
        unit=unit,
        quantity_basis=basis,
        description=attrs.get("description", ""),
        attributes=attrs,
        source=dict(source),
    )


def parse_schedule(table: list[list], schema: ScheduleSchema, source: dict | None = None) -> list[ScheduleItem]:
    """Turn one resolved schedule table into ScheduleItem records."""
    cm = resolve_columns(table, schema)
    src = source or {"schedule": schema.name}
    return [build_item(r, cm, schema, src) for r in select_rows(table, cm, schema)]
