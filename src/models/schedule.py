"""Schedule and reference-list models.

For now this holds AbbreviationEntry (Milestone 6). DoorEntry / FinishEntry /
PartitionType land with the schedule parsers in Milestones 7-8.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import JsonModel


@dataclass
class AbbreviationEntry(JsonModel):
    """A single abbreviation definition from the architectural abbreviation list."""

    abbreviation: str           # e.g. "HM"
    definition: str             # e.g. "HOLLOW METAL"


@dataclass
class ScheduleItem(JsonModel):
    """A uniform, quantity-bearing row from any schedule (Tier 1 quantity harness).

    One record per data row, whatever the schedule. `quantity_basis` makes the
    provenance of `quantity` explicit so downstream never mistakes a spec catalog
    row for a real count:
      * "row_count"          — an instance row; quantity == 1, aggregate = row count
      * "qty_column"         — quantity read from an explicit QUANTITY column
      * "unknown_plan_count" — a type/catalog row whose count lives on the drawings
                               (deferred to plan-counting); quantity is None
    """

    schedule: str                               # canonical schedule name, e.g. "door"
    shape: str                                  # "instance" | "catalog"
    mark: str                                   # row key: door_mark / room / fixture tag
    quantity: float | None                      # count or measured qty; None if unknown
    unit: str | None                            # "EA" | "SF" | ...; None when quantity is None
    quantity_basis: str                         # see class docstring
    description: str = ""                        # schedule description, if any
    attributes: dict = field(default_factory=dict)   # all resolved canonical field -> value
    source: dict = field(default_factory=dict)       # provenance: {file_id, page_index, signature}


@dataclass
class FinishEntry(JsonModel):
    """A single row from the room finish schedule (sheet AF2.4)."""

    room_number: str                        # e.g. "N101"
    room_name: str                          # e.g. "VESTIBULE"
    floor_finish: str                       # e.g. "CPT-7"
    base_finish: str                        # e.g. "WB-2"
    wall_finish: str                        # e.g. "P-1/4/ MWP-1/2"
    ceiling_finish: str                     # e.g. "ACT-1" (may be blank)
    comments: str | None = None


@dataclass
class DoorEntry(JsonModel):
    """A single row from the door and interior opening schedule (sheet A9.3.1)."""

    door_mark: str                          # e.g. "N107B"
    fire_rating_minutes: int | None
    width: str                              # e.g. "6' - 0\""
    height: str                             # e.g. "7' - 0\""
    door_elevation_type: str                # e.g. "F", "FG"
    door_material: str                      # e.g. "WD", "AL & G"
    door_finish: str                        # e.g. "WV-1"
    frame_elevation_type: str | None        # e.g. "A"
    frame_material: str                     # e.g. "HM"
    frame_finish: str                       # e.g. "P-1C"
    hardware_set: str                       # e.g. "205", "AL-11"
    glass_film: str | None = None           # e.g. "GLF-2", "N/A"
    glass_type: str | None = None           # e.g. "GL-3", "N/A"
    special_notes: str | None = None
    building: str = ""                      # "North" / "South", derived from the mark prefix