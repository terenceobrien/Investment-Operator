# Full-Article Enrichment

This project includes an optional enrichment stage for `RawTextItem`s fetched from RSS sources.  The goal is to upgrade headline/summary snippets to the full article text when available, without touching the downstream scoring or aggregation pipeline.

## How it works

1. After items are fetched by RSS sources, `daily.build_narrative_scores` calls `enrich_items` from `src/narrative/enrich/article_fetch.py`.
2. Each item with a non-empty `url` is processed:
   * The system looks up the URL hash in a cache (`data/narrative/cache/article_text_cache.*`).
   * On cache miss it fetches the HTML via a `requests.Session` with retries,
     extracts the main article using `trafilatura.extract`, and normalizes the text.
   * If the extracted text is significantly longer than the summary (≥300 chars or
     ≥50 words), the item's `body` is replaced and metadata is updated.
   * All outcomes (success/failure, word counts, errors) are recorded in both
     the item's `metadata` and the persistent cache.
3. Failures (HTTP errors, extraction problems, or too-short text) leave the
   original summary in place; the pipeline remains deterministic and network-free
   during tests.

## Cache details

- Location: `data/narrative/cache/article_text_cache.parquet` with a JSONL
  fallback.
- Schema: each record contains `url_hash`, `url`, `fetched_at`,
  `extraction_success`, `extracted_text`, `word_count`, and `error`.
- The cache prevents repeated network requests for the same article across
  pipeline runs.

The enrichment stage is opt-in and can be skipped in environments where
`narrative.enrich.article_fetch` isn't available (tests, lightweight installs).