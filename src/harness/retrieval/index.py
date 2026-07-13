from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


@dataclass
class Chunk:
    doc_id: str
    chunk_id: int
    text: str


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


class DocumentIndex:
    """A BM25 index over text files in a directory.

    Chunks files into ~500-token pieces with 50-token overlap.
    """

    def __init__(self, root: Path | str, chunk_tokens: int = 500,
                 overlap: int = 50) -> None:
        self.root = Path(root)
        self.chunks: list[Chunk] = []
        self._build(chunk_tokens, overlap)
        tokenized = [_tokenize(c.text) for c in self.chunks]
        self._bm25 = BM25Okapi(tokenized)

    def _build(self, chunk_tokens: int, overlap: int) -> None:
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError):
                continue
            words = text.split()
            for i, start in enumerate(range(0, len(words),
                                             chunk_tokens - overlap)):
                chunk_text = " ".join(words[start:start + chunk_tokens])
                if chunk_text.strip():
                    self.chunks.append(Chunk(
                        doc_id=str(path.relative_to(self.root)),
                        chunk_id=i,
                        text=chunk_text,
                    ))

    def search(self, query: str, k: int = 5) -> list[SearchHit]:
        tokenized_query = _tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)
        indexed = sorted(enumerate(scores), key=lambda x: -x[1])[:k]
        return [SearchHit(chunk=self.chunks[i], score=s)
                for i, s in indexed if s > 0]
