"""Tests for Tier 3.1 M1 deterministic fixture-tag counting (fixture_counts)."""
from __future__ import annotations

import pathlib

from src.pipeline.fixture_counts import classify_page, extract_counts, summarize_counts

DRAWINGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "uccs" / "drawings.pdf"

# Tier 1 plumbing catalog (from schedule_items.json)
_TAGS = ["WC-1", "WC-2", "U-1", "KS-1", "L-1", "L-2", "MS-1", "GD-1", "DF-1", "DF-2"]


def test_classify_page_spread():
    W, H = 3024.0, 2160.0
    scattered = [(300, 300), (2100, 1900), (1200, 1000)]        # spans most of the sheet
    clustered = [(850, 1050), (860, 1200), (1000, 1400)]        # tight block (a legend/schedule)
    assert classify_page(scattered, W, H) == "instance_plan"
    assert classify_page(clustered, W, H) == "legend_block"
    assert classify_page([(1, 1)], W, H) == "sparse"            # too few tags


def test_extract_counts_on_enlarged_plan():
    # p58 (index 57) = "PLUMBING ENLARGED PLANS": tags scattered as real instances.
    counts = {c.symbol_id: c for c in extract_counts(DRAWINGS, _TAGS, page_range=range(57, 58))}
    assert "L-2" in counts and counts["L-2"].count >= 6
    assert "WC-1" in counts
    assert all(c.sheet_page == 58 for c in counts.values())
    assert all(c.source == "text_tag" and not c.verified for c in counts.values())
    assert counts["L-2"].boxes                                  # positions recorded


def test_legend_block_page_is_excluded():
    # p55 (index 54) = P2.1.A: tags packed into a tight block (embedded schedule) -> excluded.
    counts = extract_counts(DRAWINGS, _TAGS, page_range=range(54, 55))
    assert counts == []


def test_summarize_counts_flags_dedup_pending():
    counts = extract_counts(DRAWINGS, _TAGS, page_range=range(57, 58))
    s = summarize_counts(counts)
    assert s["dedup_status"] == "pending_verification"
    assert s["instance_sheets"] == [58]
    assert s["by_symbol"]["L-2"]["candidate_total"] >= 6
