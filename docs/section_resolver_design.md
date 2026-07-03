# Semantic Section Resolver (B9) — Design

**Status:** Active build. Follows the Schedule Resolver; companion to `generalization_inventory.md`.
**Scope:** Replace the hand-authored `MATERIAL_SECTION` / `FINISH_SECTION` code→section
dicts in `phase5_graph_builder.py` with edges *derived* by semantically matching a
code's expansion against the project's real TOC section titles, constrained by CSI
division. This is the first LLM insertion point — used *inside ingestion* to build
knowledge, not the downstream estimating agent.

## Locked decisions

- **D1 Pluggable backend.** A `SectionResolver` with a deterministic,
  division-constrained matcher as the default (CI-tested) backend, and an
  LLM/embedding backend behind the same seam for the low-confidence tail. Keeps CI
  offline; the LLM is an enhancement, not a hard dependency.
- **D2 UCCS reproduction, byte-identical.** The derived resolver must reproduce the
  hand-authored edges on UCCS so the validation report is unchanged. Codes it can't
  derive confidently keep their hand-authored entry as an **override/seed** (not
  dropped). Pinney is deferred (blocked on section-line + abbreviation generalization).
- **D3 Scope.** Material + finish codes (the two dicts). Hardware/glazing (single
  constants) are an optional stretch.
- **D4 LLM proven offline.** The LLM backend is exercised via **recorded fixtures**
  (deterministic, offline-replayable in CI) plus one optional network-gated live test.

## Measure-first findings (UCCS, division-filtered lexical baseline)

9/15 raw, but only ~5 solid (`HM, WD, RB, CONC, GYP` at score 1.0). `P/MWP/WP/CON`
were "right by luck" (0.0 overlap, division argmax). Genuinely hard: `ACT` (tile vs
panel — semantic), `CPT` (carpet vs carpeting — stemming), `AL` (two aluminum
sections — ambiguous), `T` (wrong expansion), `WB` (no expansion).

**Key finding: expansion quality is the bottleneck, not matching.** 6/15 codes have
no abbreviation-list expansion — their meaning lives in the applied-finish-list
`TYPE:` field (`P-1 → "GENERAL PAINT"`, `CPT-1 → "CARPET TILE"`,
`CON-1 → "POLISHED & SEALED CONCRETE"`). Feeding those in + stemming should recover
most; the residual semantic ambiguity (`ACT`, `AL`) is where the LLM earns its place.

## Milestones

- **M1 ★** Expansion assembly: `expansion(code)` merges the abbreviation dict + the
  applied-finish-list `TYPE:` descriptions into the best description per code.
- **M2** Deterministic matcher: division-constrained, normalized + stemmed token
  overlap → `(section, confidence)` or `None`; returns low-confidence (not a
  coincidental argmax) when overlap ≈ 0.
- **M3** `SectionResolver` + graph integration: derive → override/seed for the tail;
  replace the dicts in `build_graph`. UCCS byte-identical.
- **M4 ★** LLM backend for the low-confidence tail (grounded multiple-choice over
  division-filtered titles), proven with recorded fixtures.
- **M5** Provenance: each edge carries `method` (derived_lexical / derived_llm /
  override) + confidence; confirm the seam is data-driven and Pinney-ready.

Staging: after M3, byte-identical via deterministic-derived edges + overrides for the
~6 hard cases (LLM never on the critical path). M4 derives the tail, shrinking
overrides toward zero. De-risk = M1 (expansions) and M4 (LLM accuracy on `ACT`/`AL`).
