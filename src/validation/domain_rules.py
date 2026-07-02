"""Construction-specific business rules (Milestone 12).

These complement the structural phase gates with domain sanity checks on the
assembled graph: things a construction estimator would expect to hold.
"""
from __future__ import annotations

from src.models.graph import KnowledgeGraph
from src.validation.gates import GateResult, _g


def _doors(kg: KnowledgeGraph) -> list[dict]:
    return [d["properties"] for _, d in kg.g.nodes(data=True) if d["node_type"] == "door"]


def _rooms(kg: KnowledgeGraph) -> list[dict]:
    return [d["properties"] for _, d in kg.g.nodes(data=True)
            if d["node_type"] == "room" and not d["properties"].get("derived")]


def check_domain_rules(kg: KnowledgeGraph) -> list[GateResult]:
    doors = _doors(kg)
    rooms = _rooms(kg)
    results: list[GateResult] = []

    if doors:
        with_hw = sum(1 for d in doors if d.get("hardware_set") and d["hardware_set"].upper() != "N/A")
        rate = with_hw / len(doors)
        results.append(_g("doors_have_hardware_set", rate >= 0.9,
                          f"{with_hw}/{len(doors)} doors have a hardware set ({rate:.1%})", round(rate, 3)))

        with_frame = sum(1 for d in doors if d.get("frame_material"))
        rate = with_frame / len(doors)
        results.append(_g("doors_have_frame_material", rate >= 0.9,
                          f"{with_frame}/{len(doors)} doors specify a frame material ({rate:.1%})", round(rate, 3)))

    if rooms:
        with_floor = sum(1 for r in rooms if r.get("floor"))
        rate = with_floor / len(rooms)
        results.append(_g("rooms_have_floor_finish", rate >= 0.9,
                          f"{with_floor}/{len(rooms)} rooms have a floor finish ({rate:.1%})", round(rate, 3)))

    return results