"""Tests for the Tier 3.1 M3 VLM verifier (count_verifier).

Offline: the stub client stands in for the model, so these exercise the merge /
reconcile / basis-flip logic and graceful degradation — never a real VLM call.
"""
from __future__ import annotations

from src.models.schedule import CountResult, ScheduleItem
from src.takeoff.count_verifier import (
    CountVerifier, StubVerifierClient, flip_fixture_items, merge, reconcile, verify_counts,
)


def _count(sym, page, n, conf=0.7, verified=False):
    return CountResult(symbol_id=sym, sheet_page=page, count=n, confidence=conf, verified=verified)


# --- verify + merge ------------------------------------------------------

def test_agreement_raises_confidence_and_marks_verified():
    v = CountVerifier(StubVerifierClient(default_agrees=True))
    r = merge(_count("WC-1", 58, 3), v.verify(_count("WC-1", 58, 3)))
    assert r.verified and r.count == 3            # count never overwritten
    assert r.confidence >= 0.9


def test_disagreement_keeps_count_but_drops_confidence():
    verdicts = {"L-2": {"verified_count": 8, "agrees": False, "confidence": 0.6, "notes": "legend inflated"}}
    v = CountVerifier(StubVerifierClient(verdicts))
    r = merge(_count("L-2", 58, 15, conf=0.7), v.verify(_count("L-2", 58, 15)))
    assert r.verified and r.count == 15           # deterministic count preserved
    assert r.confidence < 0.7                      # but flagged down


def test_verifier_error_degrades_to_unverified():
    def boom(req):
        raise RuntimeError("no network")
    r0 = _count("WC-1", 58, 3, conf=0.7)
    r = merge(r0, CountVerifier(boom).verify(r0))
    assert not r.verified and r.count == 3 and r.confidence == 0.7   # untouched


# --- reconcile -----------------------------------------------------------

def test_reconcile_single_sheet_total():
    rec = reconcile([_count("WC-1", 58, 3, verified=True)])
    assert rec["WC-1"]["building_total"] == 3
    assert rec["WC-1"]["verified"] and not rec["WC-1"]["multi_sheet_disagreement"]


def test_reconcile_multi_sheet_takes_max_and_flags():
    rec = reconcile([_count("L-2", 58, 15, verified=True), _count("L-2", 60, 12, verified=True)])
    assert rec["L-2"]["building_total"] == 15      # conservative: max, not sum (avoids double-count)
    assert rec["L-2"]["multi_sheet_disagreement"]


# --- flip ----------------------------------------------------------------

def test_flip_only_verified_fixtures():
    items = [
        ScheduleItem("plumbing_fixture", "catalog", "WC-1", None, None, "unknown_plan_count"),
        ScheduleItem("plumbing_fixture", "catalog", "L-9", None, None, "unknown_plan_count"),
    ]
    reconciled = {
        "WC-1": {"building_total": 3, "verified": True, "confidence": 0.9,
                 "sheets": [], "multi_sheet_disagreement": False},
        "L-9": {"building_total": 2, "verified": False, "confidence": 0.0,
                "sheets": [], "multi_sheet_disagreement": False},
    }
    flip_fixture_items(items, reconciled)
    by = {i.mark: i for i in items}
    assert by["WC-1"].quantity == 3.0 and by["WC-1"].unit == "EA"
    assert by["WC-1"].quantity_basis == "plan_count"
    assert by["WC-1"].attributes["plan_count_confidence"] == 0.9
    # unverified stays count-pending — never stub-faked
    assert by["L-9"].quantity is None and by["L-9"].quantity_basis == "unknown_plan_count"


# --- driver --------------------------------------------------------------

def test_verify_counts_offline_no_render():
    counts = [_count("WC-1", 58, 3), _count("L-2", 58, 15)]
    out = verify_counts(counts, CountVerifier(StubVerifierClient()), pdf_path=None, render=False)
    assert all(c.verified for c in out)            # stub agrees -> all verified
