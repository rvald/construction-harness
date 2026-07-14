from __future__ import annotations

import logging
from dataclasses import dataclass

from ..messages import Transcript
from ..providers.base import Provider
from .accountant import ContextAccountant
from .masking import mask_older_results
from .summarizer import summarize_prefix


log = logging.getLogger(__name__)


@dataclass
class CompactionResult:
    masking_tokens_freed: int = 0
    summarization_turns_replaced: int = 0
    summarization_tokens: int = 0
    final_state: str = "green"


class Compactor:
    def __init__(
        self,
        accountant: ContextAccountant,
        provider: Provider,
        keep_recent_results: int = 3,
        keep_recent_turns_on_summary: int = 6,
    ) -> None:
        self.accountant = accountant
        self.provider = provider
        self.keep_recent_results = keep_recent_results
        self.keep_recent_turns_on_summary = keep_recent_turns_on_summary

    async def compact_if_needed(
        self,
        transcript: Transcript,
        tools: list[dict],
    ) -> CompactionResult:
        result = CompactionResult()
        snap = self.accountant.snapshot(transcript, tools=tools)
        result.final_state = snap.state
        if snap.state != "red":
            return result

        # Step 1: mask older tool results.
        freed = mask_older_results(transcript, self.keep_recent_results,
                                    self.accountant._enc)
        result.masking_tokens_freed = freed
        snap = self.accountant.snapshot(transcript, tools=tools)
        result.final_state = snap.state
        if snap.state != "red":
            return result

        # Step 2: summarize prefix.
        summary = await summarize_prefix(
            transcript, self.provider, self.keep_recent_turns_on_summary
        )
        if summary is not None:
            result.summarization_turns_replaced = summary.turns_replaced
            result.summarization_tokens = summary.output_tokens

        snap = self.accountant.snapshot(transcript, tools=tools)
        result.final_state = snap.state
        if snap.state == "red":
            log.warning("compaction could not bring transcript under red threshold")

        return result
