from __future__ import annotations
import re
from typing import List
from hashlib import sha256
from narrative.sources.base import RawTextItem

# Patterns to detect price / market-move sentences. Edit this list to adjust behavior.
_PRICE_PATTERNS = [
    r"\b(shares|stock|stocks|index|futures)\b.*\b\d+(\.\d+)?%\b",                    # percentage symbol
    r"\b(?:[A-Z]{1,5}|shares|stock|stocks|index|futures|yields?)\b[^.!?]{0,40}\b(?:rose|fell|rallied|surged|slipped|moved|gained|lost)\b[^.!?]{0,40}\b\d+(\.\d+)?%\b",
    r"\bpoints\b",
    r"\b(up|down)\b.*\b(shares|stocks|index|futures|yields)\b",  # e.g. "up 5% on the S&P 500"
    r"rose to",              # phrases with context
    r"fell to",
]

# compile regexes once for performance / determinism
_COMPILED_PATTERNS = [re.compile(pat, flags=re.IGNORECASE) for pat in _PRICE_PATTERNS]

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?])\s+")


def strip_price_move_sentences(text: str) -> str:
    """
    Remove sentences that match any of the configured price/move patterns.
    Deterministic: splits on sentence boundaries and filters sentences using regex list.
    """
    if not text:
        return text
    sentences = _SENTENCE_SPLIT_RE.split(text)
    kept: List[str] = []
    for s in sentences:
        s_stripped = s.strip()
        if not s_stripped:
            continue
        matched = False
        for cre in _COMPILED_PATTERNS:
            if cre.search(s_stripped):
                matched = True
                break
        if not matched:
            kept.append(s_stripped)
    return " ".join(kept)


def normalize_whitespace(text: str) -> str:
    """
    Collapse consecutive whitespace (including newlines, tabs) into single spaces and trim.
    """
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clean_text(text: str) -> str:
    """
    Full cleaning pipeline (price-sentence stripping + whitespace normalization).
    """
    stripped = strip_price_move_sentences(text)
    return normalize_whitespace(stripped)


def dedupe_items(items: list[RawTextItem]) -> list[RawTextItem]:
    """
    Remove duplicates deterministically based on (source + normalized body hash).
    Keeps the first occurrence and preserves order of first-seen items.
    """
    seen = set()
    out: List[RawTextItem] = []
    for it in items:
        body_norm = clean_text(it.body or "")
        key_raw = f"{it.source}|{body_norm}"
        key = sha256(key_raw.encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
