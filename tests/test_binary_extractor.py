"""Tests for binary drawing extraction (Milestone 10).

Requires PyMuPDF (`pip install PyMuPDF`). Milestone 10 is exploratory, so these
assert magnitudes and presence rather than exact counts. Bounds are grounded in an
independent pdfplumber reading of page 14 (~3.2k text glyphs, ~21k vector
primitives, 15 grid labels N-1..N-7 / S-1..S-8); calibrate after the first run.
"""
from __future__ import annotations

import pathlib
from collections import Counter

from src.takeoff.binary_extractor import classify, extract_page

DRAWINGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"

_TEXTS, _PRIMS, _ANALYSIS = extract_page(DRAWINGS)
_CLS = Counter(t.classification for t in _TEXTS)


def test_text_objects_extracted():
    assert len(_TEXTS) > 50


def test_grid_labels_found():
    # Both axes: numeric S-1..S-8 / N-1..N-7 and lettered S-A..S-G / N-A.. .
    assert _CLS["grid_label"] >= 15


def test_door_marks_absent_from_binary_layer():
    # Documented finding: door marks are graphical on the plan, not text.
    # The door schedule (Milestone 7) is the authoritative source for them.
    assert _CLS.get("door_mark", 0) == 0


def test_room_names_found():
    assert _CLS["room_name"] >= 5


def test_dimension_strings_found():
    assert _CLS["dimension"] >= 3


def test_geometry_is_dense():
    assert _ANALYSIS["total_primitives"] > 5000


def test_lines_are_dominant_primitive():
    by_kind = _ANALYSIS["by_kind"]
    assert "line" in by_kind
    assert by_kind["line"] == max(by_kind.values())


def test_classify_unit():
    assert classify("S-3") == "grid_label"
    assert classify("N107B") == "door_mark"
    assert classify("266' - 0\"") == "dimension"
    assert classify("A9.3.1") == "sheet_reference"
    assert classify("CYBER RANGE LAB") == "room_name"