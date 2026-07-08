# Takeoff Operationalization — Document-Access Seam (Design)

**Status:** Built (M1–M3, green); M4 (scale + vector) pending. See "Outcome (as built)" below.
**Date:** 2026-07-06 (design) · updated 2026-07-08 (as built)
**Branch:** fresh `refactor/takeoff-access-layer` off `main`.
**Depends on:** the built takeoff stack (scale, area, counting, schedules, verify) — this
reorganizes *how* it runs, not *what* it extracts.
**Golden rule:** pure refactor. `output/reports/validation_report.json` **and**
`output/reports/schedule_items.json` must stay **byte-identical**; snapshot both, diff
after every milestone. WHAT is extracted does not change — only HOW pages are read,
logged, and error-handled.

---

## Outcome (as built)

The takeoff stack now opens the drawings PDF **once** and threads a shared `Document`
through all three coordinator consumers.

- **Access layer** (`src/access/`): `Document` (open-once, per-page memoized fitz + lazy
  pdfplumber, sha256 checksum, `failures` ledger, degrade-not-raise), `Page` (a
  *transparent fitz proxy* — see deviations), `TakeoffConfig` (frozen pydantic model),
  and `using_document` (a context manager that opens a path but *borrows* an already-open
  `Document`, closing only what it opened). The `CountResult` missing-`@dataclass` defect
  was repaired.
- **Drivers migrated** (`src/takeoff/`): `area_harvest`, `fixture_counts`,
  `quantity_schedules` each accept a path **or** a shared `Document`; the pure functions
  are untouched.
- **M3 coordinator** (`build_schedule_items`): one `Document`, threaded into
  schedules → areas → counts. The collapse is measured in the run manifest —
  `timing = {schedules: 298s, areas: 4.1s, counts: 0.06s}`: `areas` pays for
  `get_text("words")` once; `counts` reuses it in **0.06s** instead of re-scanning.
  `schedule_items.json` is **byte-identical**, and the anticipated fixture re-baseline
  turned out **unnecessary** (the committed block was already correct — the `@dataclass`
  repair merely restored the path). The manifest is a **sibling**
  `schedule_items.manifest.json` (gitignored — timing is non-deterministic), keeping the
  artifact deterministic.

### Deviations from the original design

- **`src/takeoff/` package created now, not deferred** (§5/§10). The 7 takeoff modules
  moved out of `src/pipeline/` (a clean import leaf), and `binary_extractor.py`
  was renamed `binary_extractor.py`.
- **`Page` is a transparent fitz proxy, not a curated API** (§6). It forwards
  `get_text(kind)` / `get_drawings()` / `rect` so the pure functions call them
  *unchanged*; `tables()` and `render_png()` are the only curated additions.
  Memoization and per-call degrade live inside the proxy.
- **`TakeoffConfig` is a frozen pydantic `BaseModel`** (not a dataclass, cf. D6), with
  validated fields and `page_range` modeled as `tuple[int,int] | None`.
- **The run manifest is a sibling file**, resolving §7's embed-vs-alongside as *sibling*.

### Discovered, deferred to a separate effort

Moving the suite toward a fast loop surfaced that it is dominated by **import-time PDF
extraction** (module-level `_REPORT = run_all(...)`, `_KG = build_graph(...)`, etc.), so
markers alone can't make it fast — pytest imports every module during collection. The
fix — a unit/integration split backed by **small fixture PDFs** — is scoped but
deferred. In place already: pytest replaced the custom `tests/run.py`, a
`tests/integration/` directory + auto-marking `conftest.py` isolates the import-heavy
files, and stale `data/uccs/pinney` fixture paths were corrected.

### Pending (M4)

`scale_resolver` and `binary_extractor` still open their own fitz; they are not on the
coordinator path, so they are lower priority. Wiring them onto the seam puts the *whole*
stack on the access layer.

---

## 1. Goal

Make the construction-takeoff stack **production-grade in operation** — robust,
observable, reproducible, maintainable — by separating the one impure concern (PDF
I/O) from the pure extraction logic it is currently tangled into. This is the
"operationalize HOW it runs" pass; no new quantities, no schema changes, no new
trades.

The takeoff stack (the code behind the `construction-takeoff` skill):

| Skill capability | Module | Library |
|---|---|---|
| Vector extraction (text + geometry) | `binary_extractor.py` | fitz |
| Scale detection | `scale_resolver.py` | fitz |
| Tag counting | `fixture_counts.py` | fitz |
| Area measurement | `area_harvest.py` | fitz |
| Schedule-sourced quantities | `quantity_schedules.py` + `schedule_resolver.py` | pdfplumber |
| Vision verification | `count_verifier.py` | fitz + anthropic |
| Assembly / output | `build_schedule_items.py` | — |

*(Linear measurement — pipes, cable trays — is a WHAT gap, deferred (T3.2). Out of
scope here.)*

---

## 2. Measured current state — the entanglement

The **pure core of each module is already clean and side-effect-free** and needs no
change: `parse_scale` / `resolve_sheet_scale`, `sf_labels` / `join_areas`,
`tag_spans` / `classify_page`, `resolve_columns` / `select_schedule_table`,
`phase4.classify`. These are the "independent work" units and are already
offline-testable.

