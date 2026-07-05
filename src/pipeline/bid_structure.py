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


def _head_of(text: str) -> str:
    """First 8 NON-BLANK lines (headers sit past blank lines / title block)."""
    return " ".join([l.strip() for l in text.splitlines() if l.strip()][:8]).upper()


def _body(doc, start: int, section_number: str, max_pages: int = 6) -> str:
    """Joined text of a section body from its start page to the next section header."""
    texts = []
    for i in range(start, min(start + max_pages, doc.page_count)):
        t = doc[i].get_text()
        if i > start:
            m = _SECTION_HEADER.search(_head_of(t))
            if m and m.group(1) != section_number:      # next section began
                break
        texts.append(t)
    return "\n".join(texts)


def locate_sections(doc, wanted: set[str]) -> dict[str, int]:
    """One page-pass: {section_number -> 0-indexed start page} for the wanted sections
    (header near the top of a page, skipping the TOC listing). First occurrence wins."""
    starts: dict[str, int] = {}
    for i in range(doc.page_count):
        head = _head_of(doc[i].get_text())
        if "TABLE OF CONTENTS" in head:
            continue
        m = _SECTION_HEADER.search(head)
        if m and m.group(1) in wanted and m.group(1) not in starts:
            starts[m.group(1)] = i
    return starts


def section_text(doc, section_number: str, max_pages: int = 6) -> tuple[str | None, int | None]:
    """Return (joined body text, 1-indexed start page) for one section, or (None, None)."""
    starts = locate_sections(doc, {section_number})
    if section_number not in starts:
        return None, None
    s = starts[section_number]
    return _body(doc, s, section_number, max_pages), s + 1


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


def summarize(items: list[BidItem], located: dict) -> dict:
    """Reported metrics: which kinds were found/absent and how many items each."""
    from collections import Counter

    return {
        "located": located,
        "counts": dict(Counter(i.kind for i in items)),
        "total_items": len(items),
    }


def build_bid_structure(manual_path) -> dict:
    """Full artifact: {summary, items}. Absent sections are flagged, not faked."""
    items, located = extract_bid_structure(manual_path)
    return {"summary": summarize(items, located), "items": [i.to_dict() for i in items]}


def extract_bid_structure(manual_path) -> tuple[list[BidItem], dict]:
    """Locate and parse the Division-01 pricing sections. Returns (items, located)
    where `located` maps each kind to 'found' | 'absent'."""
    fid = pathlib.Path(str(manual_path)).stem
    items: list[BidItem] = []
    located: dict[str, str] = {}
    with fitz.open(str(manual_path)) as doc:
        starts = locate_sections(doc, set(_REGISTRY))       # one page-pass for all sections
        for number, (kind, parser) in _REGISTRY.items():
            if number in starts:
                s = starts[number]
                located[kind] = "found"
                items += parser(_body(doc, s, number), {"file_id": fid, "page": s + 1, "section": number})
            else:
                located[kind] = "absent"
    return items, located


if __name__ == "__main__":
    import json

    manual = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "project_manual.pdf"
    out = pathlib.Path(__file__).resolve().parents[2] / "output" / "reports" / "bid_structure.json"
    report = build_bid_structure(manual)
    print(json.dumps(report["summary"], indent=2))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nwrote {out}  ({report['summary']['total_items']} bid items)")
