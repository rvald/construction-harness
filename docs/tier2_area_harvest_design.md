# Tier 2 — SF-Label Floor-Area Harvest (Design)

**Status:** Design for review → build. Decided direction: SF-harvest first (approximate, deterministic).
**Date:** 2026-07-05
**Branch:** continue on `feat/quantity-schedules` (Tier 1) or a fresh `feat/area-harvest` — additive either way.
**Depends on:** Tier 1 quantity harness (finish `ScheduleItem`s supply the known-room set), fitz text extraction.
**Golden rule:** additive only; `output/reports/validation_report.json` stays byte-identical.

---

## 1. Goal

Give the estimator an **approximate per-room floor area** — the quantity that unlocks the largest cost categories (flooring, paint, drywall) — from the cheapest reliable source: the **SF text labels already printed on the area/floor plans**. No scale, no geometry, no vision (the labels are already in square feet).

Explicitly approximate: these are occupancy/gross areas, partial coverage. Every result carries a confidence and the basis is labeled `area_label_join`, never presented as exact net area.

---

## 2. Measured basis (why this works, and its ceiling)

Probed on both firms (`scratchpad/areaprobe.py`, `pinney_area.py`):

- **UCCS:** the occupancy/area plan (p4) carries 59 room tokens + 51 `### SF` labels; **8/12 labels pair to a room within ~50pt** (`816 SF→N105 @25`, `1024 SF→N138 @43`, `781 SF→S102 @53`). Regular floor plans (p15–17) have room numbers but **no** SF labels.
- **Pinney:** SF labels co-located with room numbers on several plan sheets (p44–46, p51–53, p95–96, 14–15 labels each). Pattern generalizes.
- **Noise (must filter):** building/zone gross totals (`44403 SF`, `36726 SF`) share the sheet and pair spuriously at long distance. p3-type sheets have SF labels but no room tokens (pure building-gross) — unusable per-room.

**Ceiling:** one sheet type per project, ~partial room coverage, occupancy/gross magnitude (approximate). Accurate net areas are Tier 3 (geometry). This tier is the fast, honest first signal.

---

## 3. Approach

1. **Locate area/floor plans by signature** — pages carrying both many `### SF` labels AND several room tokens from the known-room set. No page constants; cross-checked against the drawing index where a "CODE/AREA/OCCUPANCY" title exists.
2. **Extract positioned tokens** with fitz (fast): rebuild `### SF` labels (may split across spans) and room tokens, each with a center point.
3. **Constrain to known rooms** — join SF labels only to rooms that exist in the finish `ScheduleItem` set. This single constraint removes most noise: dimensions, grid labels, and stray numbers can't masquerade as rooms.
4. **Filtered proximity join** — each known room → nearest SF label within `max_dist`; drop labels above a magnitude cap (building/zone totals) and labels with no room within threshold. Emit per-join **confidence** from distance (and a penalty when a label is nearest to several rooms, or a room to several labels).
5. **Emit `RoomArea`** and report coverage (rooms-with-area / total finish rooms).

---

## 4. Data model

```python
@dataclass
class RoomArea(JsonModel):
    room_number: str
    area_sf: float
    basis: str            # "area_label_join"
    confidence: float     # 0..1 from distance + uniqueness
    source: dict          # {file_id, page_index}
```

Areas attach to the quantity artifact as a `room_areas` list and enrich the matching finish items; catalog/other schedules are unaffected.

---

## 5. Module sketch — `src/pipeline/area_harvest.py`

- `positioned_tokens(page)` → `[(text, cx, cy)]` (fitz).
- `sf_labels(tokens)` → `[(area_sf, cx, cy)]` (rebuild split number+"SF").
- `room_tokens(tokens, known_rooms)` → `[(room, cx, cy)]` (intersect with the finish-room set).
- `join_areas(rooms, labels, max_dist, max_sf)` → `[RoomArea]` with confidence.
- `locate_area_plans(pdf_path, page_range, known_rooms, min_labels)` → candidate page indices.
- `harvest_room_areas(pdf_path, known_rooms, page_range=None)` → `[RoomArea]` (driver; fitz-only, fast).

Deterministic throughout — offline-testable. Reuses the firm-agnostic room grammar from the finish path; the known-room constraint is what makes it robust across firms.

---

## 6. Milestones (one commit each, offline tests, golden held)

- **M1 — model + extraction.** `RoomArea`; `positioned_tokens` / `sf_labels` / `room_tokens`; `locate_area_plans`. Test: UCCS area plan (p4) is located by signature; SF labels + room tokens extracted with positions.
- **M2 — filtered join + confidence.** `join_areas` constrained to known rooms, with distance/magnitude filtering and confidence. Test: UCCS p4 yields the known pairs (`N105≈816`, `N138≈1024`, `S102≈781`); coverage reported; gross totals rejected.
- **M3 — integrate + generalize.** `harvest_room_areas` wired into `build_schedule_items` (adds `room_areas` + coverage metric to `schedule_items.json`, not the golden report). Pinney smoke test proves cross-firm harvest.

---

## 7. Honest labeling (carried into the output)

Every `RoomArea` states `basis="area_label_join"` + `confidence`, and the artifact reports coverage so a consumer sees *which* rooms have an area and how trustworthy each is. Rooms with no nearby label are simply absent (not zero-filled) — the same count-pending honesty as Tier 1's catalogs. Superseding these with geometric net areas is the Tier 3 follow-on.