The problem is entirely in the **drivers**, where PDF I/O is duplicated and
uncoordinated:

- **Each driver opens its own document.** `fitz.open(...)` is re-invoked
  independently in `fixture_counts.py:52`, `area_harvest.py:115`,
  `quantity_schedules.py:173`, `count_verifier.py:157`,
  `binary_extractor.py:172`; `pdfplumber.open(...)` independently in
  `quantity_schedules.py:185` and `locator.py:177`.
- **~4 full document passes per artifact build.** One `build_schedule_items()` run
  scans the whole drawings PDF four times over with fitz — `extract_schedule_items`
  (full `get_text` pass) + `harvest_room_areas` (full `get_text("words")` pass) +
  `count_fixtures` → `extract_counts` **once per counted catalog** (plumbing, then
  lighting) — plus a pdfplumber `extract_tables` pass on the schedule candidates. No
  shared open, no memoization.
- **Dependency imports are in-function** (`import fitz`, `import pdfplumber`,
  `import pathlib` inside bodies) — done for offline-laziness, but it scatters the
  dependency surface and hides it from static tooling.
- **No observability.** No logging, no per-phase timing, no progress — despite the
  design docs noting a "~90s scan." `print()` only.
- **No error-degrade.** A single malformed page raises and aborts the whole scan,
  contradicting the architecture's "partial completion / fail explicitly, recover
  gracefully" principle (Arch §14.1, principle 9).
- **Convention drift.** 0-indexed vs 1-indexed pages are converted ad hoc
  (`sheet_page = i + 1`); `file_id or pathlib.Path(str(pdf_path)).stem` is
  re-derived in two places.
- **Config is scattered module-level constants** (`_SPREAD_THRESHOLD`, `max_dist`,
  `_MIN_TAGS`, render `dpi`, `min_coverage`) — fine for correctness, but a run is
  not parameterized or loggable as a unit, which hurts reproducibility.

### Discovered latent defect (fix under M1)

`CountResult` in `src/models/schedule.py:61` is **missing its `@dataclass`
decorator** (crammed onto the end of `BidItem`), so `CountResult(symbol_id=...)` in
`fixture_counts.py:68` cannot instantiate. This means the counting path is a
runtime break, and the committed `schedule_items.json` `fixture_counts` block is not
currently regenerable. It must be repaired before the counting migration can diff
against a real golden. Repairing it *restores intended behavior* (not a behavior
change) — but re-baseline the fixture-count block honestly and note it.

---

## 3. The seam

```
   IMPURE (new, isolated)                 PURE (unchanged logic)
   ┌────────────────────┐                 ┌───────────────────────────────┐
   │ access/document.py │   pages ──────► │ scale · area · counting ·     │
   │  open once         │                 │ schedules · vector · verify   │
   │  memoize text/tables/render          │ (pure functions, offline)     │
   │  checksum · logging · error-degrade  └───────────────────────────────┘
   └────────────────────┘
```

Extract the impure seam into one module; the takeoff drivers stop opening PDFs and
instead consume `Document` / `Page` objects. Pure functions keep their exact
signatures (they already take a `page` or a `table`, not a path) — so the diff is
almost entirely in the ~6 drivers, and the pure logic (the tested part) is untouched.

---

## 4. Locked decisions

- **D1 One open, one pass, many consumers.** A `Document` opened once, threaded
  through every consumer, with per-page text/words/tables/render **memoized** — so
  the four full passes collapse to one. This is the primary robustness *and*
  performance win.
- **D2 Behavior byte-identical, proven by the golden.** Both reports stay identical
  through every milestone (except the one honest, documented fixture-count
  re-baseline forced by the `CountResult` repair). Pure functions are not touched.
- **D3 Backward-compatible entry points.** Public functions that today take a
  `pdf_path` (used across the test suite) keep that signature via a thin wrapper that
  opens a `Document` and delegates to a `Document`-taking internal. No test rewrites
  required for the migration itself.
