# Bid Structure — Division 00/01 (Design)

**Status:** Building. M1 (alternates) done.
**Date:** 2026-07-05
**Branch:** `feat/bid-structure` (off merged `main` — independent of the scale/counts work).
**Depends on:** fitz text extraction; the standard CSI spec grammar (already parsed elsewhere).
**Golden rule:** additive; `output/reports/validation_report.json` stays byte-identical.

---

## 1. Goal

Fill the one categorical gap the estimation-data assessment left at **zero**: how the
bid is *organized and priced* — **alternates, unit prices, allowances**. Quantities
answer "what/how much"; these answer "what's base vs. alternate, what's an allowance,
what's unit-priced" — the difference between line-item quantities and a biddable tender.

## 2. Measured basis

Probed both manuals (`scratchpad/bidprobe*.py`):

- **UCCS** carries the item definitions as **standard CSI Division-01 sections**:
  `012300 ALTERNATES` (p159), `012200 UNIT PRICES` (p157); no `012100 Allowances`.
  Measured 012300 shape:
  ```
  PART 3 - EXECUTION / 3.1 SCHEDULE OF ALTERNATES
    A. Alternate No. 1: Bench Millwork.
       1. Base Bid: Provide built-in millwork benches ...
       2. Deductive Alternate: Delete two (2) ...
  ```
  UCCS has 4 alternates (Bench Millwork, West Restroom Renovation, Indirect Lighting, Skylights).
- **Division 00** also holds the bid *form* itself, but under owner-specific names
  (Colorado "SBP" forms: `SPECIMEN OF BID`, etc.) plus a CSI `004322 Unit Prices Form`.
  The forms are where prices are *entered*; the item *definitions* (what to price) are
  the Div-01 sections above — so those are the extraction target.
- **Pinney** has **no** formal Div-01 pricing sections → present-when-present,
  absent-flagged otherwise (only UCCS validates the happy path).

## 3. Key insight — reuse, don't rebuild

These are ordinary CSI sections (PART 1/2/3 + numbered articles), the grammar the
harness already parses. So this is **locate the section + text-extract the enumerated
schedule**, not a new parser. Deterministic, offline-testable, additive.

## 4. Model

```python
@dataclass
class BidItem(JsonModel):
    kind: str            # "alternate" | "unit_price" | "allowance"
    number: str          # "1", "2", ...
    title: str           # "Bench Millwork"
    basis: str           # alternate: add|deduct|unknown ; unit_price: unit ; allowance: lump_sum
    description: str = "" # base-bid / unit / allowance scope (first line)
    unit: str | None = None
    source: dict = field(default_factory=dict)   # {file_id, page, section}
```

## 5. Module — `src/pipeline/bid_structure.py`

- `section_text(doc, number)` — locate a section BODY by its header (skipping the TOC),
  read forward to the next section header. (Later: use the TOC page_range the spec
  parser already computes.)
- `parse_alternates(text)` — enumerate `Alternate No. N: Title.` + add/deduct basis +
  base-bid scope.
- `extract_bid_structure(manual)` — drive a registry of `{section -> (kind, parser)}`;
  absent sections degrade and are flagged (`located[kind] = found|absent`).

## 6. Milestones

- **M1 — alternates.** ✅ `BidItem`; `section_text`; `parse_alternates`; UCCS `012300`
  end-to-end (4 alternates, add/deduct, provenance). Parser tested on the measured shape.
- **M2 — unit prices + allowances.** `parse_unit_prices` (012200: item + unit of measure),
  `parse_allowances` (012100; absent on UCCS → flagged). Register in the driver.
- **M3 — artifact + generalization.** ✅ `locate_sections` (single page-pass for all
  wanted sections) + `build_bid_structure` → `output/reports/bid_structure.json`
  ({summary: located + counts, items}). Pinney degrades to all-absent (proven cross-firm).
  UCCS: 4 alternates + 2 unit prices; allowances absent-flagged.

## 7. Honest labeling

`located` distinguishes **found** from **absent** per kind, so a consumer sees which
bid-structure elements a project actually has. Absent sections are never zero-filled or
faked — same posture as Tier 1 catalogs and Tier 2 area coverage.
