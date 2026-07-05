"""Tier 2 — SF-label floor-area harvest.

Harvests approximate per-room floor areas from the `NNN SF` text labels printed on
the area/floor plans, associating each to a room number by proximity. Deterministic
and fitz-only (fast): the labels are already in square feet, so no scale or geometry
is needed. See docs/tier2_area_harvest_design.md.

Robustness comes from ONE constraint: SF labels are joined only to rooms that exist
in the known-room set (the finish schedule's rooms). Dimensions, grid labels, and
stray numbers can't masquerade as rooms, and building/zone gross totals are dropped
by distance + magnitude filtering.
"""
from __future__ import annotations

import math
import re

from src.models.schedule import RoomArea

_SF_UNIT = re.compile(r"^S\.?F\.?$", re.I)          # "SF", "S.F."
_NUM = re.compile(r"^\d{2,5}$")


def positioned_tokens(page) -> list[tuple[str, float, float]]:
    """(text, center_x, center_y) for every word on a fitz page."""
    out: list[tuple[str, float, float]] = []
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        t = word.strip()
        if t:
            out.append((t, (x0 + x1) / 2, (y0 + y1) / 2))
    return out


def sf_labels(tokens: list[tuple[str, float, float]]) -> list[tuple[float, float, float]]:
    """(area_sf, x, y) for each 'NNN SF' label. Handles the number and unit arriving
    as separate adjacent words (the common case) as well as a single 'NNNSF' token.
    The label's position is the NUMBER's position (that's what sits in the room)."""
    out: list[tuple[float, float, float]] = []
    for i, (t, x, y) in enumerate(tokens):
        if _NUM.match(t):
            nxt = tokens[i + 1][0] if i + 1 < len(tokens) else ""
            if _SF_UNIT.match(nxt):
                out.append((float(t), x, y))
        else:
            m = re.match(r"^(\d{2,5})S\.?F\.?$", t, re.I)
            if m:
                out.append((float(m.group(1)), x, y))
    return out


def room_tokens(tokens: list[tuple[str, float, float]],
                known_rooms: set[str]) -> list[tuple[str, float, float]]:
    """(room, x, y) for tokens that match a known room number exactly."""
    return [(t, x, y) for t, x, y in tokens if t in known_rooms]


def locate_area_plans(pages_tokens: list[tuple[int, list]], known_rooms: set[str],
                      min_labels: int = 3, min_rooms: int = 3) -> list[int]:
    """Page indices that carry enough SF labels AND known-room tokens to be an area
    plan (signature-based, no page constants). `pages_tokens` is [(page_index, tokens)]."""
    hits: list[int] = []
    for idx, toks in pages_tokens:
        if len(sf_labels(toks)) >= min_labels and len(room_tokens(toks, known_rooms)) >= min_rooms:
            hits.append(idx)
    return hits
