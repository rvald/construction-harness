# Document Locator — Design

**Status:** Built (M1–M7 complete, 103 tests green). Companion to `generalization_inventory.md`.

## Outcome (as built)

- **UCCS**: the map rediscovers every previously-hardcoded page (TOC 4-8, index 1,
  door 37, finish 48, abbrev 5). The full pipeline emits a **byte-identical**
  validation report — behavior unchanged, only the *source* of page indices changed.
- **Pinney** (combined, drawings-first, different firm): segments correctly into
  manual/drawings/front_matter; the located TOC recovers **20 divisions vs 0 before**
  (the original silent failure), and the three differently-formatted schedules are
  honestly flagged `absent` (completeness 0.4). No crash, no silent-wrong.
- **Boundary proven**: Pinney section-lines still parse to 0 sections — that's the
  **deferred field-level generalization** (section grammar, header-driven schedule
  columns, code→section resolver), not a locator concern. This phase's job — *find
  the page* — is done; *parse any firm's format* is the next phase.

---

**Date:** 2026-07-02
**Scope:** The *discovery* front-half of the pipeline. Given a bid package of any
shape (separate files or one combined PDF), determine what each page is and where
each target artifact lives, and hand that to the existing extraction parsers.

---

## Problem

Every parser is currently handed a fixed page index (`_PAGE_INDEX = 37`, ...) and
assumes two separate files (`drawings.pdf` + `project_manual.pdf`). The Pinney
reference package is a single combined 525-page PDF from a different firm; against
it the fixed indices point at the wrong pages, `extract_tables` on large-format
pages is pathologically slow, and `parse_spec_toc` returns **0 divisions silently**.

The locator replaces page constants and the two-file assumption with a discovery
step that emits a `DocumentMap`. **At runtime there are zero page constants** — the
UCCS pages only survive as a test oracle (does discovery rediscover the known page?).

## Locked decisions

1. **Everything reduces to typed REGIONS.** Separate files = usually one region
   per file; a combined PDF = several regions in one file. Location runs over
   regions, not files. The separate-vs-combined branch disappears.
2. **Not-found degrades and is flagged, never raised.** Status is explicit:
   `found | low_confidence | absent | not_applicable`. `absent` (expected but
   missing = a real gap) is distinct from `not_applicable` (its region is absent,
   so it's not a failure).
3. **This phase stops at "located the page."** It hands page refs to the existing
   parsers. No field/column-level format generalization here.
4. **Region kind / artifact name are extensible strings**, validated against a
   known set (unknown allowed-but-flagged). Adding `bid_form` later is one line.

## The funnel

```
  BID PACKAGE (1..N files)
      │  1. INTAKE    enumerate files, checksum, format (vector|scanned)
      │  2. PROFILE   per page: size, rotation, text-density, has-text, anchors
      │  3. SEGMENT   group pages -> typed REGIONS (manual|drawings|front_matter)
      │  4. LOCATE    within a region, find artifacts by content signature
      ▼
  DocumentMap  (files · profiles · regions · artifacts+status+confidence · completeness)
      │
      ▼  EXTRACTION  (existing parsers, repointed at the map)
```

**Understanding "format" is three depths:** *structural* (step 2, cheap/universal),
*semantic-enough-to-locate* (steps 3–4, signature match), and *semantic-enough-to-parse*
(column meanings, title-block layout) — the last is downstream extraction, not here.

## Performance discipline

The profiler (step 2) is **cheap and runs on every page** — only `page.rect`,
`get_text()` length, and token greps. It never calls `extract_tables` /
`get_drawings`. The **expensive** signature checks (step 4) run only on the handful
of candidate pages that (a) fall in the right region and (b) pass a cheap text
prefilter. We never table-extract 525 pages — only the ~dozen that could be the
target. Perf budget: profile + segment Pinney (525 pages) in < 60s.

## Components

| # | Component | File | Role |
|---|-----------|------|------|
| 1 | Contracts | `models/document_map.py` | FileRef, PageProfile, Region, PageRef, LocatedArtifact, DocumentMap |
| 2 | Intake (thin) | `pipeline/phase1_intake.py` | files -> FileRef (checksum, page count, format) |
| 3 | Page profiler | `pipeline/page_profiler.py` | per-page cheap features |
| 4 | Segmenter | `pipeline/segmenter.py` | profiles -> typed regions (size-class dominant, smoothed) |
| 5 | Locator registry | `pipeline/locator.py` | region -> artifact page-refs (two-tier signatures) |
| 6 | Map assembler | `pipeline/build_document_map.py` | run 2–5, completeness, cache by checksum |
| 7 | Downstream adapter | edits to parsers + `build_graph` | consume `map.locate(...)` not `_PAGE_INDEX` |

## Build sequence

- **M1** Contracts + thin intake — enumerate UCCS(2 files)/Pinney(1), checksums/format.
- **M2** Profiler ★de-risk — both packages profiled; Pinney < budget; size_class splits Letter from large-format.
- **M3** Segmenter — UCCS: manual/drawings by file; Pinney: regions + boundaries inside one file.
- **M4** Locator (spec_toc) + map assembly + completeness — the silent-0 case becomes explicit found/absent.
- **M5** Remaining locators (index, door, finish, abbrev, sections) — UCCS @ known pages; Pinney found-or-absent.
- **M6** Downstream adapter ★guard — full UCCS pipeline emits an identical validation report.
- **M7** Pinney end-to-end — run the located pipeline; capture found vs absent.

## Test strategy

1. **UCCS regression** — locator rediscovers the currently-hardcoded pages.
2. **Pinney generalization** — regions correct; each artifact `found`/`absent`/`not_applicable`; no crash, no silent empty; no hang.
3. **Perf budget** — profile + segment Pinney under the cap.

## Semantics to remember

- **Completeness is conditional on region presence.** Score = found ÷ *expected*,
  where expected is gated by which regions exist. No manual region ⇒ `spec_toc`
  is `not_applicable`, not `missing`.
- **Segmentation smoothing** (window that keeps a stray page from splitting a
  region) is a tunable parameter, not a magic constant.

## Out of scope (unchanged)

Field/column generalization; OCR/scanned handling (detect + flag only); VLM title
blocks; addenda/RFI versioning; the completeness *report UI*.
