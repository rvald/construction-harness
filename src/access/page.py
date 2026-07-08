from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import fitz
    from src.access.document import Document


class Page:
    """A single PDF page: a transparent proxy over the live fitz page, with per-page
    memoization and per-call degrade.

    Plain class (not data): it wraps a live resource and forwards behavior. The legacy
    pure extractors call get_text(...) / get_drawings() / rect on this object exactly as
    they called them on a raw fitz page, so their logic is untouched — memoization and
    error-degrade happen HERE, invisibly.

    Constructed only via Document.page(i) (Slice B), which hands back the SAME Page
    instance per index — that instance-sharing is what lets a second consumer's
    get_text("words") hit this cache instead of re-scanning (the ~4-passes -> 1 win).
    """

    def __init__(self, doc: "Document", index: int, fitz_page: "fitz.Page") -> None:
        self._doc = doc                 # back-ref: _safe, _plumber_page, config (Slice B)
        self.index = index              # 0-based — the internal truth
        self._fitz = fitz_page          # the live fitz PAGE (not the doc)
        self._memo: dict = {}           # (op, *args) -> value; the cross-consumer cache

    @property
    def number(self) -> int:
        """1-based page number — THE single 0->1 conversion point in the stack."""
        return self.index + 1

    @property
    def rect(self):
        """Forward fitz's page rect as-is, so `page.rect.width` works unchanged. Cheap
        and non-failing, so no memo / degrade wrapper."""
        return self._fitz.rect

    def _cached(self, key: tuple, produce, default):
        """Run `produce()` at most once per (page, op, args), caching the result.
        _safe (Document, Slice B) turns a page-level failure into `default` + a recorded
        failure, so one bad page yields empty extraction for that page — never an
        aborted scan."""
        if key not in self._memo:
            self._memo[key] = self._doc._safe(self.index, key[0], produce, default)
        return self._memo[key]

    # --- transparent fitz surface: legacy pure extractors call these AS-IS ---

    def get_text(self, kind: str = "text"):
        """Proxy fitz get_text, memoized per kind. The default MATCHES the kind's shape
        so the degrade path never crashes a caller: "dict" -> {} (callers do
        .get("blocks", [])), "words" -> [] (callers iterate), plain -> "". The key
        includes `kind`, so "words" and "dict" are distinct cache entries."""
        default = {} if kind in ("dict", "rawdict") else [] if kind == "words" else ""
        return self._cached(("get_text", kind), lambda: self._fitz.get_text(kind), default)

    def get_drawings(self):
        """Proxy fitz get_drawings (vector paths), memoized. Degrade default: []."""
        return self._cached(("get_drawings",), self._fitz.get_drawings, [])

    # --- curated surface: the refactored drivers call these (not the legacy pure fns) ---

    def tables(self) -> list:
        """pdfplumber table extraction, lazy + memoized. Replaces the driver's direct
        `pdf.pages[i].extract_tables()`; the pdfplumber handle is opened on first use
        (Document._plumber_page, Slice B). Degrade default: []."""
        return self._cached(
            ("tables",),
            lambda: self._doc._plumber_page(self.index).extract_tables(),
            [],
        )

    def render_png(self, dpi: int | None = None) -> bytes:
        """Render the page to PNG bytes for the VLM verifier. Replaces
        count_verifier.render_sheet; dpi falls back to the run config. Keyed by dpi
        (different dpi -> different bytes). Degrade default: b""."""
        dpi = dpi or self._doc.config.render_dpi
        return self._cached(
            ("render", dpi),
            lambda: self._fitz.get_pixmap(dpi=dpi).tobytes("png"),
            b"",
        )
