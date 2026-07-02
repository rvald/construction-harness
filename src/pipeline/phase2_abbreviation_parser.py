"""Phase 2d — Abbreviation parser (Milestone 6).

Parses the architectural abbreviation list on drawings page 6 (sheet A0.1) into
AbbreviationEntry records.

Why this is geometric rather than text-based (see notebooks/02_explore_drawings.py):
  * Page 6 is rotated 90 degrees. pdfplumber returns upright text, but the sheet's
    multi-column layout means extract_text() reads ACROSS columns on each row,
    interleaving unrelated entries. So we work from word coordinates instead.
  * The abbreviation list occupies three columns in the left third of the sheet,
    with abbreviation tokens left-aligned at x ~= 169 / 440 / 712. Past a gutter
    near x ~= 900 lies the symbol legend and general notes (not abbreviations).
  * Bold glyphs render DOUBLED ('AADDDDIITTIIOONNAALL' -> 'ADDITIONAL'); we undo that.

Known prototype limitations (documented, not bugs):
  * Multi-word abbreviations ('GYP BD', 'ACS PNL') are split first-token-as-abbrev.
  * A wrapped definition line can occasionally yield a short spurious entry.
  * The right-side symbol legend is not yet extracted (no ground truth; low value
    for the Door N107B trace) — left as a follow-up.
"""
from __future__ import annotations

import pathlib
import re

import pdfplumber

from src.models.schedule import AbbreviationEntry

_DEFAULT_PDF = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs" / "drawings.pdf"
_PAGE_INDEX = 5                     # 0-indexed -> PDF page 6 (A0.1)

_COLUMN_ANCHORS = (169, 440, 712)   # left edges of the three abbreviation columns
_REGION_X = (150, 900)             # x-band containing the abbreviation list (before the gutter)
_ROW_TOLERANCE = 5                 # pt; words within this vertical distance share a row
_ABBREV_RE = re.compile(r"[A-Z0-9/&.\-]{1,7}")


def _dedouble(token: str) -> str:
    """Undo doubled bold glyphs: 'AADDDDIITTIIOONNAALL' -> 'ADDITIONAL'."""
    if len(token) >= 4 and len(token) % 2 == 0 and token[::2] == token[1::2]:
        return token[::2]
    return token


def _column_of(x0: float) -> int | None:
    col = None
    for i, anchor in enumerate(_COLUMN_ANCHORS):
        if x0 >= anchor - 20:
            col = i
    return col


def _cluster_rows(words: list[dict], tol: int = _ROW_TOLERANCE) -> list[list[dict]]:
    """Greedily group words into physical rows by their 'top' coordinate."""
    words = sorted(words, key=lambda w: w["top"])
    rows: list[list[dict]] = []
    current: list[dict] = []
    ref: float | None = None
    for w in words:
        if ref is None or abs(w["top"] - ref) <= tol:
            current.append(w)
            ref = w["top"] if ref is None else ref
        else:
            rows.append(current)
            current = [w]
            ref = w["top"]
    if current:
        rows.append(current)
    return rows


def parse_abbreviations(
    pdf_path: str | pathlib.Path = _DEFAULT_PDF,
    page_index: int = _PAGE_INDEX,
) -> list[AbbreviationEntry]:
    """Parse the abbreviation list into AbbreviationEntry records."""
    lo, hi = _REGION_X
    with pdfplumber.open(pdf_path) as pdf:
        words = [w for w in pdf.pages[page_index].extract_words(keep_blank_chars=False)
                 if lo <= w["x0"] < hi]

    seen: set[tuple[str, str]] = set()
    entries: list[AbbreviationEntry] = []
    for row in _cluster_rows(words):
        columns: dict[int, list[str]] = {}
        for w in sorted(row, key=lambda w: w["x0"]):
            col = _column_of(w["x0"])
            if col is not None:
                columns.setdefault(col, []).append(_dedouble(w["text"]))
        for col in sorted(columns):
            tokens = columns[col]
            if len(tokens) < 2:
                continue
            abbrev, definition = tokens[0], " ".join(tokens[1:])
            if not (_ABBREV_RE.fullmatch(abbrev) and definition):
                continue
            key = (abbrev, definition)
            if key in seen:
                continue
            seen.add(key)
            entries.append(AbbreviationEntry(abbreviation=abbrev, definition=definition))
    return entries


def abbreviations_as_dict(entries: list[AbbreviationEntry]) -> dict[str, str]:
    """Convenience: first-seen definition wins when an abbreviation repeats."""
    out: dict[str, str] = {}
    for e in entries:
        out.setdefault(e.abbreviation, e.definition)
    return out


if __name__ == "__main__":
    abbrevs = parse_abbreviations()
    print(f"entries parsed : {len(abbrevs)}")
    d = abbreviations_as_dict(abbrevs)
    for k in ["ACT", "CMU", "HM", "WD", "ALUM", "AB", "AFF", "CONC", "TYP", "PLAM"]:
        print(f"  {k:<6}-> {d.get(k)!r}")