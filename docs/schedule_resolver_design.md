# Header-Driven Schedule Resolver — Design

**Status:** Built (M1–M7, 111 tests green). Follows the Document Locator; companion to `generalization_inventory.md`.

## Outcome (as built)

- **UCCS**: door + finish parsing is now header-driven; the resolver reproduces the
  old positional mapping exactly, so the validation pipeline is unchanged (all gates
  pass, same door/finish/graph output). The `/58` answer-key term is gone.
- **Pinney door schedule** — the full generalization win: located by header coverage
  (16 cols, where the old exactly-14 rule rejected it), columns resolved by label
  incl. group disambiguation (`Door`/`Frame` → door_material/frame_material) and an
  explicit `Location` column, rows found via **discovered** mark grammar (`B01w`,
  `101w`, not `[NS]`). **91 doors extracted, was 0.**
- **Gates split (C11/C10)**: magnitude counts (24 divisions, 133 sheets, 60 doors…)
  are now reported as metrics; structural invariants stay pass/fail — so the gates
  no longer invert on a different project.
- **Still deferred**: Pinney has no finish schedule (finish generalization is
  UCCS-regression-only until a finish-bearing reference project); abbreviation
  columns (C9) and the applied-finish-list pixel split (C8) remain geometric-region
  work, out of this slice.

---

**Scope:** Generalize schedule *ingestion* end-to-end (detect → resolve columns → identify rows) so schedules are read by header label and discovered row grammar, not by fixed column positions and `[NS]` mark assumptions. Door + finish schedules.

## Why

`parse_door_schedule`/`parse_finish_schedule` map columns by **index** (`_COLUMNS[i]`), select the table by an exact column count + literal anchors, filter rows by a hardcoded `[NS]` mark grammar, and score confidence with a `/58` UCCS term. All of that is UCCS-shaped (inventory B1–B4, C10). Pinney's door schedule is 16 columns, mixed-case, grouped, with an explicit `Location` column and non-`[NS]` marks — so it was located as `absent` and would not parse.

## Locked decisions

- **D1 Synonym-first.** Deterministic synonym + fuzzy (prefix/containment) matching of header labels → canonical fields. LLM/embeddings deferred; the first LLM insertion is B9 (code→section), not this.
- **D2 Full vertical, door+finish.** Soften locator *detection* + column resolution + row-key discovery. Defer abbreviation columns (C9) and applied-finish-list pixel split (C8) — those are geometric region detection, not header matching.
- **D3 Grouped headers.** Compose a group label (`DOOR`/`FRAME`/`SIZE`) with an ambiguous sub-label (`MATERIAL`/`FINISH`/`ELEVATION`) → `door_material`/`frame_material`. Unambiguous labels match directly.
- **D4 Minimal gate split (C11/C10).** Structural invariants stay pass/fail; magnitude counts (`==133`, `>50`, the `/58` term) become reported metrics — so Pinney is measurable.

## Reference reality (measured)

- **UCCS door** (p38): 14 cols, ALL CAPS, title row + group row + sub row. Ground-truth positional mapping the resolver must reproduce byte-identically.
- **Pinney door** (p89, located but rejected by the 14-col rule): 16 cols, mixed case, `Door Schedule` title, groups `Door`/`Frame`, explicit `Location`, truncated cells. **The live generalization test.**
- **Pinney has NO finish schedule** (`ROOM FINISH`/`FINISH SCHEDULE` absent everywhere). So finish resolution is validated on **UCCS regression only**; it's ready for the next finish-bearing reference project. (Pinney also has a window schedule on p90 — a future type.)

## Resolution rule

For each column: primary label = bottom-most non-empty header cell. If it's an ambiguous bare label (`material`/`finish`/`elevation`), compose with the nearest group token (`door`/`frame`/`size`) to its left in a row above; else match directly. Normalize (lowercase, strip punctuation) then match by exact synonym, then prefix/containment (handles `fire rating (m` → `fire rating`, `frame elevatio` → `frame elevation`). First column to claim a field wins.

## Milestones

- **M1 ★** schema + synonyms + header resolver (band detection, group composition, matching). Unit-tested on the real UCCS + Pinney door headers and the UCCS finish header.
- **M2** header-driven door parser; UCCS `DoorEntry` byte-identical; drop `/58`.
- **M3** soften locator door detection (header-resolution score, not exactly-14-col); UCCS still page 37, **Pinney door detected at p88**.
- **M4** row-key grammar discovery (modal mark-column shape, not `[NS]`); Pinney door rows extract.
- **M5** header-driven finish parser; UCCS `FinishEntry` identical (Pinney N/A).
- **M6** minimal gate split (C11/C10).
- **M7** integration: UCCS byte-identical report; Pinney door end-to-end located→resolved→rows.

De-risk is M1 (messy grouped/mixed-case header) then M3/M4 (does Pinney actually yield rows). UCCS byte-identical is the safety net throughout.
