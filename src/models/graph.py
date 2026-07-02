"""Knowledge graph models (Milestone 11).

GraphNode / GraphEdge are the serializable records; KnowledgeGraph wraps a
networkx MultiDiGraph (parallel edges allowed, since a door relates to several
sections via different relationships) and provides the spec's query methods.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from .base import JsonModel


@dataclass
class GraphNode(JsonModel):
    """A node in the knowledge graph."""

    id: str
    node_type: str                              # spec_section | door | room | sheet | abbreviation
    properties: dict = field(default_factory=dict)
    source_file: str = ""
    source_page: int | None = None
    confidence: float = 1.0


@dataclass
class GraphEdge(JsonModel):
    """A relationship in the knowledge graph."""

    source_id: str
    target_id: str
    relationship: str                           # DOOR_SPECIFIED_IN | LOCATED_IN | ...
    properties: dict | None = None


class KnowledgeGraph:
    """Project knowledge graph backed by networkx."""

    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()

    # --- construction ---------------------------------------------------

    def add_node(self, node: GraphNode) -> None:
        self.g.add_node(
            node.id,
            node_type=node.node_type,
            properties=node.properties,
            source_file=node.source_file,
            source_page=node.source_page,
            confidence=node.confidence,
        )

    def add_edge(self, edge: GraphEdge) -> None:
        self.g.add_edge(
            edge.source_id, edge.target_id,
            key=edge.relationship,
            relationship=edge.relationship,
            properties=edge.properties or {},
        )

    # --- lookups --------------------------------------------------------

    def find_node(self, node_id: str) -> dict | None:
        return dict(self.g.nodes[node_id]) if node_id in self.g else None

    def _nodes_of_type(self, node_type: str) -> list[str]:
        return [n for n, d in self.g.nodes(data=True) if d.get("node_type") == node_type]

    def _out(self, node_id: str) -> list[tuple[str, str, dict]]:
        """Outgoing edges as (target_id, relationship, properties)."""
        if node_id not in self.g:
            return []
        return [(t, d["relationship"], d.get("properties", {}))
                for _, t, d in self.g.out_edges(node_id, data=True)]

    def _section_ref(self, section_id: str) -> dict | None:
        node = self.find_node(section_id)
        if not node:
            return None
        return {
            "section": section_id.split(":", 1)[-1],
            "title": node["properties"].get("title"),
            "source_file": node["source_file"],
            "source_page": node["source_page"],
        }

    # --- validation queries (per spec) ---------------------------------

    def get_door_full_spec(self, door_mark: str) -> dict:
        """All spec sections connected to a door, grouped by relationship."""
        did = f"door:{door_mark}"
        node = self.find_node(did)
        if not node:
            return {"door_mark": door_mark, "found": False}

        rel_to_key = {
            "DOOR_SPECIFIED_IN": "door_spec",
            "FRAME_SPECIFIED_IN": "frame_spec",
            "HARDWARE_SPECIFIED_IN": "hardware_spec",
            "GLAZING_SPECIFIED_IN": "glazing_spec",
        }
        result: dict[str, Any] = {"door_mark": door_mark, "found": True,
                                  "properties": node["properties"]}
        for key in rel_to_key.values():
            result[key] = None
        result["room"] = None
        result["sheets"] = []

        for target, rel, _props in self._out(did):
            if rel in rel_to_key:
                result[rel_to_key[rel]] = self._section_ref(target)
            elif rel == "LOCATED_IN":
                result["room"] = target.split(":", 1)[-1]
            elif rel == "APPEARS_ON":
                result["sheets"].append(target.split(":", 1)[-1])
        return result

    def get_room_full_spec(self, room_number: str) -> dict:
        """Finish spec sections for a room + specs for doors located in it."""
        rid = f"room:{room_number}"
        node = self.find_node(rid)
        if not node:
            return {"room_number": room_number, "found": False}

        finishes = [self._section_ref(t) for t, rel, _ in self._out(rid)
                    if rel == "FINISH_SPECIFIED_IN"]
        doors = [s.split(":", 1)[-1] for s, _t, d in self.g.in_edges(rid, data=True)
                 if d["relationship"] == "LOCATED_IN"]
        return {
            "room_number": room_number, "found": True,
            "properties": node["properties"],
            "finish_specs": [f for f in finishes if f],
            "doors": doors,
        }

    def find_orphan_doors(self) -> list[str]:
        """Doors not connected to any room."""
        orphans = []
        for did in self._nodes_of_type("door"):
            if not any(rel == "LOCATED_IN" for _, rel, _ in self._out(did)):
                orphans.append(did.split(":", 1)[-1])
        return orphans

    def find_orphan_specs(self) -> list[str]:
        """Spec sections with no incoming edge from any element."""
        orphans = []
        for sid in self._nodes_of_type("spec_section"):
            if self.g.in_degree(sid) == 0:
                orphans.append(sid.split(":", 1)[-1])
        return orphans

    def find_missing_connections(self) -> list[dict]:
        """Elements carrying material/finish codes that did not resolve to a section."""
        missing = []
        for n, d in self.g.nodes(data=True):
            unresolved = d.get("properties", {}).get("unresolved_codes")
            if unresolved:
                missing.append({"id": n, "node_type": d["node_type"], "codes": unresolved})
        return missing

    # --- stats / export -------------------------------------------------

    def stats(self) -> dict:
        from collections import Counter
        node_types = Counter(d["node_type"] for _, d in self.g.nodes(data=True))
        edge_types = Counter(d["relationship"] for _, _, d in self.g.edges(data=True))
        return {
            "total_nodes": self.g.number_of_nodes(),
            "total_edges": self.g.number_of_edges(),
            "nodes_by_type": dict(node_types),
            "edges_by_type": dict(edge_types),
        }

    def to_dict(self) -> dict:
        nodes = [{"id": n, **{k: v for k, v in d.items()}} for n, d in self.g.nodes(data=True)]
        edges = [{"source_id": s, "target_id": t, "relationship": d["relationship"],
                  "properties": d.get("properties", {})}
                 for s, t, d in self.g.edges(data=True)]
        return {"nodes": nodes, "edges": edges, "stats": self.stats()}