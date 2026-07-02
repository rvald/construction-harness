"""Exploration probe #2 — Drawings PDF, focused on the page-2 drawing index.

Milestone 5 parses the drawing index (sheet G1.1, PDF page 2) into 133 SheetEntry
records. The spec warns the drawings may be rotated and their tables vector-drawn
(resisting extract_tables()). Look before parsing.

Run:  python -m notebooks.02_explore_drawings   (or: python notebooks/02_explore_drawings.py from repo root won't work — no src import, so plain path is fine)
"""
from __future__ import annotations

import pathlib

import pdfplumber

PDF = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"

# Pages the spec calls out as exploration targets (1-indexed): index, abbrev, floor plan, door schedule.
KEY_PAGES = {2: "drawing index (G1.1)", 6: "abbreviations (A0.1)",
             14: "floor plan", 38: "door schedule (A9.3.1?)"}


def rule(t: str) -> None:
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def explore() -> None:
    with pdfplumber.open(PDF) as pdf:
        rule("DOCUMENT OVERVIEW")
        print(f"page_count : {len(pdf.pages)}")
        for pno, label in KEY_PAGES.items():
            if pno - 1 < len(pdf.pages):
                p = pdf.pages[pno - 1]
                print(f"  page {pno:>3} ({label:<24}): {p.width:.0f}x{p.height:.0f}pt "
                      f"({p.width/72:.1f}x{p.height/72:.1f}in)  rotation={getattr(p,'rotation',0)}  "
                      f"chars={len(p.chars)} lines={len(p.lines)} rects={len(p.rects)} curves={len(p.curves)}")

        # --- Page 2: can pdfplumber find the index table at all? ---
        page = pdf.pages[1]
        rule("PAGE 2 — extract_tables() with default settings")
        tables = page.extract_tables()
        print(f"tables found: {len(tables)}")
        for ti, t in enumerate(tables):
            print(f"  table {ti}: {len(t)} rows x {len(t[0]) if t else 0} cols; first rows:")
            for row in t[:4]:
                print("   ", row)

        # --- Fallback view: is the index just positioned text (vector table)? ---
        rule("PAGE 2 — raw text (first 60 lines)")
        text = page.extract_text() or ""
        for line in text.splitlines()[:60]:
            print("  ", line)

        # --- Look specifically for sheet-number-like tokens to gauge structure ---
        rule("PAGE 2 — lines containing a sheet-number pattern (e.g. A2.1.1)")
        import re
        sheet_re = re.compile(r"\b([A-Z]{1,3}\d+(?:\.\d+){0,3})\b")
        hits = 0
        for line in text.splitlines():
            if sheet_re.search(line):
                print("  ", line)
                hits += 1
        print(f"...{hits} candidate lines")


if __name__ == "__main__":
    explore()