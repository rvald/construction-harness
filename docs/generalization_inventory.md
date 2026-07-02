# Overfitting & Generalization Inventory

**Status:** Planning artifact — analysis only, no code changes yet.
**Date:** 2026-07-02
**Scope:** Maps where the prototype is fitted to the UCCS bid set specifically, vs. where it encodes portable construction standards. Feeds the decision on generalization order before/alongside the LLM pivot.

---

## How to read this

Every assumption is tagged with a **layer**, which determines the *kind* of fix:

- **Layer A — Universal standard.** Encodes an industry convention (CSI MasterFormat, discipline prefixes). Portable. Keep; at most promote to config.
- **Layer B — Common-but-varying convention.** True across many projects but not all (door-mark grammar, title-block layout, schedule column order). Must become **discovered**, not **assumed** — via header/content parsing, parameterization, or the LLM.
- **Layer C — This-exact-PDF fact.** A page number, a pixel coordinate, an answer-key count. Must **never** be a constant. Becomes a search/classification/intrinsic-metric problem.

Severity reflects blast radius: does the wrong assumption fail loudly (crash), fail silently (zero results, wrong edges), or merely mis-score.

---

## Cross-cutting themes

These recur across components and are the real story — individual line fixes roll up into five patterns:

1. **General mechanism shortcut by a constant.** The portable logic often already exists and is then bypassed with a hardcoded value. `_select_schedule_table` / `_is_toc_page` detect targets by *content signature*, yet every parser is still handed a fixed page index. The TOC computes each section's `page_range`, yet the graph builder locates sections with `start_hint=340`. **De-overfitting here is mostly wiring existing mechanisms together and deleting constants — not rewriting.**
2. **Answer key leaking into runtime.** UCCS ground-truth counts are baked into *production* logic, not just tests: the `/58` term in door confidence, and nearly every validation gate threshold (`== 133 sheets`, `== 24 divisions`, `> 50 doors`). On any other project these silently invert meaning.
3. **Positional instead of semantic.** Schedule fields are mapped by column *index*, not column *header*. Any reordering/added column shifts every field.
4. **Crash instead of degrade.** Non-conforming inputs `raise` (title block, door table) rather than falling back to a lower-confidence path. No VLM fallback exists despite the architecture calling for one.
5. **Hardcoded domain knowledge that should be derived.** `MATERIAL_SECTION` / `FINISH_SECTION` hand-author the exact code→section links the pipeline was meant to *extract* from the abbreviation list + TOC titles. This is the cleanest LLM insertion point.

---

## Inventory

### Layer C — this-PDF facts (must not be constants)

| # | Location | Assumption | Breaks when | Fix direction | Severity |
|---|----------|------------|-------------|---------------|----------|
| C1 | `phase2_schedule_parser.py:27` | Door schedule is on page 38 (`_PAGE_INDEX=37`) | Any other set | Document-locator phase scans pages, matches the existing 14-col+FIRE RATING+HARDWARE SET signature, emits page. | High (silent/crash) |
| C2 | `phase2_schedule_parser.py:147` | Finish schedule on page 49 | Any other set | Same locator, finish-schedule signature. | High |
| C3 | `phase2_abbreviation_parser.py:31` | Abbreviations on page 6 | Any other set | Locator: page whose left band is a 2-col abbrev/definition list. | High |
| C4 | `phase2_drawing_index.py:27` | Drawing index on page 2 | Index elsewhere / multi-page | Locator: page carrying the `SHEET NUMBER / SHEET NAME` table (signature already in `_is_sheet_list_table`). | High |
| C5 | `phase3_sheet_classifier.py:32` | `SAMPLE_PAGE_INDICES` fixed page list | Different set | Iterate all pages, or derive from registry page map. | Medium |
| C6 | `phase5_graph_builder.py:83` | `start_hint=340` locates Division 08 | Different manual | Use `SpecSection.page_range` already computed by TOC parse. | High |
| C7 | `phase5_graph_builder.py:159,180` | Doors/rooms appear on `A9.3.1`/`A2.1.1`/`AF2.4` | Different sheet numbering | Derive host sheets from the schedule locator + registry, don't literal-name them. | Medium (wrong provenance) |
| C8 | `phase2_schedule_parser.py:192` | `room_region_top=1620` splits finish list from schedule | Any other sheet layout | Detect region boundary structurally (table bbox / header positions), not a pixel. | High |
| C9 | `phase2_abbreviation_parser.py:33,34` | Column x-anchors `(169,440,712)`, region `(150,900)` | Any other sheet layout | Cluster columns by detected x-gaps, not fixed anchors. | High |
| C10 | `phase2_schedule_parser.py:138` | Confidence uses `/58` (UCCS door count) | Any other set | Intrinsic confidence only: mark-grammar validity, core-field fill rate, table-shape cleanliness. Drop the count term. | Medium (misleading score) |
| C11 | `gates.py:38-47,58` | Gate thresholds `==24 div`, `==133 sheets`, `>50 doors`, `>25 rooms`, `>100 abbrev`, `>=100 sections` | Every other project | Split gates: **structural invariants** (marks valid, columns resolved, no orphan elements) stay as pass/fail; **magnitude counts** become reported metrics, not assertions. | High (all gates fail on new set) |

