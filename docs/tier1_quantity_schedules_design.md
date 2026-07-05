# Tier 1 — Schedule-Sourced Quantities (Design)

**Status:** Design for review — no code yet.
**Date:** 2026-07-05
**Branch target:** new feature branch off `main` (do not build on `feat/document-locator`).
**Depends on:** existing header-driven `schedule_resolver` (door + finish), document locator, abbreviation map.
**Golden rule:** additive only. `output/reports/validation_report.json` (UCCS door/finish) must remain byte-identical; snapshot then diff.

---

## 1. Goal

Deliver the *quantity* data an estimator needs from the cheapest, most reliable source we have: the schedules themselves. No scale, no geometry, no VLM. This is the highest value-to-effort slice of the quantities gap, and it matches the takeoff skill's own rule that **schedules are authoritative**.

Scope is explicitly **schedule-sourced quantities and type catalogs**. Plan-level counting/measuring (fixtures per room, floor areas, linear runs) is Tier 2/3 and out of scope here.

---

## 2. Measured schedule landscape

From probing both firms' drawings (`scratchpad/sprobe.py`, `hprobe.py`):

**UCCS drawings** carry (real, de-duped): door, room finish, lighting fixture & control, toilet accessory, partition, plumbing fixture, mechanical equipment, modular casework, fan / RTU / VAV (mechanical), switchboard / feeder / lighting-control (electrical), security device / camera.

**Pinney** is structural-heavy: door, window (composite + storefront), precast plank, strip/spread footing, concrete pier, steel column, beam, lintel, shear wall, header, post, masonry wall, exterior material, lighting.

Two firms, largely disjoint schedule sets — so the resolver must stay **discovery-driven**, not a fixed list.

---

## 3. The core finding: three schedule shapes

Each schedule yields a *different kind* of quantity. This is the crux of the design.

| Shape | Row means | Quantity it yields | Examples (measured) |
|---|---|---|---|
| **A. Instance** | one physical thing | **direct count** = row count; per-instance attributes | Door schedule (60 rows = 60 doors) |
| **B. Catalog + measure** | one type/mark | per-type **size / area / embedded QTY**, but not instance count | Pinney window (`DAYLIGHT AREA (SF)`); plumbing variant with `QUANTITY` col; casework qty |
| **C. Catalog only** | one type/mark | type → **spec/description** (no count, no measure) | Plumbing fixture (`WC-1 → American Standard 3351.101`); lighting fixture |

**Consequence — set expectations honestly:** doors are the only clean instance schedule in these sets. For everything keyed by type/mark, the schedule gives **specification, size, and sometimes area/qty**, but the *count of each type* is on the drawings and stays a Tier 3 (plan-count/VLM) problem. Tier 1 does **not** invent those counts.

---

## 4. What Tier 1 will / won't deliver

**Will:**
- Direct **counts** from instance schedules (door today; the mechanism generalizes to any future one-row-per-instance schedule).
- **Type catalogs** (mark → description → spec, cross-referenced to the abbreviation/legend map and, where possible, the code→section graph) for fixtures, lighting, equipment, casework, partitions, windows.
- Any **embedded quantity/measure columns** a schedule happens to carry: `QUANTITY`, `DAYLIGHT AREA (SF)`, size → derived area, etc., captured verbatim with units.

**Won't (deferred):**
- Instance counts for catalog-keyed items (fixtures/lighting/windows per room) — Tier 3.
- Floor/wall/ceiling areas, linear runs — Tier 2/3.
- Structural quantities requiring section thicknesses/lengths — later.

---

## 5. Data model

One uniform record so downstream (WBS / pricing) treats every schedule alike, with provenance and an explicit basis so nobody mistakes a catalog row for a count.

```python
@dataclass
class ScheduleItem(JsonModel):
    schedule: str            # canonical schedule name: "door" | "window" | "plumbing_fixture" | ...
    shape: str               # "instance" | "catalog"
    mark: str                # door_mark / window mark / fixture tag  (row key)
    description: str          # from the schedule or resolved via abbreviation/legend
    attributes: dict         # all resolved canonical fields -> value (size, material, model, ...)
    quantity: float | None   # count (instance) or embedded QTY column; None if unknown
    unit: str | None         # "EA" | "SF" | ...  (None when quantity is None)
    quantity_basis: str      # "row_count" | "qty_column" | "size_derived" | "unknown_plan_count"
    source: PageRef          # file/page/signature provenance from the locator
```

