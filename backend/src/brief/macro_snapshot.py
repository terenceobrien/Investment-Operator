from __future__ import annotations

from typing import List, Dict, Tuple
import pandas as pd
from datetime import timedelta
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.data.macro import _fred_client, _to_series


# --- indicator configuration: (display name, fred series id) ---
_INDICATORS: List[Tuple[str, str]] = [
    ("High Yield Credit Spread", "BAMLH0A0HYM2"),
    ("VIX", "VIXCLS"),
    ("10Y Treasury Yield", "GS10"),
    ("10Y Real Yield", "T10YIR"),
    ("10Y-2Y Yield Curve", "T10Y2Y"),
    ("Unemployment Rate", "UNRATE"),
    ("ISM Manufacturing PMI", "NAPMPMI"),  # approximate id
    ("Net Liquidity", "NET_LIQ"),  # uses existing net liquidity series from macro
]


def _fetch_series(series_id: str) -> pd.Series:
    fred = _fred_client()
    try:
        raw = fred.get_series(series_id, timeout=5)  # add timeout
    except Exception:
        return pd.Series(dtype=float)
    s = _to_series(raw)
    return s


def assemble_snapshot_data() -> List[Dict]:
    def fetch_one(name, sid):
        s = _fetch_series(sid)
        if s.empty:
            return {"name": name, "current": float("nan"),
                    "previous": float("nan"), "delta": float("nan"), "history": s}
        s = s.sort_index()
        curr = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) >= 2 else float("nan")
        delta = curr - prev if pd.notna(curr) and pd.notna(prev) else float("nan")
        return {"name": name, "current": curr, "previous": prev, "delta": delta, "history": s}

    results = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_one, name, sid): (i, name)
                   for i, (name, sid) in enumerate(_INDICATORS)}
        for future in as_completed(futures):
            i, name = futures[future]
            results[i] = future.result()

    return [results[i] for i in sorted(results)]


def slice_history(history: pd.Series, years: int) -> pd.Series:
    if history.empty:
        return history
    # take last ``years`` years of data
    last = history.index.max()
    cutoff = last - pd.DateOffset(years=years)
    return history[history.index >= cutoff]


# --- rendering helpers ------------------------------------------------------

def _fmt_val(v) -> str:
    if pd.isna(v):
        return "n/a"
    # percentages or rates might be <1 but we can't know here; just two decimals
    return f"{v:,.2f}"


def render_snapshot(data: List[Dict], default_years: int = 1) -> None:
    """Render the macro snapshot header in Streamlit with a timeframe selector."""
    st.subheader("Macro Snapshot")
    tf = st.selectbox("Timeframe", ["1Y", "3Y", "5Y"], index={1:0,3:1,5:2}.get(default_years,0), key="snapshot_tf")
    years = int(tf.replace("Y", ""))

    ncols = 4
    cols = st.columns(ncols, gap="large")
    for idx, item in enumerate(data):
        col = cols[idx % ncols]
        with col:
            st.markdown(f"**{item['name']}**")
            val = item.get("current")
            delta = item.get("delta")
            delta_str = f"{delta:+.2f}" if pd.notna(delta) else ""
            st.metric(label="", value=_fmt_val(val), delta=delta_str, label_visibility="hidden")
            hist = slice_history(item.get("history", pd.Series(dtype=float)), years)
            if hist is not None and not hist.empty:
                # show simple line chart
                st.line_chart(hist, width='stretch', height=100)
    st.divider()
