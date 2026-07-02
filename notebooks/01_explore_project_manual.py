"""Milestone 1 exploration — Project Manual (specifications PDF).

Goal: look at the RAW text before writing any parser, so Milestones 3 (TOC parser)
and 4 (section parser) are built against reality, not the spec's estimates.

Run:  python notebooks/01_explore_project_manual.py

We do not hardcode the spec's "pages 5-10" guess. Instead we scan the front matter,
detect where the table of contents actually lives, dump its raw text, then locate a
known section (081113) and preview its Part 1/2/3 structure.
"""
from __future__ import annotations

import pathlib
import re

import pdfplumber

PDF_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "project_manual.pdf"

SCAN_FRONT_MATTER = 16     # how many leading pages to sniff for the TOC
SECTION_SEARCH_WINDOW = range(300, 420)  # where 081113 is expected to live


def rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def explore() -> None:
    print(f"Opening: {PDF_PATH}")
    with pdfplumber.open(PDF_PATH) as pdf:
        rule("DOCUMENT OVERVIEW")
        p0 = pdf.pages[0]
        print(f"page_count        : {len(pdf.pages)}")
        print(f"page[0] size (pt) : {p0.width:.1f} x {p0.height:.1f}  "
              f"({p0.width/72:.2f}in x {p0.height/72:.2f}in)")
        print(f"page[0] rotation  : {getattr(p0, 'rotation', 0)}")

        # --- Locate the TOC by sniffing front matter for division/section markers ---
        rule(f"TOC DETECTION (scanning first {SCAN_FRONT_MATTER} pages)")
        toc_pages: list[int] = []
        for i in range(min(SCAN_FRONT_MATTER, len(pdf.pages))):
            text = pdf.pages[i].extract_text() or ""
            has_toc_title = "TABLE OF CONTENTS" in text.upper()
            n_div = len(re.findall(r"\bDIVISION\s+\d", text, re.I))
            n_sec = len(re.findall(r"\bSECTION\s+\d{5,6}", text, re.I))
            marker = "  <-- TOC?" if (n_div + n_sec) >= 3 or has_toc_title else ""
            print(f"  page {i+1:>3} (1-idx): "
                  f"toc_title={has_toc_title!s:>5}  divisions={n_div:>2}  sections={n_sec:>2}{marker}")
            if (n_div + n_sec) >= 3 or has_toc_title:
                toc_pages.append(i)

        # --- Dump raw text of the detected TOC pages so we can see real patterns ---
        if toc_pages:
            rule(f"RAW TOC TEXT (pages {[p+1 for p in toc_pages]}, 1-indexed)")
            for i in toc_pages:
                print(f"\n----- page {i+1} -----")
                print(pdf.pages[i].extract_text() or "<no text>")
        else:
            print("\n!! No TOC-like page found in front matter; widen SCAN_FRONT_MATTER.")

        # --- Locate a known spec section and preview its structure ---
        rule("LOCATING SECTION 081113 (Hollow Metal Doors and Frames)")
        hit_page = None
        for i in SECTION_SEARCH_WINDOW:
            if i >= len(pdf.pages):
                break
            text = pdf.pages[i].extract_text() or ""
            if re.search(r"SECTION\s+081113", text):
                hit_page = i
                break
        if hit_page is None:
            print(f"  Not found in window {SECTION_SEARCH_WINDOW.start}-{SECTION_SEARCH_WINDOW.stop}; "
                  "adjust SECTION_SEARCH_WINDOW.")
        else:
            print(f"  Found 'SECTION 081113' on page {hit_page+1} (1-indexed).")
            rule(f"SECTION 081113 PREVIEW (pages {hit_page+1}-{hit_page+2})")
            for i in (hit_page, hit_page + 1):
                if i < len(pdf.pages):
                    print(f"\n----- page {i+1} -----")
                    print(pdf.pages[i].extract_text() or "<no text>")


if __name__ == "__main__":
    explore()