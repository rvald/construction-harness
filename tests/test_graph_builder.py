"""Tests for knowledge graph assembly (Milestone 11), including the Door N107B
end-to-end acceptance test.
"""
from __future__ import annotations

import pathlib

from src.pipeline.phase5_graph_builder import build_graph

_BASE = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
_KG = build_graph(_BASE / "project_manual.pdf", _BASE / "drawings.pdf")


def _doors():
    return [n for n, d in _KG.g.nodes(data=True) if d["node_type"] == "door"]


def _rooms():
    return [n for n, d in _KG.g.nodes(data=True) if d["node_type"] == "room"]


def test_node_types_present():
    types = {d["node_type"] for _, d in _KG.g.nodes(data=True)}
    assert {"spec_section", "sheet", "door", "room"} <= types


def test_door_n107b_trace():
    """The spec's end-to-end acceptance test."""
    t = _KG.get_door_full_spec("N107B")
    assert t["found"]
    assert t["properties"]["door_material"] == "WD"
    assert t["properties"]["frame_material"] == "HM"
    assert t["properties"]["hardware_set"] == "205"
    assert t["door_spec"]["section"] == "081416"       # Flush Wood Doors
    assert t["frame_spec"]["section"] == "081113"      # Hollow Metal Doors and Frames
    assert t["hardware_spec"]["section"] == "087100"   # Door Hardware
    assert t["glazing_spec"] is None                   # glass N/A
    assert t["room"] == "N107"
    assert "A2.1.1" in t["sheets"]


def test_n107b_trace_has_provenance():
    t = _KG.get_door_full_spec("N107B")
    for key in ("door_spec", "frame_spec", "hardware_spec"):
        assert t[key]["source_file"] == "project_manual.pdf"
        assert isinstance(t[key]["source_page"], int)
    assert t["frame_spec"]["source_page"] == 361


def test_all_doors_resolve_to_a_spec():
    rels = ("DOOR_SPECIFIED_IN", "FRAME_SPECIFIED_IN", "HARDWARE_SPECIFIED_IN", "GLAZING_SPECIFIED_IN")
    doors = _doors()
    resolved = sum(1 for did in doors if any(r in rels for _, r, _ in _KG._out(did)))
    assert resolved / len(doors) >= 0.9


def test_rooms_mostly_resolve_finishes():
    rooms = _rooms()
    resolved = sum(1 for rid in rooms if any(r == "FINISH_SPECIFIED_IN" for _, r, _ in _KG._out(rid)))
    assert resolved / len(rooms) >= 0.9


def test_no_orphan_doors():
    assert _KG.find_orphan_doors() == []


def test_orphan_specs_are_reported():
    # Most spec sections aren't door/room-related; the diagnostic should find them.
    assert len(_KG.find_orphan_specs()) > 50


def test_missing_connections_reported():
    # Unresolvable finish codes (e.g. FRP-1, FTL-1) should be surfaced, not hidden.
    missing = _KG.find_missing_connections()
    assert len(missing) >= 1


def test_room_full_spec_query():
    r = _KG.get_room_full_spec("N102")
    assert r["found"]
    assert r["properties"]["name"] == "STUDENT LIVING ROOM"
    sections = {f["section"] for f in r["finish_specs"]}
    assert "096813" in sections        # CPT-3 -> tile carpeting