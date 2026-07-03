"""Phase 1 — Document map assembler (Document Locator, M6).

Runs the discovery funnel end to end — intake -> profile -> segment -> locate —
and assembles the DocumentMap: the single artifact the extraction parsers consume
instead of hardcoded page indices.

Completeness is CONDITIONAL ON REGION PRESENCE (locked decision): an artifact whose
region is absent is `not_applicable`, not `missing`. So a package with no drawings
isn't penalised for a missing door schedule — only genuine gaps count.
"""
from __future__ import annotations

import pathlib

from src.models.document_map import (
    ARTIFACT_REGION, STATUS_ABSENT, STATUS_LOW,
    DocumentMap, FileRef,
)
from src.pipeline.locator import locate_all
from src.pipeline.page_profiler import profile_package
from src.pipeline.phase1_intake import intake_package
from src.pipeline.segmenter import segment_package


def _completeness(artifacts: dict, regions: list) -> dict:
    """Score = found / expected, where 'expected' is gated by which regions exist."""
    present_kinds = {r.kind for r in regions}
    # Only artifacts that were actually located (spec_section is found on-demand by
    # number, not as a single page, so it isn't in the located set).
    expected = [n for n in artifacts if ARTIFACT_REGION.get(n) in present_kinds]
    found = [n for n in expected if artifacts[n].found]
    return {
        "score": round(len(found) / len(expected), 3) if expected else 0.0,
        "expected": expected,
        "found": found,
        "missing": [n for n in expected if artifacts[n].status == STATUS_ABSENT],
        "not_applicable": [n for n in artifacts if ARTIFACT_REGION.get(n) not in present_kinds],
        "low_confidence": [n for n in artifacts if artifacts[n].status == STATUS_LOW],
    }


def extraction_pages(doc_map: DocumentMap) -> dict:
    """Resolve located pages for the extraction parsers (0-indexed).

    A single page per single-page artifact; for the TOC, both its start page and
    the page after its last (the point past which spec sections begin, so a section
    scan never false-matches a TOC listing). Absent artifacts resolve to None — the
    caller skips them rather than reading a wrong page.
    """
    def first(name: str) -> int | None:
        art = doc_map.locate(name)
        return art.pages[0].page_index if (art and art.pages) else None

    toc = doc_map.locate("spec_toc")
    toc_pages = toc.pages if (toc and toc.pages) else []
    return {
        "toc_start": toc_pages[0].page_index if toc_pages else None,
        "section_start_hint": (toc_pages[-1].page_index + 1) if toc_pages else 0,
        "drawing_index": first("drawing_index"),
        "door_schedule": first("door_schedule"),
        "finish_schedule": first("finish_schedule"),
        "abbreviations": first("abbreviations"),
    }


def build_document_map(paths: list[str | pathlib.Path]) -> DocumentMap:
    """Discover the structure of a bid package (separate files or one combined PDF)."""
    files: list[FileRef] = intake_package(paths)
    profiles = profile_package(files)
    regions = segment_package(profiles)
    artifacts = locate_all(files, profiles, regions)

    return DocumentMap(
        files=files,
        profiles=profiles,
        regions=regions,
        artifacts=artifacts,
        completeness=_completeness(artifacts, regions),
    )


if __name__ == "__main__":
    import json

    base = pathlib.Path(__file__).resolve().parents[2] / "data" / "uccs"
    packages = {
        "UCCS (separate files)": [base / "drawings.pdf", base / "project_manual.pdf"],
        "Pinney (combined PDF)": [base / "pinney" / "pinney_library_drawings_and_project_manual.pdf"],
    }
    for label, paths in packages.items():
        dm = build_document_map(paths)
        print(f"\n=== {label} ===")
        print(f"files    : {[f.file_id for f in dm.files]}")
        print(f"regions  : " + ", ".join(f"{r.kind}[{r.page_start}-{r.page_end}]" for r in dm.regions))
        print("artifacts:")
        for name, art in dm.artifacts.items():
            pages = ",".join(str(p.page_index) for p in art.pages) or "-"
            print(f"  {name:<16} {art.status:<15} pages={pages}")
        print(f"completeness: {dm.completeness['score']}  "
              f"missing={dm.completeness['missing']}  na={dm.completeness['not_applicable']}")
