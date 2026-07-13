from __future__ import annotations

from ..messages import Message, ToolResult, Transcript


MASK_TEMPLATE = "[tool_result elided; call_id={call_id}; original_tokens={tokens}]"


def mask_older_results(
    transcript: Transcript,
    keep_recent: int,
    encoder,
) -> int:
    """Replace tool-result content in all but the most recent `keep_recent` turns.

    Returns the number of tokens freed.
    """
    results: list[tuple[int, int, ToolResult]] = []
    for mi, message in enumerate(transcript.messages):
        for bi, block in enumerate(message.blocks):
            if isinstance(block, ToolResult):
                results.append((mi, bi, block))

    if len(results) <= keep_recent:
        return 0

    # mask everything except the last `keep_recent`
    to_mask = results[:-keep_recent]
    freed = 0
    for mi, bi, block in to_mask:
        if block.content.startswith("[tool_result elided"):
            continue  # already masked
        tokens = len(encoder.encode(block.content))
        new_content = MASK_TEMPLATE.format(call_id=block.call_id, tokens=tokens)
        new_block = ToolResult(
            call_id=block.call_id,
            content=new_content,
            is_error=block.is_error,
        )
        new_blocks = list(transcript.messages[mi].blocks)
        new_blocks[bi] = new_block
        transcript.messages[mi] = Message(
            role=transcript.messages[mi].role,
            blocks=new_blocks,
            created_at=transcript.messages[mi].created_at,
            id=transcript.messages[mi].id,
        )
        freed += tokens - len(encoder.encode(new_content))
    return freed
