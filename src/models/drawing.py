"""Binary-extraction models (Milestone 10).

TextObject and GeometricPrimitive capture what PyMuPDF exposes at the binary/vector
level of a drawing sheet. ExtractedSymbol (listed in the structure) is deferred —
Milestone 10 is exploratory and doesn't populate symbols.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import JsonModel


@dataclass
class SheetScale(JsonModel):
    """The drawing scale of a sheet (Tier 2.1). `factor` is real inches per paper
    inch, so a drawn distance of P points -> real inches = (P/72) * factor.

    A sheet with one scale resolves confidently; a sheet mixing scales (detail views
    at different scales) is flagged `ambiguous` with `factor` unresolved — per-viewport
    association is deferred, and the plan sheets that measurement needs first are
    single-scale anyway.
    """

    pdf_page_number: int
    factor: float | None                        # real inches per paper inch; None if none/ambiguous
    scale_text: str = ""                         # the chosen scale string ("" if none/ambiguous)
    confidence: float = 0.0                      # 1.0 single, ~0.4 ambiguous, 0.0 none
    ambiguous: bool = False                      # more than one distinct scale on the sheet
    all_scales: list[str] = field(default_factory=list)   # every distinct scale string found


@dataclass
class TextObject(JsonModel):
    """A single text span from a drawing sheet, with position and classification."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font: str
    size: float
    rotation: int                 # writing-direction angle, normalized to 0/90/180/270
    classification: str = "unknown"


@dataclass
class GeometricPrimitive(JsonModel):
    """A single vector drawing primitive (line / curve / rect / quad)."""

    kind: str
    x0: float
    y0: float
    x1: float
    y1: float
    width: float | None = None    # stroke width, when available