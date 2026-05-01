# Legacy code

Code in this folder is preserved for reference but is no longer part of the
active product. It is committed to version control intentionally so that
historical work is recoverable, but it is not imported, tested, or executed
by any live code path.

## narrative_pipeline_a/

The original "daily narrative scoring" pipeline. This pipeline produced a
daily time series of numeric tone, uncertainty, and theme scores by:
chunking text into ~2000-character windows, scoring each chunk via an LLM
or deterministic stub, aggregating chunk scores per US/Eastern weekday,
and computing rolling z-scores.

It was deprecated in favor of the qualitative LLM synthesis pipeline
(`src/narrative/bundle.py` + `src/narrative/synth.py`), which produces
structured prose narrative snapshots against a curated bundle of recent
items in a single LLM call.

If the daily score time series is ever needed again (for example, to chart
narrative tone over time on a frontend page), this code can be revived by
moving the relevant files back into `src/narrative/`.

Moved on: 2026-04-28
