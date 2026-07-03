"""Tests for the semantic section resolver (B9).

M1 — expansion assembly: every UCCS material/finish code should get a usable
human-readable description by merging the abbreviation list with the applied-finish
`TYPE:` field. This is the input the matcher (M2) scores against section titles.
"""
from __future__ import annotations

from src.pipeline.phase2_abbreviation_parser import abbreviations_as_dict, parse_abbreviations
from src.pipeline.phase2_schedule_parser import parse_applied_finish_list
from src.pipeline.phase2_spec_parser import parse_spec_toc
from src.pipeline.phase5_graph_builder import FINISH_SECTION, MATERIAL_SECTION
from src.pipeline.section_resolver import expansion, match_section

_ABBR = abbreviations_as_dict(parse_abbreviations())
_APPLIED = parse_applied_finish_list()
_TITLES = {s["number"]: s["title"] for d in parse_spec_toc().divisions for s in d["sections"]}


def _exp(code: str, prefer: str = "finish") -> str:
    return expansion(code, _ABBR, _APPLIED, prefer)


def test_material_expansions_prefer_abbreviation():
    # 'material' context avoids the WD-1 wood-slat-ceiling finish collision.
    assert _exp("HM", "material") == "HOLLOW METAL"
    assert _exp("WD", "material") == "WOOD"


def test_finish_expansions_from_applied_type():
    # These have no abbreviation entry — their meaning comes from the finish TYPE:.
    assert "PAINT" in _exp("P", "finish").upper()
    assert "CARPET" in _exp("CPT", "finish").upper()
    assert "CONCRETE" in _exp("CON", "finish").upper()


def test_expansion_coverage_improved_over_abbreviations_alone():
    got = ([_exp(c, "material") for c in MATERIAL_SECTION]
           + [_exp(c, "finish") for c in FINISH_SECTION])
    # abbreviations alone covered ~9/15; merging the finish TYPE: source lifts it.
    assert sum(1 for e in got if e) >= 12


# --- M2: deterministic matcher -----------------------------------------------

def test_matcher_derives_clean_material_by_division():
    assert match_section("HOLLOW METAL", _TITLES, "08")[0] == "081113"
    assert match_section("WOOD", _TITLES, "08")[0] == "081416"


def test_matcher_derives_clean_finish_via_prefix_overlap():
    assert match_section('18" X 36" CARPET TILE', _TITLES)[0] == "096813"   # carpet~carpeting
    assert match_section("RESILIENT BASE", _TITLES)[0] == "096513"
    assert match_section("ACOUSTIC CEILING TILE", _TITLES)[0] == "095113"    # acoustic~acoustical


def test_matcher_flags_tail_as_none_not_a_lucky_argmax():
    assert match_section('4" RUBBER', _TITLES)[0] is None      # rubber != resilient base
    assert match_section("", _TITLES, "08")[0] is None         # no expansion
