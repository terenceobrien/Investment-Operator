from __future__ import annotations
from hashlib import sha256
from typing import Dict
from .base import BaseScorer, ChunkScore, ThemeScores


class StubScorer(BaseScorer):
    """
    Deterministic stub scorer: derives integer scores from SHA256(text).
    No randomness; same input -> same output across runs.
    """

    def _bytes_from_text(self, text: str) -> bytes:
        return sha256((text or "").encode("utf-8")).digest()

    def score(self, text: str) -> ChunkScore:
        b = self._bytes_from_text(text)
        # Use bytes to derive stable ints
        tone = (b[0] % 7) - 3          # maps to -3..3
        uncertainty = b[1] % 4        # maps to 0..3
        themes_vals = []
        # produce 5 theme values -2..2
        for i in range(5):
            themes_vals.append((b[2 + i] % 5) - 2)
        themes = ThemeScores(
            ai=themes_vals[0],
            inflation=themes_vals[1],
            liquidity=themes_vals[2],
            credit=themes_vals[3],
            consumer=themes_vals[4],
        )
        metadata: Dict = {"hex": sha256((text or "").encode("utf-8")).hexdigest()[:16]}
        return ChunkScore(tone=tone, uncertainty=uncertainty, themes=themes, metadata=metadata)