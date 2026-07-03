"""Tests for Phase 1 intake (Document Locator, M1).

UCCS is a two-file package; Pinney is a single combined PDF. Intake must reduce
both to a flat list of FileRef records without caring which is which yet.
"""
from __future__ import annotations

import pathlib

from src.pipeline.phase1_intake import intake_file, intake_package

DATA = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs"
DRAWINGS = DATA / "drawings.pdf"
MANUAL = DATA / "project_manual.pdf"
PINNEY = DATA / "pinney" / "pinney_library_drawings_and_project_manual.pdf"


def test_intake_separate_files():
    refs = intake_package([DRAWINGS, MANUAL])
    assert len(refs) == 2
    assert {r.file_id for r in refs} == {"drawings", "project_manual"}
    assert all(r.doc_format == "pdf_vector" for r in refs)
    assert all(len(r.checksum_sha256) == 64 for r in refs)


def test_intake_page_counts():
    assert intake_file(DRAWINGS).page_count == 133
    assert intake_file(MANUAL).page_count == 1036


def test_intake_combined_pinney():
    ref = intake_file(PINNEY)
    assert ref.file_id == "pinney_library_drawings_and_project_manual"
    assert ref.page_count == 525
    assert ref.doc_format == "pdf_vector"


def test_checksum_is_stable():
    assert intake_file(DRAWINGS).checksum_sha256 == intake_file(DRAWINGS).checksum_sha256