`quantity_basis="unknown_plan_count"` is the explicit, honest marker for catalog items whose count Tier 1 cannot supply — it becomes a work item for Tier 3, not a silent zero.

---

## 6. How we extend the existing resolver

The resolver ([schedule_resolver.py](../src/pipeline/schedule_resolver.py)) already does the hard part — header-driven, order/count-agnostic column mapping with grouped-header composition. Extension is mostly **declaring more `ScheduleSchema`s + wiring the locator + a generic parser**, not new algorithms.

1. **Add `ScheduleSchema` definitions** for the Tier 1 targets (window, plumbing_fixture, casework, partition, equipment...). Each declares `fields` (canonical → synonyms), `core_fields`, and `shape`. Reuses `resolve_columns` / `select_schedule_table` unchanged.
2. **Generalize the locator** ([locator.py](../src/pipeline/locator.py)): today it hard-declares `door_schedule` / `finish_schedule` `LocatorSpec`s. Make it iterate the schema registry — for each schema, find pages whose text carries the schedule's title/header signature. Add the new artifact names to `KNOWN_ARTIFACTS` in [document_map.py](../src/models/document_map.py).
3. **Generic schedule parser**: one parser that, given a located page + schema, selects the table (`select_schedule_table`), resolves columns, walks data rows into `ScheduleItem`s, sets `quantity`/`quantity_basis` from the schema's `shape` + presence of a QTY/measure column. The existing door/finish parsers stay as-is (golden), or become thin callers of the generic path once proven equal.
4. **Emit** a `schedule_items.json` artifact + roll counts into the validation report as **reported metrics** (never hard gates — magnitudes vary per project, per the generalization inventory's C11 lesson).

---

## 7. Target schedules for Tier 1 (prioritized)

Ordered by value-to-effort and cross-firm coverage:

1. **Window / glazing** — instance-or-mark, present in both firms; carries size + (Pinney) daylight area. High estimator value.
2. **Plumbing fixture** — catalog + spec + occasional QTY; clean header row measured on p59.
3. **Equipment (mechanical) + modular casework** — catalog + spec; casework often carries counts.
4. **Partition types** — catalog; feeds wall assemblies (and later linear-length takeoff).
5. **Lighting fixture** — catalog + spec (control-zone tables filtered out).

Structural schedules (footing/pier/beam/column, Pinney) are a natural **Tier 1b** once the generic path is proven — same mechanism, different schemas.

---

## 8. Milestones (one commit each, offline tests)

- **M1 — Data model + generic parser.** `ScheduleItem`, generic schema-driven parser, proven to reproduce door + finish output exactly (no golden change). Tests: door/finish parity.
- **M2 — Window schedule.** Schema + locator signature + parse for both firms. Tests on UCCS + Pinney window tables.
- **M3 — Catalog schedules.** Plumbing fixture, equipment, casework, partition, lighting schemas; catalog `ScheduleItem`s with `unknown_plan_count`. Tests per schedule.
- **M4 — Artifact + metrics.** Emit `schedule_items.json`; add schedule-item counts as reported metrics; refresh golden intentionally (documented re-baseline).

---

## 9. Golden-baseline safety

- Snapshot `output/reports/validation_report.json` before M1; diff after each milestone.
- New outputs go to a **new** artifact (`schedule_items.json`); the existing report only gains *reported metrics*, and only at M4 with an intentional, documented re-baseline.
- Door/finish parsing behavior is held identical (M1 parity test is the guard).

---

## 10. Open decisions to confirm

1. **Scope of Tier 1 targets** — do all five §7 schedules now, or start with window + plumbing_fixture and add the rest once the generic path is proven?
2. **Structural schedules (Pinney)** — fold in as Tier 1b now, or defer until the architectural set is solid?
3. **Catalog items with no count** — is `unknown_plan_count` the right contract (surface them as spec catalog + explicit count-pending), or should catalog-only schedules be excluded from the quantity artifact entirely until Tier 3?
4. **Description enrichment** — resolve descriptions against the abbreviation/legend map and code→section graph now, or keep raw schedule text in Tier 1 and enrich later?
