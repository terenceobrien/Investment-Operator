from __future__ import annotations
from datetime import datetime, date, timedelta, timezone
from typing import List, Optional, Dict, Tuple
import os
import math
import pandas as pd
import logging
from hashlib import sha256
import numpy as np
from scipy.stats import trim_mean

from narrative.sources import LocalFileSource, BaseSource, RawTextItem
# enrichment may be optional in tests
try:
    from narrative.enrich.article_fetch import enrich_items
except ImportError:  # pragma: no cover - enrichment module may be absent in some contexts
    enrich_items = None
from narrative.cleaning import clean_text, dedupe_items
from narrative.chunking import chunk_text
from narrative.scorers.stub import StubScorer
from narrative.normalize import add_normalized_columns
from narrative.utils import published_at_to_eastern_date

logger = logging.getLogger("narrative.daily")
logger.addHandler(logging.NullHandler())

CACHE_DIR = os.path.join("data", "narrative", "cache")
CACHE_PATH_PQ = os.path.join(CACHE_DIR, "chunk_scores.parquet")
CACHE_PATH_JSONL = os.path.join(CACHE_DIR, "chunk_scores.jsonl")

_THEME_KEYS = ("ai", "inflation", "liquidity", "credit", "consumer")


def _parse_date(d: str) -> date:
    return date.fromisoformat(d)


