"""Phase 1 — Segmenter (Document Locator, M3).

Turns per-page profiles into typed REGIONS: contiguous runs of same-kind pages
within one file. This is where "separate files vs one combined PDF" dissolves —
each file is segmented independently; a pure manual file yields one region, a
combined PDF yields several.

Design, validated against UCCS + Pinney:
  * size_class is the dominant, reliable signal: `large` -> drawings, `letter`/
    `other` -> manual (the text region). Anchors are noisy across regions (drawings
    carry SECTION/ABBREVIATION hits too), so they REFINE, never lead.
  * Pinney is drawings-first with two drawings blocks around the manual, so we
    never assume ordering or exactly two regions.
  * Stray short runs (e.g. a large foldout inside the manual) are absorbed into the
    surrounding region so they don't split it. `min_run` is a tunable parameter,
    not a magic constant.
  * A tiny boundary run with no manual anchors is cover/back-matter -> front_matter.
    The "no manual anchors" gate keeps a leading TOC page from being buried.
"""
from __future__ import annotations

from itertools import groupby

from src.models.document_map import PageProfile, Region

_MANUAL_ANCHORS = ("DIVISION", "SECTION", "TABLE OF CONTENTS")
_DEFAULT_MIN_RUN = 3


def _provisional_kind(p: PageProfile) -> str:
    return "drawings" if p.size_class == "large" else "manual"


def _runs(kinds: list[str]) -> list[list]:
    """Run-length encode into [kind, start_pos, end_pos] over list positions."""
    out: list[list] = []
    pos = 0
    for k, g in groupby(kinds):
        n = sum(1 for _ in g)
        out.append([k, pos, pos + n - 1])
        pos += n
    return out


def _absorb_strays(kinds: list[str], min_run: int) -> list[str]:
    """Relabel an interior run shorter than min_run when both neighbors agree.

    Handles a lone anomalous page (a large foldout mid-manual, a text page mid-
    drawings) without splitting the surrounding region. Boundary runs are left
    alone — they have only one neighbor and may be genuine front/back matter.
    """
    changed = True
    while changed:
        changed = False
        runs = _runs(kinds)
        for j in range(1, len(runs) - 1):
            kind, s, e = runs[j]
            left, right = runs[j - 1][0], runs[j + 1][0]
            if (e - s + 1) < min_run and left == right and left != kind:
                for pos in range(s, e + 1):
                    kinds[pos] = left
                changed = True
                break
    return kinds


def _mark_front_matter(regions: list[Region], by_index: dict, min_run: int) -> None:
    """Tiny leading/trailing manual runs with no manual anchors -> front_matter."""
    if not regions:
        return
    boundary = [regions[0]] if len(regions) == 1 else [regions[0], regions[-1]]
    for r in boundary:
        if r.kind != "manual" or r.page_count >= min_run:
            continue
        pages = [by_index[i] for i in range(r.page_start, r.page_end + 1)]
        if any(tok in p.anchor_hits for p in pages for tok in _MANUAL_ANCHORS):
            continue  # holds a TOC / division header -> keep as manual
        r.kind = "front_matter"


def segment_file(profiles: list[PageProfile], min_run: int = _DEFAULT_MIN_RUN) -> list[Region]:
    """Segment one file's profiles into ordered, contiguous, non-overlapping regions."""
    profs = sorted(profiles, key=lambda p: p.page_index)
    if not profs:
        return []
    file_id = profs[0].file_id
    by_index = {p.page_index: p for p in profs}

    kinds = _absorb_strays([_provisional_kind(p) for p in profs], min_run)

    regions: list[Region] = []
    for kind, s, e in _runs(kinds):
        run = profs[s:e + 1]
        purity = sum(1 for p in run if _provisional_kind(p) == kind) / len(run)
        regions.append(Region(
            kind=kind, file_id=file_id,
            page_start=profs[s].page_index, page_end=profs[e].page_index,
            confidence=round(purity, 3),
        ))

    _mark_front_matter(regions, by_index, min_run)
    return regions


def segment_package(profiles: list[PageProfile], min_run: int = _DEFAULT_MIN_RUN) -> list[Region]:
    """Segment every file in the package (order of first appearance preserved)."""
    regions: list[Region] = []
    for file_id in dict.fromkeys(p.file_id for p in profiles):
        regions.extend(segment_file([p for p in profiles if p.file_id == file_id], min_run))
    return regions


if __name__ == "__main__":
    import pathlib

    from src.pipeline.phase1_intake import intake_package
    from src.pipeline.page_profiler import profile_package

    base = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs"
    for label, paths in {
        "UCCS (separate)": [base / "drawings.pdf", base / "project_manual.pdf"],
        "Pinney (combined)": [base / "pinney" / "pinney_library_drawings_and_project_manual.pdf"],
    }.items():
        regions = segment_package(profile_package(intake_package(paths)))
        print(f"\n{label}:")
        for r in regions:
            print(f"  {r.kind:<12} {r.file_id:<28} pages {r.page_start:>4}-{r.page_end:<4} "
                  f"({r.page_count:>3}p, conf {r.confidence})")
