"""Phase 4 — Binary Drawing Extraction (Milestone 10), using PyMuPDF (fitz).

This is the exploratory, most-uncertain phase: the goal is to learn what the
binary/vector layer of a floor plan yields, not to build a production extractor.

Source: drawings PDF, page 14 (sheet A2.1.1 — Level 1 Floor Plan Overall).

Requires PyMuPDF:  pip install PyMuPDF        (imports as `fitz`)
Run:               python -m src.takeoff.binary_extractor

Why fitz here (and not pdfplumber): this phase is specifically about the binary
layer. fitz exposes glyph-level text with writing direction (get_text("dict"))
and the actual vector path operators (get_drawings()) — the raw geometry the
hypothesis is about. pdfplumber's object model only approximates those.

Findings (page 14, from a real fitz run) — the learning this milestone exists for:
  * Text: ~298 spans. Cleanly recoverable: dimension strings (e.g. "266' - 0\" VIF"),
    grid labels on BOTH axes (numeric S-1..S-8 / N-1..N-7 and lettered S-A..S-G /
    N-A..), and sheet cross-references ("SHEET A2.1.2", "A8.1.2").
  * Door marks are NOT in the text layer of the floor plan (0 recovered). On the
    plan they are graphical/rotated fragments, so the door schedule (Milestone 7)
    remains the authoritative source for door marks.
  * All text is rotated (writing direction 180 / 270 degrees): positional reasoning
    must account for the sheet rotation.
  * Geometry: ~40k vector primitives, overwhelmingly lines (~37k), the vast majority
    axis-aligned (walls + grid). Curves are rare (~12).
  * The drawing border is NOT a single rectangle primitive; it is composed of long
    line segments (border_bbox is None; ~8 long-line/grid candidates).
  * Conclusion: the binary layer is strong for geometry and structured text
    (dimensions, grids, references) but weak for semantic linkage (door marks,
    room-to-element association). Schedules/specs carry the semantics; the binary
    layer carries geometry. This supports sourcing the graph's semantic edges from
    Phases 2-3 rather than from floor-plan binary data.
"""
from __future__ import annotations

import math
import pathlib
import re
from typing import Any, cast

import fitz  # PyMuPDF

from src.models.drawing import GeometricPrimitive, TextObject

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"
_PAGE_INDEX = 13  # 0-indexed -> PDF page 14 (A2.1.1)


# --- text classification -------------------------------------------------

_GRID_RE = re.compile(r"[NS]-[A-Z0-9]{1,2}|[A-K]|[1-8]")
_DOOR_RE = re.compile(r"^[NS]\d{3}[A-Z]?$")
_SHEET_REF_RE = re.compile(r"^(?:SHEET\s+)?[A-Z]{1,3}\d+\.\d+(?:\.\d+)*$")
_DIM_RE = re.compile(r"\d+'")
_ROOM_RE = re.compile(r"^[A-Z][A-Z0-9 &/().\-]{2,}$")


def classify(text: str) -> str:
    """Assign a probable type to a text token (priority order matters)."""
    t = text.strip()
    if not t:
        return "blank"
    if _GRID_RE.fullmatch(t):
        return "grid_label"
    if _DOOR_RE.match(t):
        return "door_mark"
    if _SHEET_REF_RE.match(t):
        return "sheet_reference"
    if _DIM_RE.search(t):
        return "dimension"
    if _ROOM_RE.match(t):
        return "room_name"
    return "unknown"


def _rotation_from_dir(direction: tuple[float, float]) -> int:
    """Normalize a fitz writing-direction vector to 0/90/180/270 degrees."""
    angle = math.degrees(math.atan2(direction[1], direction[0]))
    return int(round(angle / 90.0) * 90) % 360


# --- extraction ----------------------------------------------------------

def extract_text_objects(page: "fitz.Page") -> list[TextObject]:
    objects: list[TextObject] = []
    data = cast(dict[str, Any], page.get_text("dict"))
    for block in data.get("blocks", []):
        if block.get("type", 0) != 0:      # 0 = text block; 1 = image
            continue
        for line in block.get("lines", []):
            rotation = _rotation_from_dir(line.get("dir", (1.0, 0.0)))
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                x0, y0, x1, y1 = span["bbox"]
                objects.append(TextObject(
                    text=text.strip(),
                    x0=x0, y0=y0, x1=x1, y1=y1,
                    font=span.get("font", ""),
                    size=round(span.get("size", 0.0), 2),
                    rotation=rotation,
                    classification=classify(text),
                ))
    return objects


