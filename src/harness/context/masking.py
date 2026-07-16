from __future__ import annotations

from ..messages import Message, ToolCall, ToolResult, Transcript


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


def drop_orphan_tool_results(transcript: Transcript) -> int:
    """Remove any ToolResult whose ToolCall is no longer in the transcript.

    A tool_result with no matching tool_use makes both provider APIs 400. The
    summarizer snaps its cut so it never produces one, so a non-zero return here
    means an upstream mutation left the transcript invalid — we repair it before
    sending, rather than firing a request we know will be rejected. Callers
    should log a non-zero result: it points at a compaction bug.

    A no-op when there are no orphans — the transcript object is left untouched,
    so the messages array stays byte-identical and the prompt cache holds.
    """
    call_ids = {b.id for m in transcript.messages
                for b in m.blocks if isinstance(b, ToolCall)}
    kept: list[Message] = []
    dropped = 0
    for m in transcript.messages:
        blocks = [b for b in m.blocks
                  if not (isinstance(b, ToolResult) and b.call_id not in call_ids)]
        dropped += len(m.blocks) - len(blocks)
        if not blocks:
            continue  # message held only orphan results; drop it whole
        kept.append(
            m if len(blocks) == len(m.blocks)
            else Message(role=m.role, blocks=blocks,
                         created_at=m.created_at, id=m.id)
        )
    if dropped:
        transcript.messages[:] = kept
    return dropped
