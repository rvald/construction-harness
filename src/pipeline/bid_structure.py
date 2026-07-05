"""Bid structure — Division 00/01 alternates / unit prices / allowances.

Fills the categorical gap the earlier assessment flagged at zero: how the bid is
organized and priced. The item definitions live in the standard CSI Division-01
pricing sections of the project manual (012300 Alternates, 012200 Unit Prices,
012100 Allowances), which use the ordinary spec grammar — so this is text
extraction over located section bodies, not a new parser.

Deterministic and fitz-only. Absent sections degrade and are flagged (Pinney has
no formal Div-01 pricing sections); nothing is faked.

Measured shape (UCCS 012300):
    PART 3 - EXECUTION / 3.1 SCHEDULE OF ALTERNATES
      A. Alternate No. 1: Bench Millwork.
         1. Base Bid: Provide built-in millwork benches ...
         2. Deductive Alternate: Delete two (2) ...
"""
from __future__ import annotations

import pathlib
import re

import fitz

from src.models.schedule import BidItem

_SECTION_HEADER = re.compile(r"SECTION\s+(\d{6})\s*[-–]")
_ALT = re.compile(r"Alternate\s+No\.?\s*(\d+)\s*:\s*([^\n]+)", re.I)
_UP = re.compile(r"Unit Price\s+No\.?\s*(\d+)\s*:\s*([^\n]+)", re.I)
_ALLOW = re.compile(r"Allowance\s+No\.?\s*(\d+)\s*:\s*([^\n]+)", re.I)
_BASE_BID = re.compile(r"Base Bid\s*:\s*([^\n]+)", re.I)
_DESC = re.compile(r"Description\s*:\s*([^\n]+)", re.I)
_UOM = re.compile(r"Unit of Measurement\s*:\s*([^\n]+)", re.I)
_DEDUCT = re.compile(r"Deductive\s+Alternate", re.I)
_ADD = re.compile(r"Add(itive)?\s+Alternate", re.I)


def _spans(marks: list, text: str):
    """Yield (match, body_text_until_next_match) for enumerated 'X No. N:' items."""
    for idx, m in enumerate(marks):
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(text)
        yield m, text[m.end():end]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def section_text(doc, section_number: str, max_pages: int = 6) -> tuple[str | None, int | None]:
    """Return (joined text, 1-indexed start page) for a spec section BODY, or (None, None).

    Locates the section by its header near the top of a page (skipping the TOC listing),
    then reads forward until the next section header or `max_pages`."""
    def head_of(text: str) -> str:
        # first 8 NON-BLANK lines (headers sit past blank lines / title block)
        return " ".join([l.strip() for l in text.splitlines() if l.strip()][:8]).upper()

    start = None
    for i in range(doc.page_count):
        head = head_of(doc[i].get_text())
        if f"SECTION {section_number}" in head and "TABLE OF CONTENTS" not in head:
            start = i
            break
    if start is None:
        return None, None
    texts = []
    for i in range(start, min(start + max_pages, doc.page_count)):
        t = doc[i].get_text()
        if i > start:
            m = _SECTION_HEADER.search(head_of(t))
            if m and m.group(1) != section_number:      # next section began
                break
        texts.append(t)
    return "\n".join(texts), start + 1


def parse_alternates(text: str, source: dict | None = None) -> list[BidItem]:
    """Parse the 'Schedule of Alternates' into BidItems (number, title, add/deduct)."""
    src = source or {}
    out: list[BidItem] = []
    for m, body in _spans(list(_ALT.finditer(text)), text):
        basis = "deduct" if _DEDUCT.search(body) else ("add" if _ADD.search(body) else "unknown")
        bm = _BASE_BID.search(body)
        out.append(BidItem(
            kind="alternate", number=m.group(1), title=m.group(2).strip().rstrip("."),
            basis=basis, description=_clean(bm.group(1))[:300] if bm else "", source=dict(src),
        ))
    return out


def parse_unit_prices(text: str, source: dict | None = None) -> list[BidItem]:
    """Parse the 'Schedule of Unit Prices' into BidItems (number, title, unit of measure)."""
    src = source or {}
    out: list[BidItem] = []
    for m, body in _spans(list(_UP.finditer(text)), text):
        dm = _DESC.search(body)
        um = _UOM.search(body)
        out.append(BidItem(
            kind="unit_price", number=m.group(1), title=m.group(2).strip().rstrip("."),
            basis="unit", description=_clean(dm.group(1))[:300] if dm else "",
            unit=_clean(um.group(1)).rstrip(".") if um else None, source=dict(src),
        ))
    return out


def parse_allowances(text: str, source: dict | None = None) -> list[BidItem]:
    """Parse the 'Schedule of Allowances' (same MasterSpec pattern). Unvalidated on
    real data — UCCS has no 012100 and Pinney no Div-01 sections — so this exists for
    the found path if a future project carries it; the absent path is what's tested."""
    src = source or {}
    out: list[BidItem] = []
    for m, body in _spans(list(_ALLOW.finditer(text)), text):
        dm = _DESC.search(body)
        out.append(BidItem(
            kind="allowance", number=m.group(1), title=m.group(2).strip().rstrip("."),
            basis="lump_sum", description=_clean(dm.group(1))[:300] if dm else "", source=dict(src),
        ))
    return out


# section number -> (kind, parser)
_REGISTRY = {
    "012300": ("alternate", parse_alternates),
    "012200": ("unit_price", parse_unit_prices),
    "012100": ("allowance", parse_allowances),
}


def extract_bid_structure(manual_path) -> tuple[list[BidItem], dict]:
    """Locate and parse the Division-01 pricing sections. Returns (items, located)
    where `located` maps each kind to 'found' | 'absent'."""
    fid = pathlib.Path(str(manual_path)).stem
    items: list[BidItem] = []
    located: dict[str, str] = {}
    with fitz.open(str(manual_path)) as doc:
        for number, (kind, parser) in _REGISTRY.items():
            text, page = section_text(doc, number)
            located[kind] = "found" if text else "absent"
            if text:
                items += parser(text, {"file_id": fid, "page": page, "section": number})
    return items, located