### Layer B — firm/convention (must become discovered or parameterized)

| # | Location | Assumption | Breaks when | Fix direction | Severity |
|---|----------|------------|-------------|---------------|----------|
| B1 | `phase2_schedule_parser.py:30,99` | Door marks are `[NS]...`; building map `{N:North,S:South}` | Marks are A/B, E/W, numeric | Discover building tokens from data (distinct mark prefixes) or per-project convention config; don't assume N/S. | High (zero doors) |
| B2 | `phase2_schedule_parser.py:148` | Room numbers `^[NS]\d{3}[A-Z]?$` | Non-N/S numbering | Same as B1; loosen to discovered room-number grammar. | High |
| B3 | `phase2_schedule_parser.py:28,34` | Door schedule = exactly 14 columns in fixed order | Any reordered/added column | Header-driven resolver: fuzzy-match header labels → canonical fields (LLM/synonym table). Order/count agnostic. | High (field shift) |
| B4 | `phase2_schedule_parser.py:167-185` | Finish schedule = 7 columns fixed order | Same | Same header-driven resolver. | High |
| B5 | `phase3_sheet_classifier.py:44-70` | SmithGroup title-block layout (largest sheet-# token, title strip above) | Other firm template | Add VLM fallback on cropped title block when heuristic low-confidence (architecture already specifies this). | High |
| B6 | `phase3_sheet_classifier.py:47` | `raise` when no sheet-number token | Non-standard sheet | Degrade to VLM / mark unclassified; don't crash the run. | High |
| B7 | `phase3_sheet_classifier.py:29` | Project number format `\d{5}\.\d{3}` | Other numbering | Extract from title-block field position, treat format as hint not gate. | Low |
| B8 | `phase2_schedule_parser.py:149` | Finish list codes delimited by `CODE TYPE:` | Other finish-list format | Header/label-driven parse of the applied finish list. | Medium |
| B9 | `phase5_graph_builder.py:33,38` | `MATERIAL_SECTION`/`FINISH_SECTION` hand-authored code→section maps | Missing sections / different codes | Derive by semantically matching abbreviation expansions + finish-list definitions against TOC section titles (embeddings/LLM). **This is the LLM-pivot overlap.** | High (wrong/missing edges) |
| B10 | `phase5_graph_builder.py:45` | Section refs match `Section\s+(0\d{5})` (leading-zero division) | Divisions ≥ 10 (e.g. 23xxxx) | Broaden to full 6-digit MasterFormat pattern. | Medium |
| B11 | `phase2_spec_parser.py:41`, classifier noise | `SMITHGROUP` header string strip | Other firm | Detect repeating header/footer by frequency across pages, not by literal firm name. | Medium |
| B12 | `phase2_spec_parser.py:118` | `_STD_ORGS` fixed org list | New standards body appears | Already extensible; consider broadening the pattern to `ORG + code` shape generically. | Low |
| B13 | `phase2_abbreviation_parser.py:41` | `_dedouble` bold-glyph doubling heuristic | Non-doubling fonts / false positives | Keep but guard; verify against a second font. | Low |

### Layer A — universal standards (keep; at most promote to config)

| # | Location | What it encodes | Note |
|---|----------|-----------------|------|
| A1 | `phase2_spec_parser.py:27,28,114,115` | CSI DIVISION / SECTION / PART / clause grammar | Genuinely standard MasterFormat. Portable. Largest portable chunk of the codebase. |
| A2 | `phase2_drawing_index.py:32` | Discipline prefix map | Mostly standard (G/A/S/M/E/P/C/L). **Caveat:** `T`, `Y`, `EMP`, `AD/AF` are firm-ish — treat those rows as Layer B extensions. |
| A3 | `phase2_drawing_index.py:45` | Drawing-type keyword rules | Reasonably general title keywords; priority ordering is sound. |
| A4 | `phase2_spec_parser.py:25` | Dash normalization (`_DASH`) | Good defensive generalization already in place. |

---

## Suggested fix order (for when we do build)

Rationale: measure first, then retire the highest-blast-radius Layer C with mechanisms we already have, then the Layer B pieces that vary most, then the LLM overlap.

1. **Second reference project** — without it, generalization is unmeasurable; every test encodes UCCS. Converts this doc into a failing-test list. *(Prerequisite, not code.)*
2. **Document-locator phase** — retires C1–C6 using existing content signatures; feeds discovered pages downstream; delete the page constants.
3. **Split the validation gates** (C11) and **drop the `/58`** (C10) — stop the answer key from living in runtime logic.
4. **Header-driven schedule columns** (B3, B4) — highest-variance Layer B; kills positional fragility.
5. **VLM fallback + no-crash degrade** for title blocks (B5, B6).
6. **Semantic code→section resolver** (B9) — replaces the hand-authored dicts; first real LLM integration and a generalization win in one.
7. Structural region detection for abbreviation columns / finish split (C8, C9); building-token discovery (B1, B2).

Defer: B7, B10–B13, A-layer config promotion — let the second reference project prove which actually break before investing.
