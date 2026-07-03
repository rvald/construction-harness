"""Document map contracts (Document Locator phase).

The DocumentMap is the hand-off between DISCOVERY (intake -> profile -> segment ->
locate) and EXTRACTION (the existing Phase 2+ parsers). For a bid package of any
shape it answers: what is each page, and where does each target artifact live?

Locked design decisions (see docs/document_locator_design.md):
  * Everything reduces to typed REGIONS. Separate files are just the case where a
    file is (usually) one region; a combined PDF yields several regions in one file.
  * A not-found target DEGRADES and is FLAGGED, never raised. `status` carries the
    explicit else-branch: found | low_confidence | absent | not_applicable, where
    `absent` (expected but missing) is distinct from `not_applicable` (region gone).
  * This phase stops at "located the page" and hands page refs to existing parsers.
  * Region kind / artifact name are extensible strings validated against a known
    set (unknown allowed-but-flagged), not a closed enum.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import JsonModel

# --- extensible vocabularies --------------------------------------------------
# Unknown values are permitted (see is_known_*), so adding "bid_form" / "geotech"
# later is a one-line change, not a schema migration.

KNOWN_REGION_KINDS = frozenset({"manual", "drawings", "front_matter", "unknown"})
KNOWN_ARTIFACTS = frozenset({
    "spec_toc", "spec_section", "drawing_index",
    "door_schedule", "finish_schedule", "abbreviations",
})

# Each artifact is searched within one region kind; drives not_applicable logic.
ARTIFACT_REGION: dict[str, str] = {
    "spec_toc": "manual",
    "spec_section": "manual",
    "drawing_index": "drawings",
    "door_schedule": "drawings",
    "finish_schedule": "drawings",
    "abbreviations": "drawings",
}

# Location status values (the explicit else-branch).
STATUS_FOUND = "found"
STATUS_LOW = "low_confidence"
STATUS_ABSENT = "absent"
STATUS_NA = "not_applicable"


def is_known_region_kind(kind: str) -> bool:
    return kind in KNOWN_REGION_KINDS


def is_known_artifact(name: str) -> bool:
    return name in KNOWN_ARTIFACTS


# --- records ------------------------------------------------------------------


@dataclass
class FileRef(JsonModel):
    """One file in the bid package (separate file or a single combined PDF)."""

    file_id: str                    # stable id, e.g. the filename stem
    path: str
    checksum_sha256: str
    page_count: int
    doc_format: str = "unknown"     # pdf_vector | pdf_scanned | unknown


@dataclass
class PageProfile(JsonModel):
    """Cheap per-page structural features. Never carries table/geometry parses."""

    file_id: str
    page_index: int                 # 0-based within the file
    width: float
    height: float
    rotation: int
    size_class: str                 # letter_portrait | large_landscape | other
    char_count: int
    text_density: float             # chars per 1000 sq pt (rotation-independent)
    has_text_layer: bool
    short_token_count: int = 0      # count of 1-4 char all-caps tokens (abbreviation signal)
    anchor_hits: dict = field(default_factory=dict)   # token -> count


@dataclass
class Region(JsonModel):
    """A contiguous run of same-kind pages, within one file."""

    kind: str                       # manual | drawings | front_matter | unknown
    file_id: str
    page_start: int                 # inclusive, 0-based
    page_end: int                   # inclusive, 0-based
    confidence: float = 1.0

    @property
    def page_count(self) -> int:
        return self.page_end - self.page_start + 1

    def contains(self, file_id: str, page_index: int) -> bool:
        return file_id == self.file_id and self.page_start <= page_index <= self.page_end


@dataclass
class PageRef(JsonModel):
    """A single located page, with how the locator matched it."""

    file_id: str
    page_index: int
    confidence: float = 1.0
    signature: str = ""             # which locator/signature produced this hit


@dataclass
class LocatedArtifact(JsonModel):
    """The result of looking for one artifact — including 'not found', explicitly."""

    name: str
    status: str                     # found | low_confidence | absent | not_applicable
    region_kind: str = ""
    pages: list[PageRef] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.status in (STATUS_FOUND, STATUS_LOW)

    @property
    def page_indices(self) -> list[int]:
        return [p.page_index for p in self.pages]

    def best(self) -> PageRef | None:
        return max(self.pages, key=lambda p: p.confidence) if self.pages else None


@dataclass
class DocumentMap(JsonModel):
    """The complete discovery result and the extraction hand-off."""

    files: list[FileRef] = field(default_factory=list)
    profiles: list[PageProfile] = field(default_factory=list)
    regions: list[Region] = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)       # name -> LocatedArtifact
    completeness: dict = field(default_factory=dict)

    # --- queries ---------------------------------------------------------

    def locate(self, name: str) -> LocatedArtifact | None:
        return self.artifacts.get(name)

    def regions_of(self, kind: str) -> list[Region]:
        return [r for r in self.regions if r.kind == kind]

    def has_region(self, kind: str) -> bool:
        return any(r.kind == kind for r in self.regions)

    def profiles_in(self, region: Region) -> list[PageProfile]:
        return [p for p in self.profiles
                if region.contains(p.file_id, p.page_index)]
