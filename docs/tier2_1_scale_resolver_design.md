# Tier 2.1 — Sheet Scale Resolver (Design)

**Status:** Design + M1 build.
**Date:** 2026-07-05
**Branch:** `feat/quantity-measurement` (off merged `main`).
**Plan of record:** **Scale (this) → Counts (T3.1) → reassess.**
**Purpose:** the deterministic measurement foundation. Scale converts drawn distances to real feet; it is the prerequisite for geometric areas / linear / volume (T3.2+). It does *not* pay off until those tiers — placed now as a cheap, low-risk stone.

---

## 1. Measured basis

Probed on both firms (`scratchpad/scaleprobe.py`):
- **Overall floor plans carry exactly ONE scale** — UCCS p14/15/16 (`3/64"=1'`, `1/8"=1'`), Pinney p21/44 (`1/8"=1'`). These are the sheets that matter for area/length takeoff.
- **Detail/enlarged sheets carry several** — identical repeated (Pinney p31: `1/4"=1'` ×11, one per viewport) or genuinely **different** (UCCS p41: `1/2"=1'` + `3/4"=1'`).
- Format is always imperial architectural `N/M" = 1'` (also `N" = D'`).

## 2. Scope decision

**Sheet-level resolver.** A sheet with a single distinct scale → confident factor. A sheet mixing scales → `ambiguous=True`, factor unresolved, all scales reported (per-viewport association is a later refinement, only needed for detail sheets — not the plan sheets measurement needs first).

## 3. Parse

`N/M" = D'` → **factor = (D × 12) / (N/M)** = real inches per paper inch.
Examples: `1/8"=1'`→96, `3/64"=1'`→256, `1/4"=1'`→48, `1/2"=1'`→24, `1"=20'`→240.
A drawn distance of `P` points → real inches = `(P/72) × factor`.

## 4. Model

```python
@dataclass
class SheetScale(JsonModel):
    pdf_page_number: int
    factor: float | None        # real inches per paper inch; None if none/ambiguous
    scale_text: str             # chosen scale string ("" if none/ambiguous)
    confidence: float           # 1.0 single scale, ~0.4 ambiguous, 0.0 none
    ambiguous: bool = False     # >1 distinct scale on the sheet
    all_scales: list[str] = []  # every distinct scale string found
```

## 5. Milestones

- **M1 (this)** — `parse_scale` + `scale_strings` + `resolve_sheet_scale`; sheet-level, single-scale confident / multi-scale flagged. Offline tests on UCCS single-scale + multi-scale sheets.
- **M2 (later)** — optional deterministic self-check: measure a known dimension leader's drawn length vs its stated feet to corroborate the parsed factor → calibrated confidence.
- **M3 (later)** — per-viewport association for detail sheets (only when a consumer needs detail-level measurement).

Deterministic and offline throughout. Additive; golden untouched.
