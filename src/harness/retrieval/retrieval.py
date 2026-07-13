# src/harness/tools/retrieval.py
from __future__ import annotations

from ..retrieval.index import DocumentIndex
from ..tools.base import Tool
from ..tools.decorator import tool



class RetrievalInterface:
    def __init__(self, index: DocumentIndex) -> None:
        self.index = index

    def as_tools(self) -> list[Tool]:
        idx = self.index

        @tool(side_effects={"read"})
        def search_docs(query: str, k: int = 5) -> str:
            """Search the document corpus for chunks matching a query.

            query: keywords or a short sentence describing what you're
                   looking for.
            k: number of hits to return (default 5, max 10).

            Returns up to k hits, each with: doc_id, chunk_id, score,
            and the chunk text. Chunks are ~500 tokens each; plan your
            context budget before calling with k > 3.

            Side effects: reads the in-memory index.
            """
            k = min(max(1, k), 10)
            hits = idx.search(query, k=k)
            if not hits:
                return "(no results)"

            lines: list[str] = []
            total_chars = 0
            for hit in hits:
                c = hit.chunk
                lines.append(f"\n--- {c.doc_id}#{c.chunk_id} "
                             f"(score={hit.score:.2f}) ---")
                lines.append(c.text)
                total_chars += len(c.text)
            lines.append(f"\n[{len(hits)} hits, ~{total_chars} chars "
                         f"(~{total_chars // 4} tokens)]")
            return "\n".join(lines)

        return [search_docs]
