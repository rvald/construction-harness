"""Phase 2a — Specification Table of Contents parser (Milestone 3).

Parses the project manual's TOC (pages 5-9 in the UCCS package) into a SpecTOC.

Design notes, all driven by the real document (see notebooks/01_explore_project_manual.py):
  * Division and section headers use a MIX of hyphen and en/em dashes.
  * Section numbers are 6 digits with an optional ".NN" suffix (e.g. 074213.23).
  * Divisions can be flagged "NOT APPLICABLE" on the line following the header.
  * Division 00 lists named procurement forms, not numbered CSI sections; we
    intentionally do not capture those as sections (nothing downstream needs them).
  * Section titles occasionally WRAP across lines; continuation lines are stitched
    back onto the preceding section.
  * Every page carries a repeating SmithGroup header and a "TOC-N" footer to strip.
"""
from __future__ import annotations

import pathlib
import re

import pdfplumber

from src.models.spec import SpecClause, SpecPart, SpecSection, SpecTOC

# Dashes seen in source: hyphen-minus, en dash, em dash, figure/horizontal-bar dashes.
_DASH = r"[-\u2012\u2013\u2014\u2015\u2212]"

DIVISION_RE = re.compile(rf"^\s*DIVISION\s+(\d{{2}})\s*{_DASH}\s*(.+?)\s*$")
SECTION_RE = re.compile(rf"^\s*SECTION\s+(\d{{6}}(?:\.\d{{2}})?)\s*{_DASH}\s*(.+?)\s*$")
_DATE_RE = re.compile(r"^\d{1,2}\s+[A-Za-z]+\s+\d{4}$")
_FOOTER_RE = re.compile(r"^TABLE OF CONTENTS\s+TOC-\d+$")

_NOISE_EXACT = {"BID SET", "TABLE OF CONTENTS", "END OF TABLE OF CONTENTS", "PROJECT MANUAL COVER"}

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "project_manual.pdf"


def _is_noise(line: str) -> bool:
    s = line.strip()
    return (
        not s
        or s.startswith("SMITHGROUP")
        or s in _NOISE_EXACT
        or bool(_DATE_RE.match(s))
        or bool(_FOOTER_RE.match(s))
    )


def _is_toc_page(text: str) -> bool:
    """A TOC page carries at least one DIVISION header or the terminal sentinel."""
    if "END OF TABLE OF CONTENTS" in text:
        return True
    return any(DIVISION_RE.match(line) for line in text.splitlines())


def _toc_lines(pdf_path: str | pathlib.Path, start_page: int = 0, scan_pages: int = 20) -> list[str]:
    """Return the raw lines of the (contiguous) TOC pages, in order.

    `start_page` (0-indexed) is where scanning begins — pass the located TOC page
    from the document map so this works when the manual isn't at the front of the
    package (e.g. a combined, drawings-first PDF). Default 0 preserves the old
    front-of-document behavior.
    """
    lines: list[str] = []
    started = False
    with pdfplumber.open(pdf_path) as pdf:
        end = min(start_page + scan_pages, len(pdf.pages))
        for i in range(start_page, end):
            text = pdf.pages[i].extract_text() or ""
            if _is_toc_page(text):
                started = True
                lines.extend(text.splitlines())
            elif started:
                break  # TOC is contiguous; stop once we've passed it
    return lines


