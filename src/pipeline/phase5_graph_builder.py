"""Phase 5 — Knowledge Graph Assembly (Milestone 11).

Assembles the structured outputs of Milestones 3-9 into one connected graph and
demonstrates end-to-end traceability: the Door N107B trace.

Design choices (documented):
  * All spec sections (from the TOC) and all sheets/doors/rooms become nodes, so
    find_orphan_specs is a real diagnostic. Abbreviation nodes are created only for
    material codes actually referenced (keeps them meaningful, not ~400 orphans).
  * Semantic edges come from the schedules/specs (Phases 2-3), never from floor-plan
    binary data — Milestone 10 showed the binary layer carries geometry, not linkage.
  * Per-door floor-plan sheet association is coarse: doors link to the door schedule
    sheet (A9.3.1, definite) and the overall Level 1 plan (A2.1.1). Finer per-sheet
    door placement isn't extractable (M10 finding), so we don't fabricate it.
"""
from __future__ import annotations

import pathlib
import re

from src.models.document_map import DocumentMap
from src.models.graph import GraphEdge, GraphNode, KnowledgeGraph
from src.pipeline.build_document_map import build_document_map, extraction_pages
from src.pipeline.phase2_abbreviation_parser import parse_abbreviations, abbreviations_as_dict
from src.pipeline.phase2_drawing_index import parse_drawing_index
from src.pipeline.phase2_schedule_parser import (
    extraction_confidence, parse_applied_finish_list, parse_door_schedule, parse_finish_schedule,
)
from src.pipeline.phase2_spec_parser import parse_spec_section, parse_spec_toc
from src.pipeline.section_resolver import SectionLink, build_section_map

MANUAL = "project_manual.pdf"
DRAWINGS = "drawings.pdf"

# material code -> spec section number
MATERIAL_SECTION = {"HM": "081113", "WD": "081416", "AL": "084113", "AL & G": "084113"}
HARDWARE_SECTION = "087100"
GLAZING_SECTION = "088000"

# finish code alpha-prefix -> spec section number
FINISH_SECTION = {
    "CPT": "096813", "P": "099123", "MWP": "099123", "WP": "099123",
    "ACT": "095113", "WB": "096513", "RB": "096513",
    "CONC": "033500", "CON": "033500", "T": "093013", "GYP": "092900",
}

_CODE_RE = re.compile(r"[A-Z]{1,4}-\d+[A-Z]?")
_SECTION_REF_RE = re.compile(r"Section\s+(0\d{5})")
_TRACE_SECTIONS = ["081113", "081416", "087100"]


def _sid(num: str) -> str: return f"section:{num}"
def _sec(links: dict[str, SectionLink], key: str) -> str | None:
    link = links.get(key)
    return link.section if link else None
def _room_of(mark: str) -> str:
    m = re.match(r"([NS]\d{3})", mark)
    return m.group(1) if m else mark


