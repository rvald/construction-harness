"""A1 tests (ADR-004): config knobs on submit — validation, normalization, and threading
into the pipeline. Fast — no DB, no pdfplumber (the pipeline call is spied, not run)."""
from __future__ import annotations

import pytest

from service.api.ingestions import _resolve_config as api_resolve
from service.core.errors import ApiError
from service.takeoff.planner import plan_shard_windows
from service.core.schemas import TakeoffConfigIn


# --- validation + normalization ------------------------------------------------

def test_defaults_are_the_golden():
    assert TakeoffConfigIn().model_dump() == {
        "render_dpi": 100, "spread_threshold": 0.35, "min_tags": 3, "page_range": None,
    }


def test_omitted_and_explicit_defaults_normalize_identically():
    # dedup-stability: 'omit config' and 'pass the defaults' must store the same dict
    assert api_resolve(None) == api_resolve('{"render_dpi": 100, "min_tags": 3}')


@pytest.mark.parametrize("bad", [
    '{"render_dpi": 0}',
    '{"spread_threshold": 1.5}',
    '{"min_tags": 0}',
    '{"page_range": [5, 5]}',
    '{"page_range": [-1, 3]}',
    '{"unknown_knob": 1}',
    'not json',
])
def test_invalid_config_rejected(bad):
    with pytest.raises(ApiError) as ei:
        api_resolve(bad)
    assert ei.value.status_code == 422


# --- config -> (TakeoffConfig, page_range) mapping -----------------------------

def test_adapter_resolve_defaults():
    from service.takeoff.pipeline_adapter import _resolve_config
    tc, page_range = _resolve_config(None)
    assert tc.render_dpi == 100 and tc.spread_threshold == 0.35 and tc.min_tags == 3
    assert page_range is None


def test_adapter_resolve_with_values():
    from service.takeoff.pipeline_adapter import _resolve_config
    tc, page_range = _resolve_config({"render_dpi": 150, "min_tags": 5, "page_range": [0, 50]})
    assert tc.render_dpi == 150 and tc.min_tags == 5
    assert list(page_range) == list(range(0, 50))


# --- threading: run_takeoff hands the resolved config to the builder ------------

def test_run_takeoff_threads_config(monkeypatch):
    import src.takeoff.build_schedule_items as bsi
    captured = {}

    def spy(source, *, config=None, page_range=None):
        captured["config"] = config
        captured["page_range"] = page_range
        return ({}, {})

    monkeypatch.setattr(bsi, "build_schedule_items", spy)
    from service.takeoff.pipeline_adapter import run_takeoff
    run_takeoff("x.pdf", config={"render_dpi": 120, "page_range": [10, 40]})
    assert captured["config"].render_dpi == 120
    assert list(captured["page_range"]) == list(range(10, 40))


# --- planner honors a submit-time page window ----------------------------------

def test_planner_windows_within_page_range():
    # candidates across the whole doc, but the job is bounded to pages [40, 90)
    candidates = list(range(0, 100, 5))
    windows = plan_shard_windows(candidates, 100, 4, page_start=40, page_end=90)
    assert windows[0].start == 40
    assert windows[-1].end == 90
    for w in windows:
        assert 40 <= w.start < w.end <= 90
        assert w.candidate_count <= 4


def test_planner_defaults_unchanged():
    # regression: default args still cover [0, total)
    w = plan_shard_windows([1, 2, 3], 10, 30)
    assert (w[0].start, w[0].end) == (0, 10)
