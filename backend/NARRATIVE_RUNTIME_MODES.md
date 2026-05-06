# Narrative Runtime Modes

Helix narrative reads support three backend runtime modes. Mode metadata is
returned by the backend response, so the frontend does not need separate
deployment config to show mock/cache status.

For live UI testing without LLM calls:

```env
NARRATIVE_MODE=mock
ALLOW_LLM_CALLS=false
```

For cache-only testing with real cached outputs:

```env
NARRATIVE_MODE=cache
ALLOW_LLM_CALLS=false
```

For real live synthesis:

```env
NARRATIVE_MODE=live
ALLOW_LLM_CALLS=true
```

Defaults are conservative:

```env
NARRATIVE_MODE=mock
ALLOW_LLM_CALLS=false
```

Changing these environment variables on a deployed backend usually requires a
backend restart or redeploy. Mock fixture data lives in
`backend/data/fixtures/narrative/` and is for UI testing only.

Ticker-specific narrative reads are intentionally limited to SPY and the
initial Magnificent 7 set: AAPL, MSFT, NVDA, AMZN, GOOGL, META, and TSLA.
Unsupported tickers return an unsupported response and do not trigger
generation.

To precompute one supported ticker:

```bash
python backend/scripts/precompute_narrative.py --ticker MSFT
```

To precompute the initial Magnificent 7 set:

```bash
python backend/scripts/precompute_narrative.py --magnificent7
```