def build_graph(
    manual_path: str | pathlib.Path,
    drawings_path: str | pathlib.Path,
    doc_map: DocumentMap | None = None,
) -> KnowledgeGraph:
    kg = KnowledgeGraph()

    # Discover where each artifact lives instead of hardcoding page indices.
    # Absent artifacts (an artifact the locator couldn't confirm) resolve to None
    # and their parser is skipped rather than reading a wrong page.
    if doc_map is None:
        doc_map = build_document_map([drawings_path, manual_path])
    pg = extraction_pages(doc_map)

    toc = parse_spec_toc(manual_path, start_page=pg["toc_start"] or 0)
    registry = parse_drawing_index(drawings_path, page_index=pg["drawing_index"]) \
        if pg["drawing_index"] is not None else []
    doors = parse_door_schedule(drawings_path, page_index=pg["door_schedule"]) \
        if pg["door_schedule"] is not None else []
    rooms = parse_finish_schedule(drawings_path, page_index=pg["finish_schedule"]) \
        if pg["finish_schedule"] is not None else []
    abbrev = abbreviations_as_dict(parse_abbreviations(drawings_path, page_index=pg["abbreviations"])) \
        if pg["abbreviations"] is not None else {}
    applied = parse_applied_finish_list(drawings_path, page_index=pg["finish_schedule"]) \
        if pg["finish_schedule"] is not None else {}
    door_conf = round(extraction_confidence(doors), 3) if doors else 0.0

    section_titles: dict[str, str] = {}

    # --- nodes: spec sections (all, from TOC) ---
    for div in toc.divisions:
        for sec in div["sections"]:
            section_titles[sec["number"]] = sec["title"]
            kg.add_node(GraphNode(
                id=_sid(sec["number"]), node_type="spec_section",
                properties={"title": sec["title"], "division": div["number"]},
                source_file=MANUAL, source_page=None, confidence=1.0,
            ))

    # Derive code -> section links (B9) instead of hardcoding. The hand-authored
    # maps are passed only as a shrinking `seed` override for cases the matcher
    # can't yet derive, so UCCS stays byte-identical.
    material_links = build_section_map(MATERIAL_SECTION, abbrev, applied, section_titles,
                                       "material", "08", seed=MATERIAL_SECTION)
    finish_links = build_section_map(FINISH_SECTION, abbrev, applied, section_titles,
                                     "finish", None, seed=FINISH_SECTION)

    # enrich the trace sections with page provenance + collect cross-references
    section_refs: dict[str, set[str]] = {}
    for num in _TRACE_SECTIONS:
        sec = parse_spec_section(manual_path, num, toc=toc, start_hint=pg["section_start_hint"])
        section_refs[num] = {r for r in _SECTION_REF_RE.findall(sec.raw_text) if r != num}
        if _sid(num) in kg.g:
            kg.g.nodes[_sid(num)]["source_page"] = sec.page_range[0]
            kg.g.nodes[_sid(num)]["properties"]["parts"] = len(sec.parts)

    # --- nodes: sheets ---
    for e in registry:
        kg.add_node(GraphNode(
            id=f"sheet:{e.sheet_number}", node_type="sheet",
            properties={"title": e.sheet_title, "discipline": e.discipline, "type": e.drawing_type},
            source_file=DRAWINGS, source_page=e.pdf_page_number, confidence=1.0,
        ))

    # --- nodes: abbreviations (only referenced materials) ---
    for code in set(MATERIAL_SECTION):
        base = code.split(" ")[0]
        if base in abbrev:
            kg.add_node(GraphNode(
                id=f"abbr:{base}", node_type="abbreviation",
                properties={"definition": abbrev[base]},
                source_file=DRAWINGS, source_page=6, confidence=1.0,
            ))

    # --- nodes: rooms ---
    for r in rooms:
        kg.add_node(GraphNode(
            id=f"room:{r.room_number}", node_type="room",
            properties={"name": r.room_name,
                        "floor": r.floor_finish, "base": r.base_finish,
                        "wall": r.wall_finish, "ceiling": r.ceiling_finish},
            source_file=DRAWINGS, source_page=49, confidence=1.0,
        ))

    # --- nodes + edges: doors ---
    for d in doors:
        did = f"door:{d.door_mark}"
        unresolved: list[str] = []
        kg.add_node(GraphNode(
            id=did, node_type="door",
            properties={"width": d.width, "height": d.height,
                        "door_material": d.door_material, "door_finish": d.door_finish,
                        "frame_material": d.frame_material, "hardware_set": d.hardware_set,
                        "glass_type": d.glass_type, "building": d.building},
            source_file=DRAWINGS, source_page=38, confidence=door_conf,
        ))

        def link_material(material: str, rel: str) -> None:
            sec = _sec(material_links, material)
            if sec and kg.find_node(_sid(sec)):
                kg.add_edge(GraphEdge(did, _sid(sec), rel, {"material": material}))
                base = material.split(" ")[0]
                if kg.find_node(f"abbr:{base}"):
                    kg.add_edge(GraphEdge(did, f"abbr:{base}", "HAS_MATERIAL", {"material": material}))
            elif material and material not in ("(E)",):
                unresolved.append(material)

        link_material(d.door_material, "DOOR_SPECIFIED_IN")
        link_material(d.frame_material, "FRAME_SPECIFIED_IN")

        if d.hardware_set and d.hardware_set.upper() != "N/A" and kg.find_node(_sid(HARDWARE_SECTION)):
            kg.add_edge(GraphEdge(did, _sid(HARDWARE_SECTION), "HARDWARE_SPECIFIED_IN",
                                  {"hardware_set": d.hardware_set}))
        if d.glass_type and d.glass_type.upper() != "N/A" and kg.find_node(_sid(GLAZING_SECTION)):
            kg.add_edge(GraphEdge(did, _sid(GLAZING_SECTION), "GLAZING_SPECIFIED_IN",
                                  {"glass_type": d.glass_type}))

        # door -> room (derive room; create a stub if it isn't in the finish schedule)
        room_id = f"room:{_room_of(d.door_mark)}"
        if not kg.find_node(room_id):
            kg.add_node(GraphNode(id=room_id, node_type="room",
                                  properties={"name": None, "derived": True},
                                  source_file=DRAWINGS, source_page=38, confidence=door_conf))
        kg.add_edge(GraphEdge(did, room_id, "LOCATED_IN", None))

        # door -> sheets (schedule sheet + overall level-1 plan; coarse by design)
        for sheet in ("A9.3.1", "A2.1.1"):
            if kg.find_node(f"sheet:{sheet}"):
                kg.add_edge(GraphEdge(did, f"sheet:{sheet}", "APPEARS_ON", None))

        if unresolved:
            kg.g.nodes[did]["properties"]["unresolved_codes"] = unresolved

    # --- edges: room -> finish sections ---
    for r in rooms:
        rid = f"room:{r.room_number}"
        unresolved: list[str] = []
        codes: set[str] = set()
        for cell in (r.floor_finish, r.base_finish, r.wall_finish, r.ceiling_finish):
            codes.update(_CODE_RE.findall(cell or ""))
        for code in codes:
            prefix = re.match(r"[A-Z]+", code)
            sec = _sec(finish_links, prefix.group()) if prefix else None
            if sec and kg.find_node(_sid(sec)):
                kg.add_edge(GraphEdge(rid, _sid(sec), "FINISH_SPECIFIED_IN", {"code": code}))
            else:
                unresolved.append(code)
        for sheet in ("AF2.4", "A2.1.1"):
            if kg.find_node(f"sheet:{sheet}"):
                kg.add_edge(GraphEdge(rid, f"sheet:{sheet}", "APPEARS_ON", None))
        if unresolved:
            if rid in kg.g:
                kg.g.nodes[rid]["properties"]["unresolved_codes"] = sorted(set(unresolved))

    # --- edges: section -> section cross references ---
    for src, refs in section_refs.items():
        for tgt in refs:
            if kg.find_node(_sid(tgt)):
                kg.add_edge(GraphEdge(_sid(src), _sid(tgt), "REFERENCES", None))

    return kg


if __name__ == "__main__":
    base = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs"
    kg = build_graph(base / "project_manual.pdf", base / "drawings.pdf")
    import json
    print(json.dumps(kg.stats(), indent=2))
    print("\n== DOOR N107B TRACE ==")
    print(json.dumps(kg.get_door_full_spec("N107B"), indent=2, ensure_ascii=False))