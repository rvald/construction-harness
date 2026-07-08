"""Run-scoped configuration for the takeoff access layer.

Each field replaces a magic constant that used to live inside a driver, so a run is
parameterized in one place and dumpable into the run manifest via .model_dump().
Defaults reproduce today's behavior exactly — the golden report is the guardrail.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TakeoffConfig(BaseModel):
    """Immutable, validated parameters for one takeoff run."""

    model_config = ConfigDict(frozen=True)

    render_dpi: int = Field(
        default=100, ge=1,
        description="DPI for rendering a sheet to PNG for the VLM verifier.",
    )
    spread_threshold: float = Field(
        default=0.35, ge=0.0, le=1.0,
        description="Min fraction of the sheet a tag set must span to count as an "
                    "instance plan vs a clustered legend.",
    )
    min_tags: int = Field(
        default=3, ge=1,
        description="Fewest tags before a sheet can be an instance plan.",
    )
    page_range: tuple[int, int] | None = Field(
        default=None,
        description="0-based half-open [start, end) page window; None = all pages.",
    )

    @model_validator(mode="after")
    def _check_page_range(self) -> TakeoffConfig:
        if self.page_range is not None:
            start, end = self.page_range
            if start < 0 or start >= end:
                raise ValueError(f"page_range must be 0 <= start < end, got {self.page_range!r}")
        return self
