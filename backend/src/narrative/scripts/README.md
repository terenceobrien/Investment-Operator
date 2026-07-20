# Narrative Daily Refresh

`daily_refresh.py` runs the narrative synthesis engine once for each daily
market subject and writes subject-specific snapshots under `data/snapshots/`.

Current subjects:

- `SPY`: broad market / S&P 500 read
- `QQQ`: Nasdaq-100 / mega-cap tech read

The command exits with status `0` only when every subject succeeds. If one
subject fails, successful snapshots are still written and the process exits
non-zero so Railway marks the run as failed.

## Manual Run

From the backend directory:

```bash
python -m src.narrative.scripts.daily_refresh
```

Expected outputs:

- `data/snapshots/narrative_state_YYYY-MM-DD_SPY.json`
- `data/snapshots/narrative_state_YYYY-MM-DD_QQQ.json`

The script logs one line per major step, including bundle item counts, selected
LLM item counts, ledger counts, elapsed time, and final success/failure totals.

## Stub Mode

If narrative generation is not live, the script writes clearly marked stub
snapshots instead of calling the LLM. This is useful for testing deployment
wiring without spending model tokens.

```bash
ALLOW_LLM_CALLS=false python -m src.narrative.scripts.daily_refresh
```

Stub snapshots include `_meta.is_stub: true` and placeholder content saying the
snapshot is a stub for testing.

## Railway Cron Setup

Recommended service name: `narrative-refresh`.

Dashboard setup:

1. Add a new service to the Railway project.
2. Point it at the same GitHub repo.
3. Set the service root/config to the backend app. If using Config as Code,
   set the custom config path to `/backend/railway.narrative-refresh.toml`.
4. Set the start command to:

   ```bash
   python -m src.narrative.scripts.daily_refresh
   ```

5. In Settings -> Cron Schedule, enter:

   ```cron
   0 10 * * *
   ```

   Railway cron schedules are UTC, so this runs at 10:00 UTC.

6. Ensure the service has the same narrative/data environment variables as the
   main FastAPI service.

## Environment Variables

Required for live runs:

- `OPENAI_API_KEY`
- `FINNHUB_API_KEY`
- `NARRATIVE_MODE=live`
- `ALLOW_LLM_CALLS=true`

Recommended when regime snapshots may need to be built:

- `FRED_API_KEY`

Optional:

- `NARRATIVE_FINAL_MODEL` (defaults in `src/narrative/config.py`)
- `NARRATIVE_PREPROCESS_MODEL`
- `NARRATIVE_PROMPT_VERSION`
- `NARRATIVE_SOURCE_CONFIG_VERSION`
- `NARRATIVE_CACHE_DIR`
- `NARRATIVE_REFRESH_LOG_LEVEL`
- `NARRATIVE_REFRESH_OPENAI_TIMEOUT_SEC` (default `240`)

To disable live refresh for cost control, set `ALLOW_LLM_CALLS=false`, set
`NARRATIVE_MODE=mock` or `cache`, or disable the Railway cron schedule.

## Failure Handling

If a daily run fails:

1. Check Railway logs for the failing subject and exception.
2. Confirm required environment variables are present on the cron service.
3. Confirm source APIs are reachable and quota is available.
4. Re-run the command manually from Railway or locally after fixing the issue.

Partial failure is intentional: if `SPY` succeeds and `QQQ` fails, the `SPY`
snapshot remains usable, but the process exits non-zero.

## Storage Caveat

Railway service files outside a volume are ephemeral and local to that service.
Do not assume snapshots written by the `narrative-refresh` cron service will be
visible to the main FastAPI service unless both are configured to read/write the
same persistent storage.

For this phase, the script writes local files. Before relying on these snapshots
in production, configure one of:

- A Railway volume strategy that makes `data/snapshots/` available where the
  FastAPI service reads it.
- External object storage such as S3.
- A future persistence layer in the narrative query service.

Railway's relative path guidance means a volume intended to persist `./data`
should be mounted at `/app/data` for a Nixpacks/Railpack app.
