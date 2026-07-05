# Geometric Tier — B0 Polygonization Spike (Result: DEFERRED)

**Date:** 2026-07-05
**Question:** Can we form closed room polygons from the wall geometry (+ T2.1 scale) and
get net floor areas that match the SF-harvest ground truth? This was the go/no-go gate
for the whole geometric tier (net floor/wall/ceiling areas, linear runs — all flow from
room polygons).

## What was tried

On the UCCS North floor plan (p15, `1/8"=1'`, factor 96): extracted the wall line
segments (phase-4 geometry), noded the arrangement and ran `shapely.ops.polygonize`,
matched each finish-schedule room label to its containing polygon, converted polygon
area (pt²) to sqft via the scale, and compared to the SF-harvest ground truth.

## Result — deterministic polygonization is NOT viable off-the-shelf

- polygonize ran fine (0.5s, 10,984 polygons from ~15k segments) but produced **no
  correctly-sized room polygons**:
  - most rooms fall into one **giant 47,748 SF enclosing face** — the walls don't close
    at doorways, so the arrangement merges many rooms into a single region;
  - the rest land in **tiny slivers** (5–10 SF) — the gaps between double-wall lines.
- Ground-truth check: `N108` computed **47,748 SF** vs harvest **71 SF** (~670× off).

Root causes (the hard ones flagged since the phase-4 exploration): doorway gaps (rooms
don't close), double-wall thickness (slivers), no 1:1 room→polygon mapping. Also,
deterministic polygonization needs a geometry library (`shapely`) that wasn't a project
dependency — a further cost signal.

Making it work would require a real wall-processing pipeline: double-wall→centerline
merge, doorway-gap snap-closing, then room-label-seeded face extraction. Substantial,
uncertain engineering.

## Decision (user, reassess-after-B0): DEFER the geometric tier

Rationale: **Tier 2 already provides approximate floor areas** (SF-label harvest), so the
geometric tier's only marginal gain is net-vs-gross *accuracy* — which the spike shows is
expensive (heavy wall pipeline) or requires departing from the VLM-as-verifier rule
(VLM-estimated areas). Not worth it now. Ship the substantial extraction already built
(schedules, multi-trade counts, approximate areas, bid structure).

`shapely`/`numpy` were installed only to run this spike and are removed; no committed
code depends on them. If the geometric tier is revisited, start from the wall-processing
pipeline above, not raw `polygonize`.
