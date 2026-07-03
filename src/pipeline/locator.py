"""Phase 1 — Artifact locator (Document Locator, M4/M5).

Finds each target artifact by CONTENT SIGNATURE within the region where it belongs,
replacing the hardcoded `_PAGE_INDEX` constants. Every locator is two-tier:

  1. cheap PREFILTER over the already-computed page profiles (anchor tokens) —
     no PDF re-open — to get a small candidate set within the target region;
  2. expensive CONFIRM (extract_tables / text signature) on those candidates only.

This is what keeps it fast (we never table-extract 525 pages) and general (we reuse
the same signatures the parsers already trust: `_is_sheet_list_table`,
`_select_schedule_table`, the TOC division/section grammar).

Not-found is explicit: a target whose region is absent -> not_applicable; a target
searched but not confirmed -> absent. Neither raises. (Locked decision.)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

import pdfplumber

from src.models.document_map import (
    STATUS_ABSENT, STATUS_FOUND, STATUS_LOW, STATUS_NA,
    FileRef, LocatedArtifact, PageProfile, PageRef, Region,
)
from src.pipeline.phase2_drawing_index import _is_sheet_list_table
from src.pipeline.phase2_schedule_parser import _clean, _select_schedule_table
from src.pipeline.phase2_spec_parser import DIVISION_RE, SECTION_RE

# --- confirm signatures (run on candidate pages only) ------------------------


def _confirm_toc(page: "pdfplumber.page.Page", _profile: PageProfile) -> float:
    """A TOC page lists many divisions/sections; a spec page has ~one header."""
    text = page.extract_text() or ""
    hits = sum(1 for ln in text.splitlines() if DIVISION_RE.match(ln) or SECTION_RE.match(ln))
    return 1.0 if hits >= 3 else 0.0


def _confirm_drawing_index(page: "pdfplumber.page.Page", _profile: PageProfile) -> float:
    return 1.0 if any(_is_sheet_list_table(t) for t in page.extract_tables()) else 0.0


def _confirm_door_schedule(page: "pdfplumber.page.Page", _profile: PageProfile) -> float:
    return 1.0 if _select_schedule_table(page.extract_tables()) is not None else 0.0


def _confirm_finish_schedule(page: "pdfplumber.page.Page", _profile: PageProfile) -> float:
    """A room-finish schedule: a 7-col table titled ROOM FINISH SCHEDULE, or one
    carrying all four finish surfaces. The all-four test avoids matching a wall-
    assembly detail that merely mentions CEILING (UCCS page 35)."""
    for t in page.extract_tables():
        if not t or len(t[0]) != 7:
            continue
        header = " ".join(_clean(c) for row in t[:3] for c in row).upper()
        if "ROOM FINISH SCHEDULE" in header:
            return 1.0
        if all(k in header for k in ("FLOOR", "BASE", "WALL", "CEILING")):
            return 0.7
    return 0.0


def _score_abbreviations(profile: PageProfile) -> float:
    """No PDF needed: the abbreviation sheet is dense with 1-4 char all-caps tokens.
    Saturating, strictly-increasing score so the true sheet wins argmax without ties."""
    c = profile.short_token_count
    return c / (c + 400.0)


# --- locator specs -----------------------------------------------------------


@dataclass
class LocatorSpec:
    name: str
    region_kind: str
    prefilter: Callable[[PageProfile], bool]
    confirm: Callable[..., float]
    needs_pdf: bool = True
    multiplicity: str = "one"       # "one" (best page) | "run" (longest contiguous run)
    min_conf: float = 0.6


def _has(*tokens: str) -> Callable[[PageProfile], bool]:
    return lambda p: all(t in p.anchor_hits for t in tokens)


def _has_any(*tokens: str) -> Callable[[PageProfile], bool]:
    return lambda p: any(t in p.anchor_hits for t in tokens)


LOCATORS: list[LocatorSpec] = [
    LocatorSpec("spec_toc", "manual", _has_any("TABLE OF CONTENTS"),
                _confirm_toc, multiplicity="run"),
    LocatorSpec("drawing_index", "drawings", _has("SHEET NUMBER", "SHEET NAME"),
                _confirm_drawing_index, multiplicity="one"),
    LocatorSpec("door_schedule", "drawings", _has("DOOR SCHEDULE", "FIRE RATING"),
                _confirm_door_schedule, multiplicity="run"),
    LocatorSpec("finish_schedule", "drawings", _has_any("ROOM FINISH SCHEDULE", "FINISH SCHEDULE"),
                _confirm_finish_schedule, multiplicity="run"),
    LocatorSpec("abbreviations", "drawings", _has_any("ABBREVIATION"),
                _score_abbreviations, needs_pdf=False, multiplicity="one", min_conf=0.5),
]


# --- runner ------------------------------------------------------------------


def _candidates(spec: LocatorSpec, profiles: list[PageProfile], regions: list[Region]) -> list[PageProfile]:
    target = [r for r in regions if r.kind == spec.region_kind]
    return [p for p in profiles
            if spec.prefilter(p) and any(r.contains(p.file_id, p.page_index) for r in target)]


def _longest_run(refs: list[PageRef]) -> list[PageRef]:
    """Longest contiguous page_index run within a single file (ties -> higher conf)."""
    best: list[PageRef] = []
    key = lambda rs: (len(rs), sum(x.confidence for x in rs))
    by_file: dict[str, list[PageRef]] = defaultdict(list)
    for r in refs:
        by_file[r.file_id].append(r)
    for file_refs in by_file.values():
        file_refs.sort(key=lambda r: r.page_index)
        runs: list[list[PageRef]] = [[file_refs[0]]]
        for r in file_refs[1:]:
            if r.page_index == runs[-1][-1].page_index + 1:
                runs[-1].append(r)
            else:
                runs.append([r])
        candidate = max(runs, key=key)
        if not best or key(candidate) > key(best):
            best = candidate
    return best


def _assemble(spec: LocatorSpec, refs: list[PageRef], region_present: bool) -> LocatedArtifact:
    if not region_present:
        return LocatedArtifact(spec.name, STATUS_NA, spec.region_kind, [])
    if not refs:
        return LocatedArtifact(spec.name, STATUS_ABSENT, spec.region_kind, [])
    pages = _longest_run(refs) if spec.multiplicity == "run" else [max(refs, key=lambda r: r.confidence)]
    best = max(p.confidence for p in pages)
    status = STATUS_FOUND if best >= spec.min_conf else STATUS_LOW
    pages.sort(key=lambda r: (r.file_id, r.page_index))
    return LocatedArtifact(spec.name, status, spec.region_kind, pages)


def locate_all(
    files: list[FileRef], profiles: list[PageProfile], regions: list[Region],
) -> dict[str, LocatedArtifact]:
    """Locate every registered artifact; returns name -> LocatedArtifact (never raises)."""
    path_by_id = {f.file_id: f.path for f in files}
    results: dict[str, LocatedArtifact] = {}

    for spec in LOCATORS:
        region_present = any(r.kind == spec.region_kind for r in regions)
        cands = _candidates(spec, profiles, regions)
        refs: list[PageRef] = []

        if spec.needs_pdf:
            by_file: dict[str, list[PageProfile]] = defaultdict(list)
            for p in cands:
                by_file[p.file_id].append(p)
            for file_id, ps in by_file.items():
                with pdfplumber.open(path_by_id[file_id]) as pdf:
                    for p in sorted(ps, key=lambda p: p.page_index):
                        conf = spec.confirm(pdf.pages[p.page_index], p)
                        if conf > 0:
                            refs.append(PageRef(file_id, p.page_index, round(conf, 3), spec.name))
        else:
            for p in cands:
                conf = spec.confirm(p)
                if conf > 0:
                    refs.append(PageRef(p.file_id, p.page_index, round(conf, 3), spec.name))

        results[spec.name] = _assemble(spec, refs, region_present)

    return results
