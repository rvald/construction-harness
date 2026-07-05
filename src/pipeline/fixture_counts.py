"""Tier 3.1 M1 — deterministic fixture-tag counting (extraction stage).

Fixture tags are in the text layer on the plumbing sheets (M0 spike), so counting is
text-based, not vector/template symbol matching. This produces per-SHEET candidate
counts for the Tier 1 fixture catalog; it does NOT dedupe across overall/enlarged
views into a building total — that (and inflation from legend/schedule blocks) is what
the VLM verifier reconciles. See docs/tier3_symbol_counting_design.md.

Legend/schedule blocks (many tags packed into a small region, e.g. an embedded fixture
schedule) are excluded here by a spatial-spread test: instance tags scatter across the
sheet; a schedule/legend clusters. A page carrying both would over-count — the verifier
catches that.
"""
from __future__ import annotations

from src.models.schedule import CountResult

# a page is an "instance plan" if its tags span at least this fraction of the sheet
_SPREAD_THRESHOLD = 0.35
_MIN_TAGS = 3


def tag_spans(page, tags: set[str]) -> dict[str, list[tuple[float, float]]]:
    """{tag: [(cx, cy), ...]} for exact catalog-tag tokens on a fitz page."""
    out: dict[str, list[tuple[float, float]]] = {}
    for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        w = word.strip()
        if w in tags:
            out.setdefault(w, []).append(((x0 + x1) / 2, (y0 + y1) / 2))
    return out


def _spread_fraction(points: list[tuple[float, float]], width: float, height: float) -> float:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return max((max(xs) - min(xs)) / width, (max(ys) - min(ys)) / height)


def classify_page(points: list[tuple[float, float]], width: float, height: float) -> str:
    """"instance_plan" (tags scattered) | "legend_block" (tags clustered) | "sparse"."""
    if len(points) < _MIN_TAGS:
        return "sparse"
    return "instance_plan" if _spread_fraction(points, width, height) >= _SPREAD_THRESHOLD else "legend_block"


def extract_counts(pdf_path, tags, page_range=None) -> list[CountResult]:
    """Per-sheet fixture-tag counts over a page range (instance plans only)."""
    import fitz

    tagset = set(tags)
    out: list[CountResult] = []
    with fitz.open(str(pdf_path)) as doc:
        rng = page_range if page_range is not None else range(doc.page_count)
        for i in rng:
            page = doc[i]
            spans = tag_spans(page, tagset)
            points = [p for pts in spans.values() for p in pts]
            if classify_page(points, page.rect.width, page.rect.height) != "instance_plan":
                continue
            for tag, pts in spans.items():
                out.append(CountResult(
                    symbol_id=tag,
                    sheet_page=i + 1,
                    count=len(pts),
                    boxes=[[round(x, 1), round(y, 1)] for x, y in pts],
                ))
    return out


def summarize_counts(counts: list[CountResult]) -> dict:
    """Reported metrics — per-symbol candidate totals (NOT deduped; dedup pending
    verification), plus which sheets each was counted on."""
    from collections import defaultdict

    per_symbol: dict[str, dict] = defaultdict(lambda: {"candidate_total": 0, "sheets": []})
    for c in counts:
        e = per_symbol[c.symbol_id]
        e["candidate_total"] += c.count
        e["sheets"].append({"page": c.sheet_page, "count": c.count})
    return {
        "symbols_counted": len(per_symbol),
        "instance_sheets": sorted({c.sheet_page for c in counts}),
        "dedup_status": "pending_verification",       # candidate totals may double-count across views
        "by_symbol": dict(per_symbol),
    }