def _utc_dt_for_date(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def _date_range_weekdays(start: date, end: date) -> List[date]:
    out = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur = cur + timedelta(days=1)
    return out


def _load_cache() -> Dict[str, Dict]:
    """
    Load chunk score cache into a dict mapping chunk_hash -> score dict.
    Supports parquet or fallback JSONL.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = {}
    try:
        if os.path.exists(CACHE_PATH_PQ):
            df = pd.read_parquet(CACHE_PATH_PQ)
            for _, r in df.iterrows():
                cache[r["chunk_hash"]] = {
                    "tone": int(r["tone"]),
                    "uncertainty": int(r["uncertainty"]),
                    "themes": {
                        "ai": int(r["theme_ai"]),
                        "inflation": int(r["theme_inflation"]),
                        "liquidity": int(r["theme_liquidity"]),
                        "credit": int(r["theme_credit"]),
                        "consumer": int(r["theme_consumer"]),
                    },
                    "metadata": r.get("metadata", None),
                }
            logger.info("Loaded %d cached chunk scores (parquet)", len(cache))
            return cache
    except Exception:
        logger.exception("Failed to load parquet cache, falling back to jsonl")

    if os.path.exists(CACHE_PATH_JSONL):
        with open(CACHE_PATH_JSONL, "r", encoding="utf-8") as fh:
            import json
            for line in fh:
                try:
                    obj = json.loads(line)
                    cache[obj["chunk_hash"]] = obj["score"]
                except Exception:
                    continue
    logger.info("Loaded %d cached chunk scores (jsonl or empty)", len(cache))
    return cache


def _append_cache(new_entries: List[Tuple[str, Dict]]):
    """
    Append new_entries [(chunk_hash, score_dict), ...] to cache storage.
    """
    if not new_entries:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        records = []
        for ch, score in new_entries:
            rec = {
                "chunk_hash": ch,
                "tone": int(score["tone"]),
                "uncertainty": int(score["uncertainty"]),
                "theme_ai": int(score["themes"]["ai"]),
                "theme_inflation": int(score["themes"]["inflation"]),
                "theme_liquidity": int(score["themes"]["liquidity"]),
                "theme_credit": int(score["themes"]["credit"]),
                "theme_consumer": int(score["themes"]["consumer"]),
                "metadata": score.get("metadata", {}),
            }
            records.append(rec)
        df_new = pd.DataFrame.from_records(records)
        if os.path.exists(CACHE_PATH_PQ):
            try:
                df_old = pd.read_parquet(CACHE_PATH_PQ)
                df = pd.concat([df_old, df_new], ignore_index=True)
            except Exception:
                df = df_new
        else:
            df = df_new
        df = df.drop_duplicates(subset=["chunk_hash"], keep="first")
        df.to_parquet(CACHE_PATH_PQ, index=False)
        logger.info("Appended %d chunk scores to parquet cache", len(df_new))
        return
    except Exception:
        logger.exception("Parquet cache write failed; falling back to JSONL append")

    import json
    with open(CACHE_PATH_JSONL, "a", encoding="utf-8") as fh:
        for ch, score in new_entries:
            fh.write(json.dumps({"chunk_hash": ch, "score": score}, ensure_ascii=False) + "\n")
    logger.info("Appended %d chunk scores to jsonl cache", len(new_entries))


def _normalized_entropy_from_chunk_scores(chunk_scores: List[Dict]) -> float:
    """
    Compute normalized entropy [0,1] of dominant theme distribution across chunks.

    For each chunk:
    - find the theme with largest absolute score
    - ignore the chunk if all theme scores are 0
    - compute entropy over resulting dominant-theme counts
    - normalize by log(number_of_themes)
    """
    dominant_counts = {k: 0 for k in _THEME_KEYS}
    used = 0

    for c in chunk_scores:
        theme_vals = c["themes"]
        abs_vals = {k: abs(int(theme_vals[k])) for k in _THEME_KEYS}
        max_abs = max(abs_vals.values())
        if max_abs == 0:
            continue
        dominant_theme = max(abs_vals, key=abs_vals.get)
        dominant_counts[dominant_theme] += 1
        used += 1

    if used == 0:
        return 0.0

    probs = [count / used for count in dominant_counts.values() if count > 0]
    entropy = -sum(p * math.log(p) for p in probs)
    max_entropy = math.log(len(_THEME_KEYS))
    if max_entropy == 0:
        return 0.0
    return float(entropy / max_entropy)


def build_narrative_scores(
    start: str,
    end: str,
    sources: Optional[List[BaseSource]] = None,
) -> pd.DataFrame:
    """
    Build daily narrative scores between start and end (YYYY-MM-DD inclusive).
    - start/end are inclusive dates in YYYY-MM-DD.
    - Output contains weekdays only (Mon-Fri).
    """
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    fetch_start = _utc_dt_for_date(start_date)
    fetch_end = _utc_dt_for_date(end_date + timedelta(days=1))

    if sources is None:
        sources = [LocalFileSource()]

    items: List[RawTextItem] = []
    parse_errors_total = 0
    fetched_per_source: Dict[str, int] = {}
    article_enrichment_success_rate = None
    for src in sources:
        fetched = src.fetch(start=fetch_start, end=fetch_end)
        items.extend(fetched)
        fetched_per_source[src.__class__.__name__] = fetched_per_source.get(src.__class__.__name__, 0) + len(fetched)
        if hasattr(src, "last_parse_errors_count"):
            parse_errors_total += getattr(src, "last_parse_errors_count", 0)

    logger.info("Fetched items: %d (parse_errors=%d)", len(items), parse_errors_total)

    # optionally enrich items with full article text when available
    if enrich_items is not None:
        try:
            items = enrich_items(items)
        except Exception:
            # enrichment is best-effort; ignore failures
            pass

    enrichment_flags = [
        bool((it.metadata or {}).get("full_text_extraction_success"))
        for it in items
        if "full_text_extraction_success" in (it.metadata or {})
    ]
    if enrichment_flags:
        article_enrichment_success_rate = float(sum(enrichment_flags)) / len(enrichment_flags)

    deduped = dedupe_items(items)
    logger.info("Deduped items: %d -> %d", len(items), len(deduped))

    buckets: Dict[date, List[RawTextItem]] = {}
    for it in deduped:
        local_date = published_at_to_eastern_date(it.published_at)
        buckets.setdefault(local_date, []).append(it)

    days = _date_range_weekdays(start_date, end_date)

    scorer_type = os.getenv("NARRATIVE_SCORER", "stub").lower()
    model = ""
    prompt_ver = os.getenv("NARRATIVE_PROMPT_VERSION", "v1")
    if scorer_type == "llm":
        model = os.getenv("NARRATIVE_LLM_MODEL")
        if not model:
            raise RuntimeError("NARRATIVE_LLM_MODEL must be set when using llm scorer")
        from narrative.scorers.llm import LLMScorer
        scorer = LLMScorer(model=model, prompt_version=prompt_ver)
    else:
        scorer = StubScorer()

    cache = _load_cache()
    cache_hits = 0
    cache_total = 0
    cache_updates = []

    rows = []
    total_chunks = 0
    total_items_with_chunks = 0
    llm_call_count = 0

    for d in days:
        day_items = buckets.get(d, [])
        n_items = len(day_items)
        chunk_scores = []
        n_chunks = 0
        sources_set = set()

        for it in day_items:
            sources_set.add(it.source)
            cleaned = clean_text(it.body or "")
            chunks = chunk_text(cleaned)
            if chunks:
                total_items_with_chunks += 1
            n_chunks += len(chunks)
            total_chunks += len(chunks)

            for ch in chunks:
                ch_hash = sha256(f"{scorer_type}:{model}:{prompt_ver}:{ch}".encode()).hexdigest()
                cache_total += 1

                if ch_hash in cache:
                    cache_hits += 1
                    sc_dict = cache[ch_hash]
                    chunk_scores.append(sc_dict)
                else:
                    sc = scorer.score(ch)
                    llm_call_count += 1
                    scd = {
                        "tone": int(sc.tone),
                        "uncertainty": int(sc.uncertainty),
                        "themes": {
                            "ai": int(sc.themes.ai),
                            "inflation": int(sc.themes.inflation),
                            "liquidity": int(sc.themes.liquidity),
                            "credit": int(sc.themes.credit),
                            "consumer": int(sc.themes.consumer),
                        },
                        "metadata": sc.metadata or {},
                    }
                    chunk_scores.append(scd)
                    cache_updates.append((ch_hash, scd))
                    cache[ch_hash] = scd

        if chunk_scores:
            tones = [c["tone"] for c in chunk_scores]
            uncerts = [c["uncertainty"] for c in chunk_scores]
            themes = {
                "ai": [c["themes"]["ai"] for c in chunk_scores],
                "inflation": [c["themes"]["inflation"] for c in chunk_scores],
                "liquidity": [c["themes"]["liquidity"] for c in chunk_scores],
                "credit": [c["themes"]["credit"] for c in chunk_scores],
                "consumer": [c["themes"]["consumer"] for c in chunk_scores],
            }

            tone_mean = float(sum(tones) / len(tones))
            tone_trimmed_mean = float(trim_mean(tones, 0.1))
            tone_tail_risk = float(np.percentile(tones, 10))
            unc_mean = float(sum(uncerts) / len(uncerts))
            theme_means = {k: float(sum(v) / len(v)) for k, v in themes.items()}

            # New dispersion metrics
            narrative_dispersion = float(pd.Series(tones).std(ddof=0))
            theme_stds = {k: float(pd.Series(v).std(ddof=0)) for k, v in themes.items()}
            theme_dispersion = float(sum(theme_stds.values()) / len(theme_stds))
            narrative_entropy = _normalized_entropy_from_chunk_scores(chunk_scores)

            # Existing derived metrics, now explicitly tied to dispersion
            tone_std_clipped = max(0.0, min(3.0, narrative_dispersion))
            conviction = 3.0 - tone_std_clipped

            theme_dispersion_clipped = max(0.0, min(3.0, theme_dispersion))
            cohesion = 3.0 - theme_dispersion_clipped
        else:
            tone_mean = float("nan")
            tone_trimmed_mean = float("nan")
            tone_tail_risk = float("nan")
            unc_mean = float("nan")
            theme_means = {k: float("nan") for k in _THEME_KEYS}
            conviction = float("nan")
            cohesion = float("nan")
            narrative_dispersion = float("nan")
            theme_dispersion = float("nan")
            narrative_entropy = float("nan")

        row = {
            "date": d.isoformat(),
            "scorer_type": scorer_type.upper(),
            "tone": tone_mean,
            "tone_trimmed_mean": tone_trimmed_mean,
            "tone_tail_risk": tone_tail_risk,
            "uncertainty": unc_mean,
            "theme_ai": theme_means["ai"],
            "theme_inflation": theme_means["inflation"],
            "theme_liquidity": theme_means["liquidity"],
            "theme_credit": theme_means["credit"],
            "theme_consumer": theme_means["consumer"],
            "conviction": conviction,
            "cohesion": cohesion,
            "narrative_dispersion": narrative_dispersion,
            "theme_dispersion": theme_dispersion,
            "narrative_entropy": narrative_entropy,
            "n_items": n_items,
            "n_chunks": n_chunks,
            "n_sources": len(sources_set),
            "has_text": 1 if n_items > 0 else 0,
        }
        rows.append(row)

    _append_cache(cache_updates)
    cache_hit_rate = float(cache_hits) / cache_total if cache_total else 0.0

    df = pd.DataFrame(rows)
    cols = [
        "date",
        "scorer_type",
        "tone",
        "tone_trimmed_mean",
        "tone_tail_risk",
        "uncertainty",
        "theme_ai",
        "theme_inflation",
        "theme_liquidity",
        "theme_credit",
        "theme_consumer",
        "conviction",
        "cohesion",
        "narrative_dispersion",
        "theme_dispersion",
        "narrative_entropy",
        "n_items",
        "n_chunks",
        "n_sources",
        "has_text",
    ]
    df = df[cols]

    df = add_normalized_columns(df)
    z_cols = [c for c in df.columns if c.startswith("z_") and c != "z_is_expanding"]
    if z_cols:
        text_rows = df["has_text"] == 1
        nan_z_mask = df.loc[text_rows, z_cols].isna().any(axis=1)
        if bool(nan_z_mask.any()):
            nan_dates = df.loc[text_rows].loc[nan_z_mask, "date"]
            logger.warning(
                "NaN z-score values found for text-bearing rows between %s and %s",
                nan_dates.min(),
                nan_dates.max(),
            )
            raise AssertionError(
                f"NaN z-score values found for text-bearing rows between {nan_dates.min()} and {nan_dates.max()}"
            )
        days_with_nan_zscore = int(nan_z_mask.sum())
    else:
        days_with_nan_zscore = 0

    out_dir = os.path.join("data", "narrative")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "narrative_daily.csv")
    parquet_path = os.path.join(out_dir, "narrative_daily.parquet")

    df.to_csv(csv_path, index=False, columns=df.columns)
    try:
        df.to_parquet(parquet_path, index=False)
    except Exception:
        pass

    days_with_text = int(df["has_text"].sum())
    total_row_items = sum(r["n_items"] for r in rows)
    avg_chunks_per_item = float(total_chunks) / total_row_items if total_row_items else 0.0
    top_sources = sorted(fetched_per_source.items(), key=lambda x: x[1], reverse=True)[:5]

    logger.info(
        "run_summary: fetched=%d deduped=%d parse_errors=%d days_with_text=%d avg_chunks_per_item=%.3f cache_hit_rate=%.3f top_sources=%s",
        len(items),
        len(deduped),
        parse_errors_total,
        days_with_text,
        avg_chunks_per_item,
        cache_hit_rate,
        top_sources,
    )

    logger.info(
        {
            "total_items_fetched": len(items),
            "total_items_deduped": len(deduped),
            "total_chunks_scored": total_chunks,
            "cache_hit_rate": cache_hit_rate,
            "llm_call_count": llm_call_count,
            "article_enrichment_success_rate": article_enrichment_success_rate,
            "days_with_text": days_with_text,
            "days_with_nan_zscore": days_with_nan_zscore,
        }
    )

    return df