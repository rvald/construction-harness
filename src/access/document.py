"""Open-once PDF access for the takeoff stack.

Document is the single impure seam: it owns the live PDF handles and hands page data
to the (pure) extraction functions, so the stack opens each file ONCE instead of the
~4 independent scans it runs today. It is a plain class — NOT a dataclass/pydantic
model — because it holds live fitz/pdfplumber handles and does real work at
construction; an explicit __init__ is the honest fit.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

import fitz  

from src.access.config import TakeoffConfig
from src.access.page import Page




def _null_logger(event: str, **fields) -> None:
    """No-op default so the access layer can always call self._log(...) without a None
    check. A real (event, **fields) callable is injected by the coordinator; tests
    inject a list-appender to assert which events fired."""
    pass


@contextmanager
def using_document(source, *, config: TakeoffConfig | None = None, logger=None):
    """Yield a Document for `source`, which may be a path OR an already-open Document.

    Closes it ONLY if we opened it here — so a driver works standalone (given a path)
    and also accepts the coordinator's shared, single-open Document without closing it
    out from under the other consumers. `config`/`logger` apply only when we open one
    (a passed-in Document already carries its own)."""
    if isinstance(source, Document):
        yield source                      # shared: caller owns the lifecycle, don't close
    else:
        doc = Document(source, config=config, logger=logger)
        try:
            yield doc
        finally:
            doc.close()                   # we opened it -> we close it, even on error


class Document:
    """One open PDF: fitz eager (backbone); pdfplumber + checksum lazy (paid on demand)."""

    def __init__(
        self,
        path: str | Path,
        *,
        file_id: str | None = None,
        config: TakeoffConfig | None = None,
        logger: Callable[..., None] | None = None,
    ) -> None:
        self.path = str(path)                     # normalize once; fitz/pdfplumber/hashing all want str
        self.config = config or TakeoffConfig()   # one config per run; Page.render_png + drivers read it
        self.file_id = file_id or Path(self.path).stem  # THE single file_id definition
        self._fitz = fitz.open(self.path)         # eager backbone: a missing/corrupt file fails HERE (fail early)
        self._plumber = None                      # lazy: opened only if .tables() is ever asked (Slice B)
        self.failures: list[dict] = []            # degrade-not-raise ledger; filled by _safe, rides the manifest
        self._checksum: str | None = None         # memo slot for the lazy whole-file hash
        self._log = logger or _null_logger        # observability seam (null default = zero behavior change)
        self._pages: dict[int, Page] = {}   # index -> Page; THE cross-consumer memo cache

        self._log("document.open", file_id=self.file_id, pages=self.page_count)

    def _require_open(self):
        """Return the live fitz handle, or fail loudly if the Document is closed.
        One message, one place — every method that needs the handle goes through here,
        and it also narrows fitz.Document | None -> fitz.Document for the type checker."""
        if self._fitz is None:
            raise RuntimeError(f"Document {self.file_id} is closed")
        return self._fitz

    @property
    def page_count(self) -> int:
        """Page total (forward to fitz). A property so callers read doc.page_count."""
        return self._require_open().page_count

    @property
    def checksum(self) -> str:
        """sha256 of the file bytes — the honest identity for the manifest / cache keys.
        Lazy + memoized: a Document opened only to render one page never pays the hash."""
        if self._checksum is None:
            self._checksum = sha256(Path(self.path).read_bytes()).hexdigest()
        return self._checksum

    def close(self) -> None:
        """Release the handles. Idempotent: guarded on _fitz so a manual close() after
        __exit__ (or any double close) is a safe no-op, and document.close logs once."""
        if self._fitz is None:                    # already closed -> no-op
            return
        self._fitz.close()
        self._fitz = None
        if self._plumber is not None:
            self._plumber.close()
            self._plumber = None
        self._log("document.close", file_id=self.file_id, failures=len(self.failures))

        # --- degrade primitive: one place a page-level failure becomes empty + a record ---
    def _safe(self, index: int, op: str, produce, default):
        """Run produce(); on ANY extraction failure, record it and return `default`
        instead of raising — so one malformed page yields empty extraction for that page,
        not an aborted scan (Arch principle 9). Catches Exception, NOT BaseException, so
        KeyboardInterrupt/SystemExit still propagate."""
        try:
            return produce()
        except Exception as e:
            self.failures.append({"page_index": index, "op": op, "error": repr(e)})
            self._log("page.error", index=index, op=op, error=str(e))
            return default

    # --- lazy pdfplumber: opened once, on first table request, closed in close() ---
    def _plumber_page(self, index: int):
        """The pdfplumber page at `index`. pdfplumber is opened lazily (a table scan is
        the only thing that needs it) and cached on the Document; the heavy import stays
        out of the fitz-only paths."""
        if self._plumber is None:
            import pdfplumber
            self._plumber = pdfplumber.open(self.path)
        return self._plumber.pages[index]

    # --- page access: construct-and-cache, so the same Page (and its memo) is reused ---
    def page(self, index: int) -> Page:
        """The Page at 0-based `index`. Cached, so every consumer that asks for the same
        index gets the SAME Page instance — that's what makes Page._memo a shared cache
        and collapses the redundant scans into one."""
        fitz_doc = self._require_open()           # closed -> fail loudly, cached or not
        if index not in self._pages:
            self._pages[index] = Page(self, index, fitz_doc[index])
        return self._pages[index]

    def pages(self, page_range: tuple[int, int] | None = None):
        """Iterate Pages over a window, degrading on a page that won't even load.

        Window precedence: explicit arg > self.config.page_range > all pages. So a driver
        calling doc.pages() automatically honors the run's configured window (this is the
        reader that justifies config.page_range's existence). A page whose construction
        fails is recorded and skipped — per-PULL failures are caught later by _safe."""
        pr = page_range if page_range is not None else self.config.page_range
        rng = range(*pr) if pr is not None else range(self.page_count)
        for i in rng:
            try:
                yield self.page(i)
            except Exception as e:
                self.failures.append({"page_index": i, "op": "load", "error": repr(e)})
                self._log("page.error", index=i, op="load", error=str(e))


    def __enter__(self) -> Document:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()  
