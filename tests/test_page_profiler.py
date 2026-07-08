"""Tests for the page profiler (Document Locator, M2).

This is the de-risk milestone: cheap per-page features must (a) separate the
Letter-scale manual from large-format drawings, and (b) do it fast on the 525-page
Pinney set. Profiles for the big UCCS files are computed once at import.
"""
from __future__ import annotations

import pathlib
import time

from src.pipeline.phase1_intake import intake_file
from src.pipeline.page_profiler import profile_file

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
MANUAL = DATA / "project_manual.pdf"
PINNEY = pathlib.Path(__file__).resolve().parents[1] / "data" / "pinney" / "pinney_library_drawings_and_project_manual.pdf"

_MANUAL = profile_file(intake_file(MANUAL))
_DRAWINGS = profile_file(intake_file(DRAWINGS))


def _fraction(profs, size_class: str) -> float:
    return sum(1 for p in profs if p.size_class == size_class) / len(profs)


def test_manual_pages_are_letter_scale():
    assert _fraction(_MANUAL, "letter") > 0.95


def test_drawings_pages_are_large_format():
    assert _fraction(_DRAWINGS, "large") > 0.90


def test_manual_is_text_dense_drawings_are_not():
    # Density cleanly separates the two even where size might be ambiguous.
    manual_med = sorted(p.text_density for p in _MANUAL)[len(_MANUAL) // 2]
    drawings_med = sorted(p.text_density for p in _DRAWINGS)[len(_DRAWINGS) // 2]
    assert manual_med > drawings_med


def test_manual_carries_division_anchors():
    assert any(p.anchor_hits.get("DIVISION") for p in _MANUAL)


def test_drawings_carry_sheet_or_schedule_anchors():
    tokens = {tok for p in _DRAWINGS for tok in p.anchor_hits}
    assert "SHEET NUMBER" in tokens or "DOOR SCHEDULE" in tokens or "FIRE RATING" in tokens


def test_pinney_profiles_split_by_size_and_stay_fast():
    ref = intake_file(PINNEY)
    t0 = time.time()
    profs = profile_file(ref)
    elapsed = time.time() - t0
    assert len(profs) == 525
    kinds = {p.size_class for p in profs}
    assert "letter" in kinds and "large" in kinds
    assert elapsed < 60, f"profiling Pinney took {elapsed:.1f}s (budget 60s)"
