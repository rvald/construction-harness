"""Phase-boundary validation gates (Milestone 12).

Each gate returns a GateResult (pass/fail + a human-readable detail + a metric).
Gates formalize the checks we validated ad hoc while building Milestones 3-11.

Note on the Phase 5 "no isolated nodes" check: most spec sections are legitimately
unreferenced by any door/room (they cover MEP, structural, etc.), so treating every
isolated node as a failure would be wrong. The pass/fail gate is therefore ELEMENT
connectivity (every door and room has an edge); the count of isolated nodes overall
is reported as an informational metric.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.models.graph import KnowledgeGraph
from src.models.base import JsonModel


@dataclass
class GateResult(JsonModel):
    name: str
    passed: bool
    detail: str
    metric: float | int | None = None


def _g(name: str, passed: bool, detail: str, metric=None) -> GateResult:
    return GateResult(name=name, passed=passed, detail=detail, metric=metric)


# --- Phase 2 -------------------------------------------------------------

def check_phase2(toc, door_count: int, room_count: int, abbrev_count: int) -> list[GateResult]:
    divisions = [d["number"] for d in toc.divisions]
    return [
        _g("toc_section_count", toc.total_sections >= 100,
           f"{toc.total_sections} sections (expected >= 100)", toc.total_sections),
        _g("all_divisions_present", len(divisions) == 24,
           f"{len(divisions)} divisions (expected 24)", len(divisions)),
        _g("door_schedule_size", door_count > 50,
           f"{door_count} doors (expected > 50)", door_count),
        _g("finish_schedule_size", room_count > 25,
           f"{room_count} rooms (expected > 25)", room_count),
        _g("abbreviation_list_size", abbrev_count > 100,
           f"{abbrev_count} abbreviations (expected > 100)", abbrev_count),
    ]


# --- Phase 3 -------------------------------------------------------------

def check_phase3(registry, reconciliation: list[dict]) -> list[GateResult]:
    disciplines = {e.discipline for e in registry}
    all_found = all(r["in_registry"] for r in reconciliation)
    pages_ok = all(r["page_matches"] for r in reconciliation)
    return [
        _g("sheet_count", len(registry) == 133,
           f"{len(registry)} sheets (expected 133)", len(registry)),
        _g("all_disciplines_present", len(disciplines) >= 9,
           f"{len(disciplines)} disciplines represented", len(disciplines)),
        _g("sample_sheets_classified", all_found,
           f"{sum(r['in_registry'] for r in reconciliation)}/{len(reconciliation)} sample sheets in registry"),
        _g("sample_page_numbers_verified", pages_ok,
           f"{sum(r['page_matches'] for r in reconciliation)}/{len(reconciliation)} sample page numbers match"),
    ]


# --- Phase 5 -------------------------------------------------------------

def _rate(kg: KnowledgeGraph, node_type: str, rels: tuple[str, ...]) -> tuple[int, int]:
    nodes = [n for n, d in kg.g.nodes(data=True) if d["node_type"] == node_type]
    resolved = sum(1 for n in nodes if any(r in rels for _, r, _ in kg._out(n)))
    return resolved, len(nodes)


def check_phase5(kg: KnowledgeGraph) -> list[GateResult]:
    door_res, door_n = _rate(kg, "door",
                             ("DOOR_SPECIFIED_IN", "FRAME_SPECIFIED_IN",
                              "HARDWARE_SPECIFIED_IN", "GLAZING_SPECIFIED_IN"))
    room_res, room_n = _rate(kg, "room", ("FINISH_SPECIFIED_IN",))
    door_rate = door_res / door_n if door_n else 0.0
    room_rate = room_res / room_n if room_n else 0.0

    # element connectivity: every door + room has at least one edge
    elements = [n for n, d in kg.g.nodes(data=True) if d["node_type"] in ("door", "room")]
    isolated_elements = [n for n in elements if kg.g.degree(n) == 0]
    isolated_total = [n for n in kg.g.nodes() if kg.g.degree(n) == 0]

    return [
        _g("element_connectivity", not isolated_elements,
           f"{len(isolated_elements)} isolated element nodes "
           f"({len(isolated_total)} isolated nodes total, mostly unreferenced specs/sheets)",
           len(isolated_elements)),
        _g("door_to_spec_rate", door_rate >= 0.9,
           f"{door_res}/{door_n} doors resolve to a spec ({door_rate:.1%})", round(door_rate, 3)),
        _g("room_to_finish_rate", room_rate >= 0.9,
           f"{room_res}/{room_n} rooms resolve finishes ({room_rate:.1%})", round(room_rate, 3)),
    ]


def confidence_distribution(kg: KnowledgeGraph) -> dict:
    confs = [d["confidence"] for _, d in kg.g.nodes(data=True)]
    buckets = Counter("1.0" if c >= 0.999 else "0.9-1.0" if c >= 0.9 else "<0.9" for c in confs)
    return {
        "min": round(min(confs), 3), "max": round(max(confs), 3),
        "mean": round(sum(confs) / len(confs), 3), "buckets": dict(buckets),
    }


# --- report --------------------------------------------------------------

def build_report(kg, toc, registry, doors, rooms, abbrev_count, reconciliation) -> dict:
    """Assemble the full validation report from already-parsed inputs + graph."""
    from src.validation.domain_rules import check_domain_rules

    gates = (
        [{"phase": "phase2", **r.to_dict()} for r in check_phase2(toc, len(doors), len(rooms), abbrev_count)]
        + [{"phase": "phase3", **r.to_dict()} for r in check_phase3(registry, reconciliation)]
        + [{"phase": "phase5", **r.to_dict()} for r in check_phase5(kg)]
        + [{"phase": "domain", **r.to_dict()} for r in check_domain_rules(kg)]
    )
    door_res, door_n = _rate(kg, "door",
                             ("DOOR_SPECIFIED_IN", "FRAME_SPECIFIED_IN",
                              "HARDWARE_SPECIFIED_IN", "GLAZING_SPECIFIED_IN"))
    room_res, room_n = _rate(kg, "room", ("FINISH_SPECIFIED_IN",))
    orphan_specs = kg.find_orphan_specs()

    return {
        "all_gates_passed": all(g["passed"] for g in gates),
        "gates": gates,
        "graph_stats": kg.stats(),
        "connection_rates": {
            "door_to_spec": round(door_res / door_n, 3) if door_n else 0.0,
            "room_to_finish": round(room_res / room_n, 3) if room_n else 0.0,
        },
        "unresolved": {
            "orphan_doors": kg.find_orphan_doors(),
            "orphan_spec_count": len(orphan_specs),
            "orphan_spec_sample": orphan_specs[:10],
            "missing_connections": kg.find_missing_connections(),
        },
        "confidence": confidence_distribution(kg),
    }


def run_all(manual_path, drawings_path) -> dict:
    """Parse every phase, build the graph, run all gates, and return the report."""
    from src.pipeline.phase2_abbreviation_parser import parse_abbreviations
    from src.pipeline.phase2_drawing_index import parse_drawing_index
    from src.pipeline.phase2_schedule_parser import parse_door_schedule, parse_finish_schedule
    from src.pipeline.phase2_spec_parser import parse_spec_toc
    from src.pipeline.phase3_sheet_classifier import classify_sheets, reconcile
    from src.pipeline.phase5_graph_builder import build_graph

    toc = parse_spec_toc(manual_path)
    registry = parse_drawing_index(drawings_path)
    doors = parse_door_schedule(drawings_path)
    rooms = parse_finish_schedule(drawings_path)
    abbrev_count = len(parse_abbreviations(drawings_path))
    reconciliation = reconcile(classify_sheets(drawings_path), registry)
    kg = build_graph(manual_path, drawings_path)

    return build_report(kg, toc, registry, doors, rooms, abbrev_count, reconciliation)


if __name__ == "__main__":
    import json
    import pathlib

    base = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs"
    report = run_all(base / "project_manual.pdf", base / "drawings.pdf")

    print(f"ALL GATES PASSED: {report['all_gates_passed']}\n")
    for g in report["gates"]:
        mark = "PASS" if g["passed"] else "FAIL"
        print(f"  [{mark}] {g['phase']:<7} {g['name']:<28} {g['detail']}")
    print("\nconnection rates:", report["connection_rates"])
    print("confidence      :", report["confidence"])
    print(f"orphan specs    : {report['unresolved']['orphan_spec_count']} "
          f"| missing connections: {len(report['unresolved']['missing_connections'])}")

    out = pathlib.Path(__file__).resolve().parents[2] / "output" / "reports" / "validation_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nwrote {out}")