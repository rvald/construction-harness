"""Tier 2.1 — sheet scale resolver.

Reads the imperial architectural scale printed on a drawing sheet (`1/8" = 1'`) and
turns it into a factor: real inches per paper inch. Deterministic and fitz-only.
See docs/tier2_1_scale_resolver_design.md.

Scope: sheet-level. A sheet with one scale resolves confidently; a sheet mixing
scales (detail views) is flagged `ambiguous` — per-viewport association is deferred.
The overall floor plans that measurement needs first are single-scale.
"""
from __future__ import annotations

import re

from src.models.drawing import SheetScale

# `N/M" = D'` or `N" = D'`  (e.g. 1/8" = 1', 3/64" = 1', 1" = 20')
_SCALE_RE = re.compile(r'(\d{1,2})(?:\s*/\s*(\d{1,3}))?\s*"\s*=\s*(\d{1,3})\s*[\'′]')


def parse_scale(text: str) -> float | None:
    """Parse a scale string to a factor = real inches per paper inch, or None."""
    m = _SCALE_RE.search(text)
    if not m:
        return None
    num = int(m.group(1))
    den = int(m.group(2)) if m.group(2) else 1
    real_feet = int(m.group(3))
    paper_inches = num / den
    if paper_inches <= 0:
        return None
    return round((real_feet * 12) / paper_inches, 4)


def _canonical(text: str) -> str:
    """Normalize a matched scale string for de-duplication (collapse whitespace)."""
    return re.sub(r"\s+", "", text)


def scale_strings(page) -> list[tuple[str, float, float]]:
    """(scale_text, x, y) for every scale string on a fitz page (position = line bbox)."""
    out: list[tuple[str, float, float]] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            txt = "".join(s.get("text", "") for s in line.get("spans", []))
            for m in _SCALE_RE.finditer(txt):
                x0, y0, _, _ = line["bbox"]
                out.append((m.group(0), x0, y0))
    return out


def resolve_sheet_scale(page, pdf_page_number: int) -> SheetScale:
    """Resolve one sheet's scale. Confident on a single scale; ambiguous on several."""
    found = scale_strings(page)
    if not found:
        return SheetScale(pdf_page_number, None, "", 0.0, False, [])

    # de-dupe by canonical form, preserving first-seen display text
    distinct: dict[str, str] = {}
    for text, _, _ in found:
        distinct.setdefault(_canonical(text), text)
    labels = list(distinct.values())

    if len(labels) == 1:
        return SheetScale(pdf_page_number, parse_scale(labels[0]), labels[0], 1.0, False, labels)
    # multiple distinct scales -> per-viewport association needed (deferred)
    return SheetScale(pdf_page_number, None, "", 0.4, True, labels)
