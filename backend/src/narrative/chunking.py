from __future__ import annotations
from typing import List

def chunk_text(text: str, max_chars: int = 2000, overlap: int = 200) -> List[str]:
    """
    Deterministic character-based chunking with fixed overlap.
    Preserves order, no empty chunks.
    """
    if text is None:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be >=0 and < max_chars")

    n = len(text)
    if n == 0:
        return []

    chunks: List[str] = []
    start = 0
    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end]
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        # advance start by window slide (end - overlap)
        start = end - overlap
        # ensure progress (prevent infinite loop)
        if start <= 0:
            start = end
    return chunks