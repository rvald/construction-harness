"""Binary-extraction models (Milestone 10).

TextObject and GeometricPrimitive capture what PyMuPDF exposes at the binary/vector
level of a drawing sheet. ExtractedSymbol (listed in the structure) is deferred —
Milestone 10 is exploratory and doesn't populate symbols.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import JsonModel


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