- **D4 Offline-safe, lazy heavy deps.** `pdfplumber` and rendering stay lazily
  imported *inside* the access layer (the offline suite never triggers a table
  extract or a render it doesn't ask for). fitz is the one eager dependency, already
  required.
- **D5 Degrade, don't raise.** `Document.pages()` isolates per-page failures: log +
  record in a `failures` list + skip, never abort the scan. Matches Arch principle 9.
- **D6 Config as one object, defaults reproduce today.** A `TakeoffConfig` dataclass
  centralizes the scattered thresholds; its defaults reproduce current output
  exactly, and the resolved config is logged as part of the run manifest.

---

## 5. Target module layout

```
src/access/
  document.py     ← NEW. Document / Page: open-once, memoized fitz+pdfplumber
                    views, render, checksum, file_id, page-index convention,
                    logging hook, per-page error-degrade.
  config.py       ← NEW. TakeoffConfig (thresholds, dpi, page ranges) + run manifest.
```

Module *renames* into a `src/takeoff/` package (`scale.py`, `area.py`, `counting.py`,
`verify.py`, `schedules.py`, `vector.py`, `assemble.py`) are a **later, optional**
pass — they are churn without robustness payoff, and every rename touches imports +
tests. This design deliberately does **not** move files; it only inserts the access
seam under the existing modules. Layout reorg is a separate decision after this
lands.

---

## 6. The access-layer contract

```python
# src/access/document.py
class Document:
    """Open-once access to one PDF. fitz is the backbone; pdfplumber is lazy."""
    def __init__(self, path, *, file_id: str | None = None, logger=None): ...

    @property
    def file_id(self) -> str: ...          # given, or path stem — the ONE definition
    @property
    def checksum(self) -> str: ...         # sha256; reproducibility + memo/cache key
    @property
    def page_count(self) -> int: ...

    def pages(self, page_range=None):       # -> Iterator[Page]; per-page error-degrade
        ...
    def page(self, index: int) -> "Page": ...

    failures: list[dict]                    # [{page_index, error}] recorded, not raised

class Page:
    index: int                              # 0-based (internal truth)
    number: int                             # 1-based (the single conversion point)
    width: float
    height: float
    def text(self) -> str: ...              # fitz get_text(),        memoized
    def words(self) -> list: ...            # fitz get_text("words"), memoized
    def text_dict(self) -> dict: ...        # fitz get_text("dict"),  memoized (spans/geometry)
    def drawings(self) -> list: ...         # fitz get_drawings(),    memoized
    def tables(self) -> list[list[list]]: ...   # pdfplumber extract_tables(), lazy + memoized
    def render_png(self, dpi: int = 100) -> bytes: ...
```

- **Memoization is per-`Page`-per-kind**, so the schedule pass, the area pass, and
  both fixture passes share one `text()`/`words()` computation instead of four.
- **`tables()` opens pdfplumber lazily and once**, caching the handle on the
  `Document`; only candidate pages ever trigger it (unchanged gating).
- **`render_png`** replaces `count_verifier.render_sheet` — one renderer, one dpi
  default, cacheable by `(checksum, page, dpi)`.
- **Logging hook**: the access layer emits structured events
  (`document.open`, `page.text`, `page.tables`, `page.render`, `page.error`) with
  elapsed time and sizes; a null logger by default so tests stay silent.

Drivers change shape from `fn(pdf_path, ...)` to `fn(doc: Document, ...)`, with a
`fn(pdf_path, ...)` wrapper preserved. `build_schedule_items` opens **one**
`Document` and threads it into `extract_schedule_items`, `harvest_room_areas`, and
`count_fixtures`.

---

## 7. Observability & reproducibility

- **Run manifest** (written alongside each artifact, not into the golden): resolved
  `TakeoffConfig`, per-file `{file_id, checksum, page_count}`, per-phase timing,
  per-phase item counts, and `Document.failures`. Answers "what exactly produced this
  number, and how long did it take" — the audit-log gap in Arch §14.4.
- **Structured logging** at phase boundaries (candidate pages found, tables
  resolved, tags counted, areas joined) at INFO; per-page events at DEBUG.
- **Determinism check**: same input checksum ⇒ identical output; the manifest's
  checksums make a re-run diffable.

---

## 8. Migration order (one commit each, golden diffed after every step)

- **M1 — access layer + counting repair. ✅** Built `Document`/`Page` + `TakeoffConfig`;
  fixed the `CountResult` `@dataclass` defect; repointed `fixture_counts` +
  `count_verifier.render_sheet` at the access layer.
- **M2 — area + schedules onto the seam. ✅** Repointed `harvest_room_areas` and
  `extract_schedule_items` (fitz text + pdfplumber tables) at a shared `Document`;
  `schedule_items.json` byte-identical.
- **M3 — `build_schedule_items` single-open orchestration. ✅** One `Document` threaded
  through all three consumers; run manifest emitted to a sibling file; the 4-passes→1
  collapse is visible in the timing (`counts` 0.06s reusing `areas`' memoized words);
  artifact byte-identical.
- **M4 — vector + scale + wrappers. (pending)** Repoint `binary_extractor` and
  `scale_resolver` drivers; confirm every public `pdf_path` entry point still works.

De-risk was M1 (the seam contract + the latent defect) and M3 (proving the pass
collapse without changing output) — both landed.

---

## 9. Golden-safety plan

- Snapshot `validation_report.json` + `schedule_items.json` before M1.
- Diff both after every milestone; any non-identical byte is a stop-and-explain,
  except the single M1 fixture-count re-baseline (which is the *repair* of a
  currently-broken path, documented in the commit).
- The access layer ships with its own offline unit tests (memoization,
  error-degrade, checksum, page-number conversion) so its behavior is pinned
  independently of the drivers.

---

## 10. Out of scope (explicit)

- New quantities or trades (linear measurement / pipes / cable trays — T3.2).
- Schema changes, new `ScheduleSchema`s, CSV output (the skill's CSV is a WHAT
  concern — separate).
- `src/takeoff/` package rename (optional later pass — §5).
- Touching the pure extraction functions' logic or signatures.
- OCR / scanned-PDF handling, VLM changes, the locator/segmenter (discovery
  front-half is already its own clean seam).
```
