"""The ONE seam between the service and the takeoff pipeline.

Nothing else in ``service/`` imports ``src`` — so if the pipeline's internals move, this
is the only file that changes. We invoke the builder and return its outputs verbatim; we
never touch the pipeline's own ``output/reports/`` write path or its pure functions.

The builder's ``report`` and ``manifest`` are the pipeline's contract: provenance and
confidence(-basis) already ride on every record, and the manifest already carries checksum,
per-phase timing, and the per-page ``failures`` ledger. We preserve both as-is.
"""
from __future__ import annotations

from pathlib import Path

# The entity/artifact contract version the service serves. Bump when the shredding schema
# or the shape we expose changes — independent of the pipeline's own versioning.
ENTITY_SCHEMA_VERSION = "1.0.0"


def run_takeoff(pdf_path: str | Path) -> tuple[dict, dict]:
    """Run the takeoff builder on one drawings PDF -> (report, manifest).

    Imported lazily so the API process (which never runs the build) does not pull PyMuPDF/
    pdfplumber, and so importing this module stays cheap. Defaults reproduce the golden.
    """
    from src.takeoff.build_schedule_items import build_schedule_items

    report, manifest = build_schedule_items(Path(pdf_path))
    return report, manifest
