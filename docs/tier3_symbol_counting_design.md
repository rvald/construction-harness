# Tier 3.1 — Fixture / Symbol Counting (Design)

**Status:** Design only — no code. Captures the contract to build against later.
**Date:** 2026-07-05
**Plan of record:** Scale (T2.1) → **Counts (T3.1, this doc)** → reassess (T3.2 geometry vs fan-out vs Div 00/01).
**Branch when built:** fresh off `main` (Tier 1 + Tier 2 are merged to main as of PR #5).
**Depends on:** Tier 1 quantity harness (supplies the catalog + `unknown_plan_count` items). **Does NOT need scale** — counting is dimensionless.

---

## 1. Goal

Close the `unknown_plan_count` gap: for each catalog fixture from Tier 1 (`WC-1`, `L-1`, lighting types, …), determine **how many appear on the drawings**, with per-count confidence and location provenance. This is the datum an estimator needs to price MEP trades, and the first place the harness admits vision.

Success = a plumbing/lighting fixture's `quantity_basis` flips from `unknown_plan_count` → `plan_count`, carrying a count, a confidence, and the boxes it was counted from.

---

## 2. Why vision here (measured)

The deterministic text/geometry layer cannot carry this (probed earlier this session):
- Door marks: **0 recovered** from the floor-plan text layer — they're graphical/rotated fragments.
- Fixture tags on plans: sparse and unreliable in text (`FAN:27, SD:4, L1:4`).
- The binary layer is ~37k line segments with no clean per-symbol structure.

So instances of a fixture symbol are a **visual** pattern, not a text token. This is exactly the VLM-fallback the architecture always specified (inventory B5/B6) and never built.

---

## 3. Design principle — deterministic extraction PRODUCES the count; VLM VERIFIES it

Locked direction (user, 2026-07-05): **the VLM is a verifier that runs *after* deterministic extraction — it does not do the counting.** Deterministic vector/template matching produces the count and the boxes; the VLM then looks at the extracted result against the rendered sheet and confirms it, flags a discrepancy, or adjusts confidence. This mirrors the takeoff skill's own model ("vector extraction handles precision; vision verifies") and the section resolver's pluggable-tail pattern.

- **Deterministic core is primary.** Vector/template matching over the sheet geometry yields a `CountResult` (count + boxes) — fast, offline, testable. This is the source of truth for the number.
- **VLM is the pluggable verifier.** A `CountVerifier` backend takes the extracted result + the rendered region and returns agreement / a corrected read / a confidence adjustment. Two implementations: a **stub** (canned verdicts — offline suite, never calls a model) and a **real VLM adapter** (opt-in, cached).
- **The count survives without the VLM.** If no verifier runs, the deterministic count still stands (unverified, lower confidence). Verification raises confidence or flags for review — it is not on the critical path to *having* a number.
- **Offline tests never call a model.** They validate extraction + aggregation + the basis flip, and the verify-merge logic against the stub.

---

## 4. The contract

Two stages: deterministic **extraction** (primary), then optional **verification** (VLM).

```python
# --- Stage 1: deterministic extraction (primary, offline) ---
def extract_counts(sheet, catalog) -> list["CountResult"]: ...   # vector/template matching

@dataclass
class CountResult:
    symbol_id: str          # catalog key from Tier 1, e.g. "WC-1"
    count: int              # PRODUCED by deterministic extraction
    boxes: list[BBox]       # counted locations -> provenance
    confidence: float       # extraction confidence (pre-verification)
    sheet_page: int
    source: str             # "vector_template"
    verified: bool = False  # set by stage 2

# --- Stage 2: VLM verification (opt-in, pluggable, runs AFTER extraction) ---
class CountVerifier(Protocol):
    def verify(self, req: "VerifyRequest") -> "Verification": ...

@dataclass
class VerifyRequest:
    result: CountResult     # what extraction found — the thing being checked
    region: BBox            # plan viewport
    sheet_image: bytes      # rendered crop for the model to look at
    legend_ref: LegendRef   # the glyph/description the count is of

@dataclass
class Verification:
    symbol_id: str
    agrees: bool
    verified_count: int | None   # the model's own read, when it disagrees
    confidence: float            # verification confidence -> merged into the item
    notes: str
    source: str                  # "vlm"
```

- `LegendRef` ties each `symbol_id` to its drawn symbol — sourced from the legend/abbreviation map + Tier 1 catalog (the catalog exists; the legend glyph is the new extraction).
- **Merge rule:** on `agrees` → raise confidence, `verified=True`; on disagreement → keep the deterministic count but drop confidence and record the model's `verified_count` + `notes` for human review (never silently overwrite the extracted number).

---

## 5. Pipeline flow

```
Tier1 catalog (unknown_plan_count items)
     │  for each symbol_id
     ▼
locate plan viewport(s) for the fixture's discipline   (reuse locator/registry)
     ▼
[EXTRACT] deterministic vector/template match           ──► CountResult (count + boxes)
     ▼
aggregate per (symbol_id, sheet)
     ▼
flip ScheduleItem: unknown_plan_count → plan_count (count, confidence, boxes)   ← already usable here
     ▼
[VERIFY, opt-in] CountVerifier.verify(result, image)    ──► Verification
     ▼
merge: agree → raise confidence + verified=True ; disagree → keep count, flag for review
```

The count is usable after EXTRACT; VERIFY only strengthens/flags it.

Rooms/fixtures with no confident count stay `unknown_plan_count` (same honesty as Tier 1/2 — never a faked number).

---

## 6. Catalog-bounded (why this is tractable)

We never do open-ended detection. We only ever answer "how many of *this known* `symbol_id`?" — the catalog from Tier 1 bounds the problem to a handful of known symbols per discipline. That makes both the deterministic matcher and the VLM prompt narrow and verifiable.

---

## 7. Offline-test story

- **Stub backend** returns canned `CountResult`s → tests assert the aggregation and the `unknown_plan_count → plan_count` flip, plus provenance shape.
- **Deterministic candidate test** on one real fixture symbol (e.g. a plumbing glyph) → assert candidate boxes are found on the known sheet, count is in a plausible range.
- No test invokes a VLM. Real VLM adapter is exercised only in opt-in, non-suite runs (cached).

---

## 8. Open decisions (settle before building)

1. ~~Vector-template-first vs VLM-primary.~~ **RESOLVED (user):** deterministic extraction is primary and produces the count; the VLM is a verifier that runs after. The M0 spike now just measures deterministic-extraction recall on one fixture type (to size how much the verifier has to catch), not whether to use the VLM to count.
2. **First trade.** Plumbing fixtures (clean Tier 1 catalog: WC-1/L-1/MS-1…, and a bounded plan set) — recommended first target. Lighting/power outlets next.
3. **VLM backend + cost.** Which model/adapter; per-sheet/per-symbol call budget; caching keyed on (pdf, page, symbol_id) so re-runs are free and the suite stays offline.
4. **Verification signals.** Where a schedule QTY column, riser diagram, or panel schedule exists, use it to cross-check the visual count and raise/lower confidence.

---

## 9. Milestones (when built)

- **M0 — one-symbol spike (probe).** On one plumbing fixture, measure the deterministic vector/template pass: does it find the instances on the real plan, and at what recall? Sizes what the verifier must catch.
- **M1 — extraction core + basis flip.** `extract_counts` (vector/template) + `CountResult`; aggregate and flip `unknown_plan_count → plan_count` with count/boxes/confidence. Offline tests. **Delivers usable counts without any VLM.**
- **M2 — legend extraction + one trade end-to-end.** `LegendRef` from the legend/catalog; plumbing fixtures counted deterministically into `schedule_items.json` with provenance.
- **M3 — VLM verifier (opt-in).** `CountVerifier` protocol + stub (offline tests for the merge rule) + real cached VLM adapter; verification raises confidence / flags disagreements; suite stays offline.

---

## 10. Payoff

Directly closes the Tier 1 boundary the user flagged: a fixture like `WC-1` goes from "spec known, count pending" to "spec + count + where," which is what the takeoff skill's tag-counting step was always for — the count **extracted deterministically** and **verified by vision**, rather than pulled from an unreliable text layer.
