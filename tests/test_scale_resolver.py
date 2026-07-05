"""Tests for the Tier 2.1 sheet scale resolver."""
from __future__ import annotations

import pathlib

import fitz

from src.pipeline.scale_resolver import parse_scale, resolve_sheet_scale

DRAWINGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"


def test_parse_scale_imperial_formats():
    assert parse_scale('1/8" = 1\'') == 96.0
    assert parse_scale('3/64" = 1\'') == 256.0
    assert parse_scale('1/4" = 1\'') == 48.0
    assert parse_scale('1/2" = 1\'') == 24.0
    assert parse_scale('3/4" = 1\'') == 16.0
    assert parse_scale('1" = 20\'') == 240.0
    assert parse_scale("no scale here") is None


def _scale(page_index: int):
    with fitz.open(DRAWINGS) as doc:
        return resolve_sheet_scale(doc[page_index], page_index + 1)


def test_single_scale_floor_plan_resolves_confidently():
    s = _scale(14)                                # p15, 1/8" = 1'
    assert s.factor == 96.0
    assert s.confidence == 1.0
    assert not s.ambiguous
    assert s.all_scales and "1/8" in s.scale_text


def test_enlarged_scale_sheet_resolves():
    s = _scale(13)                                # p14, 3/64" = 1'
    assert s.factor == 256.0
    assert not s.ambiguous


def test_multi_scale_sheet_flagged_ambiguous():
    s = _scale(40)                                # p41, 1/2" = 1' AND 3/4" = 1'
    assert s.ambiguous
    assert s.factor is None
    assert len(s.all_scales) == 2                 # two distinct scales reported
