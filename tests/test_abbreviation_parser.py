"""Tests for the abbreviation parser (Milestone 6).

Ground truth is partial per the spec ("verify during implementation"); anchors
below were confirmed against the real A0.1 sheet during exploration.
"""
from __future__ import annotations

import pathlib

from src.pipeline.phase2_abbreviation_parser import (
    _dedouble,
    abbreviations_as_dict,
    parse_abbreviations,
)

DRAWINGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"

_ENTRIES = parse_abbreviations(DRAWINGS)
_DICT = abbreviations_as_dict(_ENTRIES)


def test_dense_list_extracted():
    # Spec estimated "200+"; the real sheet is denser. Guard a sane floor and ceiling.
    assert 200 <= len(_ENTRIES) <= 450


def test_known_anchor_definitions():
    assert _DICT["ACT"] == "ACOUSTICAL CEILING TILE"
    assert _DICT["CMU"] == "CONCRETE MASONRY UNIT"
    assert _DICT["HM"] == "HOLLOW METAL"
    assert _DICT["WD"] == "WOOD"
    assert _DICT["ALUM"] == "ALUMINUM"


def test_hollow_metal_present_for_door_trace():
    # HM is what the Door N107B frame material resolves to downstream.
    assert "HM" in _DICT and _DICT["HM"] == "HOLLOW METAL"


def test_definitions_are_nonempty_uppercase():
    for e in _ENTRIES:
        assert e.definition and e.definition == e.definition.upper()
        assert 1 <= len(e.abbreviation) <= 7


def test_dedouble_helper():
    assert _dedouble("AADDDDIITTIIOONNAALL") == "ADDITIONAL"
    assert _dedouble("HM") == "HM"                 # not doubled -> unchanged
    assert _dedouble("WOOD") == "WOOD"             # even length but not paired -> unchanged