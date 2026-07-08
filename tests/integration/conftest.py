"""Everything under tests/integration/ opens real PDFs / runs full-document scans and
executes work at import (e.g. `_REPORT = run_all(...)`). Auto-mark the whole directory
`integration` so `-m "not integration"` deselects it — and, more importantly, so the
fast unit loop (`pytest tests/unit`) never even collects (imports) these modules, which
is where the ~40s collection cost lived.
"""
from __future__ import annotations

import pathlib

import pytest

_HERE = pathlib.Path(__file__).parent


def pytest_collection_modifyitems(config, items):
    for item in items:
        if _HERE in item.path.parents:      # only tests defined under tests/integration/
            item.add_marker(pytest.mark.integration)
