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

from src.access.document import using_document
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


def join_areas(rooms: list[tuple[str, float, float]],
               labels: list[tuple[float, float, float]],
               max_dist: float = 100.0, max_sf: float = 20000.0) -> list[RoomArea]:
    """Associate each room with its nearest SF label (one label -> one room).

    Two filters keep the join honest:
      * distance — a label beyond `max_dist` of every room is dropped (building/zone
        totals sit far from any single room number);
      * magnitude — a label above `max_sf` is a building/zone total, not a room.
    The join is label-centric: an SF label is printed INSIDE one room, so each label
    binds to its nearest room (not the reverse — a room can have a neighbour's label
    closer than its own). Contention is resolved greedily by closeness: if a room is
    the nearest room to several labels, it keeps the closest one. Confidence falls off
    linearly with distance.
    """
    cands = [(a, x, y) for a, x, y in labels if a <= max_sf]
    pairs: list[tuple[float, str, float]] = []            # (dist, room, area)
    for a, lx, ly in cands:
        best: tuple[float, str] | None = None
        for rm, rx, ry in rooms:
            d = math.hypot(rx - lx, ry - ly)
            if d <= max_dist and (best is None or d < best[0]):
                best = (d, rm)
        if best is not None:
            pairs.append((best[0], best[1], a))

    pairs.sort(key=lambda p: p[0])                         # closest bindings first
    used_rooms: set[str] = set()
    out: list[RoomArea] = []
    for d, rm, a in pairs:
        if rm in used_rooms:
            continue
        used_rooms.add(rm)
        out.append(RoomArea(room_number=rm, area_sf=a,
                            confidence=max(0.0, round(1 - d / max_dist, 3))))
    return out


def harvest_room_areas(source, known_rooms: set[str], page_range=None, **join_kw) -> list[RoomArea]:
    """Driver: locate area plans in a page range and harvest per-room areas from them.

    `source` is a path OR an already-open Document (the coordinator's shared, single-open
    handle). fitz-only and fast. Areas are de-duplicated by room across pages (first area
    plan wins); each result records its source page. Rooms with no nearby label are simply
    absent — not zero-filled (the same count-pending honesty as Tier 1)."""
    with using_document(source) as doc:
        rng = page_range if page_range is not None else range(doc.page_count)
        pages_tokens = [(i, positioned_tokens(doc.page(i))) for i in rng]

        tok_by_page = dict(pages_tokens)
        seen: set[str] = set()
        out: list[RoomArea] = []
        for i in locate_area_plans(pages_tokens, known_rooms):
            toks = tok_by_page[i]
            for ra in join_areas(room_tokens(toks, known_rooms), sf_labels(toks), **join_kw):
                if ra.room_number in seen:
                    continue
                seen.add(ra.room_number)
                ra.source = {"file_id": doc.file_id, "page_index": i}
                out.append(ra)
        return out
