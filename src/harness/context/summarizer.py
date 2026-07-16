from __future__ import annotations

from dataclasses import dataclass

from ..messages import Message, TextBlock, ToolCall, ToolResult, Transcript
from ..providers.base import Provider


SUMMARIZER_SYSTEM = """\
You are a conversation summarizer for an AI agent session.

Your job is to condense the provided conversation into a brief summary that
preserves:
- Key facts discovered (files read, values computed, decisions made).
- Open questions and in-progress subtasks.
- Which tools have been called and what they returned, in sequence.
- Any user-expressed preferences or constraints.

DO NOT:
- Invent information not present in the transcript.
- Omit tool calls — list each tool call with a one-line outcome.
- Exceed 1000 words.

Return plain prose. The summary replaces the original turns in the agent's
memory, so it must be accurate and complete.
"""


def _has_tool_result(m: Message) -> bool:
    return any(isinstance(b, ToolResult) for b in m.blocks)


@dataclass
class SummarizationResult:
    summary_text: str
    turns_replaced: int
    input_tokens: int
    output_tokens: int


async def summarize_prefix(
    transcript: Transcript,
    provider: Provider,
    keep_recent_turns: int,
) -> SummarizationResult | None:
    """Summarize turns before the last `keep_recent_turns`, leaving the first
    user message intact."""
    if len(transcript.messages) <= keep_recent_turns + 1:
        return None

    first_user = transcript.messages[0]
    prefix_end = len(transcript.messages) - keep_recent_turns

    # Never cut between a tool_call and its tool_result. A kept tool_result whose
    # originating tool_call landed in the summarized prefix is an orphan that both
    # provider APIs 400 on. Retreat the cut past any leading tool_result run so the
    # assistant turn that issued those calls is kept alongside its results.
    while prefix_end > 1 and _has_tool_result(transcript.messages[prefix_end]):
        prefix_end -= 1

    prefix_to_summarize = transcript.messages[1:prefix_end]
    if not prefix_to_summarize:
        return None

    # Render the prefix as text the summarizer can read.
    rendered_parts: list[str] = []
    for m in prefix_to_summarize:
        for block in m.blocks:
            match block:
                case TextBlock(text=t):
                    rendered_parts.append(f"[{m.role}] {t}")
                case ToolCall(name=n, args=a):
                    rendered_parts.append(f"[assistant→tool] {n}({a})")
                case ToolResult(content=c, is_error=err):
                    prefix = "[tool→error]" if err else "[tool→result]"
                    rendered_parts.append(f"{prefix} {c}")
    rendered = "\n".join(rendered_parts)

    sub_transcript = Transcript(system=SUMMARIZER_SYSTEM)
    sub_transcript.append(Message.user_text(
        f"Summarize this conversation.\n\n{rendered}"
    ))

    response = await provider.acomplete(sub_transcript, tools=[])
    summary_text = response.text or "(empty summary)"

    # Replace the prefix with a single synthetic message.
    summary_message = Message.user_text(
        f"[session summary — {len(prefix_to_summarize)} turns replaced]\n"
        f"{summary_text}"
    )
    transcript.messages[1:prefix_end] = [summary_message]

    return SummarizationResult(
        summary_text=summary_text,
        turns_replaced=len(prefix_to_summarize),
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