def parse_spec_toc(pdf_path: str | pathlib.Path = _DEFAULT_PDF, start_page: int = 0) -> SpecTOC:
    """Parse the project manual TOC into a structured SpecTOC."""
    divisions: list[dict] = []
    current: dict | None = None
    last_section: dict | None = None

    for raw in _toc_lines(pdf_path, start_page):
        if _is_noise(raw):
            continue

        m = DIVISION_RE.match(raw)
        if m:
            current = {"number": m.group(1), "title": m.group(2).strip(),
                       "sections": [], "applicable": True}
            divisions.append(current)
            last_section = None
            continue

        if raw.strip().upper() == "NOT APPLICABLE":
            if current is not None:
                current["applicable"] = False
            continue

        m = SECTION_RE.match(raw)
        if m and current is not None:
            last_section = {"number": m.group(1), "title": m.group(2).strip()}
            current["sections"].append(last_section)
            continue

        # Unmatched content line. In a numbered division this is a wrapped title
        # continuation; in Division 00 it is a named procurement form (skipped).
        if current is not None and current["number"] != "00" and last_section is not None:
            prev = last_section["title"]
            joiner = "" if prev.endswith("-") else " "
            last_section["title"] = (prev + joiner + raw.strip()).strip()

    total = sum(len(d["sections"]) for d in divisions)
    return SpecTOC(divisions=divisions, total_sections=total)


# ---------------------------------------------------------------------------
# Phase 2b — individual spec section parser (Milestone 4)
# ---------------------------------------------------------------------------

PART_RE = re.compile(rf"^\s*PART\s+([123])\s*{_DASH}\s*(.+?)\s*$")
CLAUSE_RE = re.compile(r"^\s*(\d+\.\d+)\s+([A-Z][A-Z0-9 ,./&()'-]+?)\s*$")

# Standards-issuing bodies seen in the manual; extend as new ones appear.
_STD_ORGS = r"ASTM|ANSI/SDI|ANSI|NAAMM-HMMA|NAAMM|SDI|HMMA|NFPA|UL|BHMA|WDMA|ICC|ASHRAE|SSPC|NEMA|FM"
_STANDARD_RE = re.compile(rf"\b(?:{_STD_ORGS})\s+[A-Z]?\d[\w./-]*")


def _strip_section_noise(line: str, section_number: str) -> bool:
    """True if the line is a repeating page header or the section footer."""
    s = line.strip()
    if not s or s.startswith("SMITHGROUP") or s == "BID SET" or _DATE_RE.match(s):
        return True
    # Footer looks like "HOLLOW METAL DOORS AND FRAMES 081113-3"
    return bool(re.search(rf"\b{re.escape(section_number)}-\d+\s*$", s))


def _extract_standards(text: str) -> list[str]:
    """Pull standards refs from clause text; normalize wraps + trailing punctuation."""
    flat = re.sub(r"\s+", " ", text)  # heal refs split across line breaks
    seen: dict[str, None] = {}
    for m in _STANDARD_RE.finditer(flat):
        seen.setdefault(m.group().rstrip(". ").strip(), None)
    return list(seen)


def _extract_products(title: str, text: str) -> list[str]:
    """Light-touch manufacturer extraction from a MANUFACTURERS clause.

    CSI manufacturer lists read like 'a. Ceco Door; ASSA ABLOY.' — we pull the
    text after each list marker and split on ';'. Approximate by design; the
    graph links doors to sections via material codes, not manufacturer names.
    """
    if "MANUFACTURER" not in title:
        return []
    out: dict[str, None] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*[a-z0-9]{1,2}[.)]\s+(.*)$", line)  # list item: "a. ..." / "1. ..."
        if not m:
            continue
        for piece in m.group(1).split(";"):
            name = piece.strip().rstrip(".").strip()
            # keep proper-noun-ish names, drop boilerplate sentences
            if 2 <= len(name) <= 60 and name[:1].isupper() and " requirements" not in name.lower():
                out.setdefault(name, None)
    return list(out)


