from __future__ import annotations

from typing import Optional
import os
import pandas as pd
import yfinance as yf

from src.data.macro import _fred_client, _to_series


INDICATOR_XLSX = os.path.join("data", "research", "indicators.xlsx")


def _load_indicator_list(path: str = INDICATOR_XLSX) -> pd.DataFrame:
    """Read the spreadsheet listing indicators and their sources."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Indicator configuration not found at {path}")
    df = pd.read_excel(path, sheet_name=0)
    return df


def fetch_indicator_series(source: str, series_id: str, start: Optional[str] = None, end: Optional[str] = None) -> pd.Series:
    """Fetch a single time series from the specified source."""
    source = source.strip().lower()
    if source == "fred":
        fred = _fred_client()
        try:
            raw = fred.get_series(series_id)
        except Exception:
            return pd.Series(dtype=float)
        s = _to_series(raw)
    elif source in ("yahoo finance", "cboe"):
        try:
            tk = yf.Ticker(series_id)
            hist = tk.history(period="max", interval="1d")
        except Exception:
            return pd.Series(dtype=float)
        if hist is None or hist.empty:
            return pd.Series(dtype=float)
        s = hist["Close"].copy()
        s.index = pd.to_datetime(s.index)
        # drop timezone info to avoid combining with naive FRED series
        if hasattr(s.index, "tz") and s.index.tz is not None:
            s.index = s.index.tz_convert(None)
        # collapse to calendar date (keep last observation of day)
        s.index = s.index.normalize()
        s = s.groupby(s.index).last()
    else:
        raise ValueError(f"Unsupported source '{source}' for series '{series_id}'")

    # restrict to date range if requested but do not forward-fill
    if start or end:
        s = s.loc[(s.index >= start if start else True) & (s.index <= end if end else True)]
    return s


def gather_all_indicators(output_csv: str, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    """Pull all indicators defined in the spreadsheet and save to CSV.

    Non-daily series will only have values on their native observation dates
    (no resampling or forward-filling).
    """
    df = _load_indicator_list()
    series_dict = {}
    pulled_originals: list[str] = []
    # override mapping for specific tickers that share a common display name
    name_overrides = {
        "^VIX": "VIX",
        "^VIX3M": "VIX 3M",
    }

    for _, row in df.iterrows():
        name = row.get("Indicator") or row.get("indicator")
        src = row.get("Source") or row.get("source")
        sid = row.get("ID") or row.get("id")
        if pd.isna(name) or pd.isna(src) or pd.isna(sid):
            continue
        name = str(name).strip()
        sid = str(sid).strip()
        # apply overrides if provided
        colname = name_overrides.get(sid, name)
        # if the name already exists (duplicate non-overridden), append series id
        if colname in series_dict and colname not in name_overrides.values():
            colname = f"{colname} ({sid})"
        try:
            s = fetch_indicator_series(src, sid, start=start, end=end)
        except Exception:
            s = pd.Series(dtype=float)
        if not s.empty:
            s.name = colname
            series_dict[colname] = s
            pulled_originals.append(name)
            # compute percentiles based on non-null values throughout the sample
            non_null = s.dropna()
            if not non_null.empty:
                ranks = non_null.rank(pct=True)
                pct_series = pd.Series(index=s.index, dtype=float)
                pct_series.loc[non_null.index] = ranks
                pct_series.name = f"{colname}_percentile"
                series_dict[pct_series.name] = pct_series
                # compute buckets: 10 equal percentile bins
                bucket_series = pd.cut(pct_series, bins=[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], labels=range(1, 11), right=True)
                bucket_series.name = f"{colname} Bucket"
                series_dict[bucket_series.name] = bucket_series
    if not series_dict:
        out_df = pd.DataFrame()
    else:
        out_df = pd.concat(series_dict.values(), axis=1)
        out_df = out_df.sort_index()
        # forward-fill less frequent data so values propagate to daily grid
        out_df = out_df.ffill()
    # persist
    out_dir = os.path.dirname(output_csv)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    out_df.to_csv(output_csv, index_label="date")

    # also write indicators_returned list (only those with data)
    returned_path = os.path.join(out_dir, "indicators_returned.csv")
    try:
        # original indicator names that produced data (deduplicated)
        unique_inds = sorted(set(pulled_originals))
        ret_df = df[df["Indicator"].isin(unique_inds)]
        # drop repeated rows where the spreadsheet listed the same name twice
        ret_df = ret_df.drop_duplicates(subset="Indicator")
        ret_df.to_csv(returned_path, index=False)
    except Exception:
        pass

    return out_df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gather indicator time series into CSV")
    parser.add_argument("--output", default="data/research/indicators_all.csv", help="Output CSV path")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    dfout = gather_all_indicators(args.output, start=args.start, end=args.end)
    print(f"Wrote {len(dfout)} rows with {len(dfout.columns)} indicators to {args.output}")