def extract_geometry(page: "fitz.Page") -> list[GeometricPrimitive]:
    prims: list[GeometricPrimitive] = []
    for path in cast(list[dict[str, Any]], page.get_drawings()):
        width = path.get("width")
        for item in path.get("items", []):
            op = item[0]
            if op == "l":                                   # line: two Points
                p1, p2 = item[1], item[2]
                prims.append(GeometricPrimitive("line",
                    min(p1.x, p2.x), min(p1.y, p2.y), max(p1.x, p2.x), max(p1.y, p2.y), width))
            elif op == "c":                                 # cubic Bezier: four Points
                pts = item[1:5]
                xs = [p.x for p in pts]; ys = [p.y for p in pts]
                prims.append(GeometricPrimitive("curve",
                    min(xs), min(ys), max(xs), max(ys), width))
            elif op == "re":                                # rectangle: one Rect
                r = item[1]
                prims.append(GeometricPrimitive("rect", r.x0, r.y0, r.x1, r.y1, width))
            elif op == "qu":                                # quad: one Quad
                r = item[1].rect
                prims.append(GeometricPrimitive("quad", r.x0, r.y0, r.x1, r.y1, width))
    return prims


# --- exploratory geometry analysis --------------------------------------

def _length(p: GeometricPrimitive) -> float:
    return math.hypot(p.x1 - p.x0, p.y1 - p.y0)


def analyze_geometry(prims: list[GeometricPrimitive], page_rect: "fitz.Rect") -> dict:
    """Cheap, exploratory pattern signals — not a production classifier."""
    from collections import Counter

    by_kind = dict(Counter(p.kind for p in prims))
    span = min(page_rect.width, page_rect.height)
    lines = [p for p in prims if p.kind == "line"]

    grid_candidates = sum(1 for p in lines if _length(p) > 0.6 * span)
    axis_aligned = sum(1 for p in lines
                       if abs(p.x1 - p.x0) < 1 or abs(p.y1 - p.y0) < 1)

    # border = the rect covering most of the page
    page_area = page_rect.width * page_rect.height
    border = None
    best = 0.0
    for p in prims:
        if p.kind in ("rect", "quad"):
            area = abs(p.x1 - p.x0) * abs(p.y1 - p.y0)
            if area > 0.6 * page_area and area > best:
                best, border = area, (round(p.x0), round(p.y0), round(p.x1), round(p.y1))

    return {
        "total_primitives": len(prims),
        "by_kind": by_kind,
        "long_lines_grid_candidates": grid_candidates,
        "axis_aligned_line_segments": axis_aligned,
        "border_bbox": border,
    }


def extract_page(pdf_path: str | pathlib.Path = _DEFAULT_PDF, page_index: int = _PAGE_INDEX):
    """Return (text_objects, primitives, geometry_analysis) for a page."""
    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_index]
        texts = extract_text_objects(page)
        prims = extract_geometry(page)
        analysis = analyze_geometry(prims, page.rect)
    return texts, prims, analysis


if __name__ == "__main__":
    from collections import Counter

    texts, prims, analysis = extract_page()

    print(f"== TEXT OBJECTS ({len(texts)}) ==")
    for cls, n in sorted(Counter(t.classification for t in texts).items(), key=lambda x: -x[1]):
        print(f"  {cls:<16}{n}")
    for cls in ("grid_label", "room_name", "dimension", "door_mark", "sheet_reference"):
        sample = [t.text for t in texts if t.classification == cls][:8]
        print(f"  e.g. {cls:<16}{sample}")

    print(f"\n== GEOMETRY ==")
    for k, v in analysis.items():
        print(f"  {k}: {v}")

    print("\n== OBSERVATIONS (fill in from this run) ==")
    print("  - text rotations seen:", sorted({t.rotation for t in texts}))
    print("  - door marks recoverable from binary text layer?",
          "YES" if any(t.classification == "door_mark" for t in texts) else "NO (see notes)")

    # Persist a summary artifact (matches the other milestones' output pattern).
    import json

    out = pathlib.Path(__file__).resolve().parents[2] / "output" / "reports" / "binary_extraction_page14.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "page": _PAGE_INDEX + 1,
        "text_object_count": len(texts),
        "classification_counts": dict(Counter(t.classification for t in texts)),
        "text_rotations": sorted({t.rotation for t in texts}),
        "geometry": analysis,
        "text_objects": [t.to_dict() for t in texts],
    }, indent=2, ensure_ascii=False))
    print(f"\nwrote {out}")