def extract_section_text(
    pdf_path: str | pathlib.Path,
    section_number: str,
    start_hint: int = 0,
) -> tuple[str, str, tuple[int, int]]:
    """Locate a section and return (raw_text, section_title, (start_pg, end_pg)).

    Boundaries: starts at the 'SECTION NNNNNN - TITLE' header line, ends at
    'END OF SECTION' (or the following SECTION header as a fallback). Page
    numbers returned are 1-indexed. Repeating headers/footers are stripped.
    """
    header_re = re.compile(rf"^\s*SECTION\s+{re.escape(section_number)}\s*{_DASH}\s*(.+?)\s*$")
    with pdfplumber.open(pdf_path) as pdf:
        n = len(pdf.pages)
        start: int | None = None
        title: str = ""
        for i in range(start_hint, n):
            for line in (pdf.pages[i].extract_text() or "").splitlines():
                m = header_re.match(line)
                if m:
                    start, title = i, m.group(1).strip()
                    break
            if start is not None:
                break
        if start is None:
            raise ValueError(f"SECTION {section_number} header not found (from page {start_hint+1}).")

        end = start
        for i in range(start, min(start + 60, n)):
            text = pdf.pages[i].extract_text() or ""
            if "END OF SECTION" in text:
                end = i
                break
            if i > start and re.search(r"^\s*SECTION\s+\d{6}", text, re.M):
                end = i - 1
                break
            end = i

        body: list[str] = []
        for i in range(start, end + 1):
            for line in (pdf.pages[i].extract_text() or "").splitlines():
                if not _strip_section_noise(line, section_number):
                    body.append(line)
    return "\n".join(body), title, (start + 1, end + 1)


def parse_spec_section(
    pdf_path: str | pathlib.Path = _DEFAULT_PDF,
    section_number: str = "081113",
    toc: SpecTOC | None = None,
    start_hint: int = 0,
) -> SpecSection:
    """Parse one CSI section into a SpecSection with Part 1/2/3 clause structure."""
    raw_text, section_title, page_range = extract_section_text(pdf_path, section_number, start_hint)

    division_number = section_number[:2]
    division_title = ""
    if toc is None:
        toc = parse_spec_toc(pdf_path)
    div = toc.division(division_number)
    if div:
        division_title = div["title"]

    # Split the body into parts, then clauses within each part.
    lines = raw_text.splitlines()
    part_bounds: list[tuple[int, int, str]] = []  # (line_idx, part_number, part_title)
    for idx, line in enumerate(lines):
        m = PART_RE.match(line)
        if m:
            part_bounds.append((idx, int(m.group(1)), m.group(2).strip()))

    parts: list[SpecPart] = []
    for p, (line_idx, part_no, part_title) in enumerate(part_bounds):
        end_idx = part_bounds[p + 1][0] if p + 1 < len(part_bounds) else len(lines)
        part_lines = lines[line_idx + 1:end_idx]

        # Find clause headers whose id matches this part number (guards false positives).
        clause_hdrs: list[tuple[int, str, str]] = []
        for j, line in enumerate(part_lines):
            m = CLAUSE_RE.match(line)
            if m and m.group(1).split(".")[0] == str(part_no):
                clause_hdrs.append((j, m.group(1), m.group(2).strip()))

        clauses: list[SpecClause] = []
        for c, (j, cid, ctitle) in enumerate(clause_hdrs):
            body_end = clause_hdrs[c + 1][0] if c + 1 < len(clause_hdrs) else len(part_lines)
            body = "\n".join(part_lines[j + 1:body_end]).strip()
            clauses.append(SpecClause(
                clause_id=cid,
                title=ctitle,
                text=body,
                products=_extract_products(ctitle, body),
                standards=_extract_standards(ctitle + "\n" + body),
            ))
        parts.append(SpecPart(part_number=part_no, part_title=part_title, clauses=clauses))

    return SpecSection(
        section_number=section_number,
        section_title=section_title,
        division_number=division_number,
        division_title=division_title,
        parts=parts,
        page_range=page_range,
        raw_text=raw_text,
    )


if __name__ == "__main__":
    toc = parse_spec_toc()
    print(f"divisions parsed : {len(toc.divisions)}")
    print(f"total sections   : {toc.total_sections}")
    print(f"{'div':<5}{'applic':<8}{'#sec':<6}title")
    print("-" * 60)
    for d in toc.divisions:
        print(f"{d['number']:<5}{str(d['applicable']):<8}{len(d['sections']):<6}{d['title']}")