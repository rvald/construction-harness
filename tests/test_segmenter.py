"""Tests for the segmenter (Document Locator, M3).

UCCS: separate files -> exactly one manual region and one drawings region, each
spanning its whole file. Pinney: one combined PDF -> drawings-first, multi-region,
with the manual block correctly identified and the leading TOC page kept in a
manual region (not buried as front_matter).
"""
from __future__ import annotations

import pathlib

from src.pipeline.phase1_intake import intake_file, intake_package
from src.pipeline.page_profiler import profile_file, profile_package
from src.pipeline.segmenter import segment_file, segment_package

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
MANUAL = DATA / "project_manual.pdf"
PINNEY = DATA / "pinney" / "pinney_library_drawings_and_project_manual.pdf"

_PINNEY_REGIONS = segment_package(profile_package(intake_package([PINNEY])))


def _covers_all(regions, page_count: int) -> bool:
    """Regions are contiguous, non-overlapping, and cover every page once."""
    covered = sorted((r.page_start, r.page_end) for r in regions)
    if covered[0][0] != 0 or covered[-1][1] != page_count - 1:
        return False
    return all(covered[i][1] + 1 == covered[i + 1][0] for i in range(len(covered) - 1))


def test_uccs_manual_is_one_region():
    regions = segment_file(profile_file(intake_file(MANUAL)))
    assert len(regions) == 1
    assert regions[0].kind == "manual"
    assert (regions[0].page_start, regions[0].page_end) == (0, 1035)


def test_uccs_drawings_is_one_region():
    regions = segment_file(profile_file(intake_file(DRAWINGS)))
    assert len(regions) == 1
    assert regions[0].kind == "drawings"
    assert (regions[0].page_start, regions[0].page_end) == (0, 132)


def test_uccs_package_has_one_manual_one_drawings():
    regions = segment_package(profile_package(intake_package([DRAWINGS, MANUAL])))
    kinds = sorted(r.kind for r in regions)
    assert kinds == ["drawings", "manual"]


def test_pinney_is_multi_region_both_kinds():
    kinds = {r.kind for r in _PINNEY_REGIONS}
    assert "manual" in kinds and "drawings" in kinds
    assert len(_PINNEY_REGIONS) >= 4  # drawings-first, two drawings blocks + manual


def test_pinney_regions_cover_all_pages():
    assert _covers_all(_PINNEY_REGIONS, 525)


def test_pinney_manual_block_holds_the_specs():
    # The big manual block (DIVISION anchors live at pages 99-455) must be manual.
    hosts = [r for r in _PINNEY_REGIONS
             if r.kind == "manual" and r.page_start <= 300 <= r.page_end]
    assert len(hosts) == 1
    assert hosts[0].page_count > 300


def test_pinney_toc_page_stays_in_a_manual_region():
    # Page 1 carries the TOC anchor; it must not be buried as front_matter.
    hosts = [r for r in _PINNEY_REGIONS if r.page_start <= 1 <= r.page_end]
    assert len(hosts) == 1
    assert hosts[0].kind == "manual"
