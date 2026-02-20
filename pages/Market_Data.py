from __future__ import annotations

from dataclasses import dataclass
from typing import List
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime , timedelta

from src.data.market import fetch_market_moves

st.set_page_config(page_title="Market Data", layout="wide")
st.title("Market Data - Price Action and Technical Indicators")

DEFAULT_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "TLT", "HYG", "GLD", "USO", "BTC-USD"]

CROSS_ASSET_LABELS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "DIA": "Dow",
    "TLT": "20Y+ Treas",
    "HYG": "High Yield",
    "GLD": "Gold",
    "USO": "Oil",
    "BTC-USD": "Bitcoin",
}

# 3x3 grid (simple + clean)
CROSS_ASSET_GRID_ORDER = [
    "SPY", "QQQ", "IWM",
    "DIA", "TLT", "HYG",
    "GLD", "USO", "BTC-USD",
]

SECTORS = {
    "XLB": "Materials",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLK": "Technology",
    "XLP": "Staples",
    "XLU": "Utilities",
    "XLV": "Health Care",
    "XLY": "Discretionary",
    "XLC": "Comm Services",
    "XLRE": "Real Estate",
}

HORIZONS = {
    "1D": 1,
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
    "YTD": "YTD",
}

HORIZON_COLOR_RANGES = {
    "1D": 5,
    "1W": 10,
    "1M": 20,
    "3M": 40,
    "6M": 60,
    "1Y": 100,
    "YTD": 100,
}

col1, col2 = st.columns([1, 3])
with col1:
    horizon_label = st.selectbox("Horizon", list(HORIZONS.keys()), index=0)
    use_adj_close = st.toggle("Use Adjusted Close", value=True)

tickers = list(SECTORS.keys())

@st.cache_data(ttl=300)
def fetch_prices(tickers: list[str], period="1y", interval="1d", auto_adjust=True) -> pd.DataFrame:
    data = yf.download(
        tickers,
        period=period,
        interval=interval,
        group_by="ticker",
        auto_adjust=auto_adjust,
        progress=False,
        threads=True,
    )
    # yf returns different shapes depending on # tickers
    if isinstance(data.columns, pd.MultiIndex):
        # Take Close from each ticker
        close = pd.DataFrame({t: data[t]["Close"] for t in tickers})
    else:
        close = data[["Close"]].rename(columns={"Close": tickers[0]})
    close = close.dropna(how="all")
    return close

prices = fetch_prices(tickers, period="2y", auto_adjust=use_adj_close)

def compute_return(series: pd.Series, horizon) -> float:
    s = series.dropna()
    if len(s) < 2:
        return np.nan

    if horizon == "YTD":
        year_start = pd.Timestamp(datetime.now().year, 1, 1)
        # nearest trading day on/after year_start
        ytd_slice = s[s.index >= year_start]
        if ytd_slice.empty:
            return np.nan
        start = ytd_slice.iloc[0]
        end = ytd_slice.iloc[-1]
        return (end / start - 1.0) * 100.0

    n = int(horizon)
    if len(s) <= n:
        return np.nan
    start = s.iloc[-(n + 1)]
    end = s.iloc[-1]
    return (end / start - 1.0) * 100.0

h = HORIZONS[horizon_label]
rets = {t: compute_return(prices[t], h) for t in tickers}

cross_prices = fetch_prices(DEFAULT_TICKERS, period="2y", auto_adjust=use_adj_close)
cross_rets = {t: compute_return(cross_prices[t], h) for t in DEFAULT_TICKERS}

df = (
    pd.DataFrame(
        {
            "Ticker": tickers,
            "Sector": [SECTORS[t] for t in tickers],
            "Return_%": [rets[t] for t in tickers],
        }
    )
    .sort_values("Return_%", ascending=False)
    .reset_index(drop=True)
)

# --- Heatmap layout (simple 3x4 grid) ---
grid_order = [
    "XLK", "XLY", "XLC", "XLF",
    "XLV", "XLI", "XLB", "XLE",
    "XLP", "XLU", "XLRE", None,
]
st.subheader("Broad Market Returns")

cross_grid = []
cross_labels = []
for t in CROSS_ASSET_GRID_ORDER:
    r = cross_rets.get(t, np.nan)
    cross_grid.append(r)
    name = CROSS_ASSET_LABELS.get(t, t)
    if pd.isna(r):
        cross_labels.append(f"{name}<br>n/a")
    else:
        cross_labels.append(f"{name}<br>{r:.2f}%")

cross_grid = np.array(cross_grid).reshape(3, 3)
cross_labels = np.array(cross_labels).reshape(3, 3)

# Use same horizon-dependent scaling logic you already defined
max_abs_cross = HORIZON_COLOR_RANGES.get(horizon_label, 50)

cross_fig = px.imshow(
    cross_grid,
    text_auto=False,
    aspect="auto",
    color_continuous_scale=[
        [0.0, "#7f1d1d"],  # deep red
        [0.5, "#1f2937"],  # neutral dark
        [1.0, "#065f46"],  # deep green
    ],
    origin="upper",
    zmin=-max_abs_cross,
    zmax=max_abs_cross,
)

cross_fig.update_traces(
    text=cross_labels,
    texttemplate="%{text}",
    hovertemplate="%{text}<extra></extra>",
)

cross_fig.update_layout(
    height=360,
    margin=dict(l=10, r=10, t=10, b=10),
    coloraxis_colorbar=dict(title=f"{horizon_label} %"),
)

st.plotly_chart(cross_fig, use_container_width=True)

st.divider()

@st.cache_data(ttl=300)
def get_default_ticker_moves(tickers: list[str]) -> pd.DataFrame:
    return fetch_market_moves(tickers)

moves_df = get_default_ticker_moves(DEFAULT_TICKERS)

if moves_df is None or moves_df.empty:
    st.caption("No data returned.")
else:
    st.dataframe(
        moves_df.style.format({"last": "{:.2f}", "chg_pct_1d": "{:+.2f}%"}),
        use_container_width=True,
        hide_index=True
    )

st.divider()
st.subheader("Sector Returns")

grid = []
labels = []
for t in grid_order:
    if t is None:
        grid.append(np.nan)
        labels.append("")
    else:
        grid.append(rets.get(t, np.nan))
        labels.append(f"{SECTORS[t]}<br>{rets.get(t, np.nan):.2f}%")

grid = np.array(grid).reshape(3, 4)
labels = np.array(labels).reshape(3, 4)

max_abs = HORIZON_COLOR_RANGES.get(horizon_label, 50)

fig = px.imshow(
    grid,
    text_auto=False,
    aspect="auto",
   color_continuous_scale=[
    [0.0, "#7f1d1d"],  # deep red
    [0.5, "#1f2937"],  # neutral dark
    [1.0, "#065f46"],  # deep green
    ],
    origin="upper",
    zmin=-max_abs,
    zmax=max_abs,
)

# Put our custom labels on top
fig.update_traces(
    text=labels,
    texttemplate="%{text}",
    hovertemplate="%{text}<extra></extra>",
)

fig.update_layout(
    height=420,
    margin=dict(l=10, r=10, t=10, b=10),
    coloraxis_colorbar=dict(title=f"{horizon_label} %"),
)

st.plotly_chart(fig, use_container_width=True)

st.dataframe(
    df.style.format({"Return_%": "{:.2f}%"}), 
    use_container_width=True,
    hide_index=True
)

tickers = ["SPY", "QQQ", "IWM", "TLT", "HYG", "GLD", "USO", "BTC-USD"]
ticker = st.selectbox("Select Ticker", tickers)

timeframes = {
    "1D": 1,
    "5D": 5,
    "1M": 30,
    "3M": 90,
    "YTD": 365
}
tf_label = st.selectbox("Select Timeframe", list(timeframes.keys()))

# --- Fetch Data ---
if tf_label == "1D":
    data = yf.download(ticker, period="1d", interval="5m")
elif tf_label == "5D":
    data = yf.download(ticker, period="5d", interval="30m")
elif tf_label == "1M":
    data = yf.download(ticker, period="1mo", interval="1d")
elif tf_label == "3M":
    data = yf.download(ticker, period="3mo", interval="1d")
elif tf_label == "YTD":
    data = yf.download(ticker, period="1y", interval="1d")

if isinstance(data.columns, pd.MultiIndex):
    data.columns = [" ".join([str(x) for x in col if x]).strip() for col in data.columns.values]

# Find the close column robustly
close_candidates = [c for c in data.columns if "Close" in str(c)]
if not close_candidates:
    st.error(f"No Close column found. Columns are: {list(data.columns)}")
    st.stop()

close_col = close_candidates[0]  # e.g., "Close" or "SPY Close"

# Coerce to numeric (handles object/string weirdness)
y = pd.to_numeric(data[close_col], errors="coerce")

if y.dropna().empty:
    st.error("Close series is all NaN after coercion. Data source returned non-numeric values.")
    st.stop()

df = data.copy()
dt_col = df.columns[0]  # first col is Datetime after reset_index()

if isinstance(df.columns, pd.MultiIndex):
    df.columns = [c[0] for c in df.columns]  # keep first level: Open/High/Low/Close/Volume

# Normalize column names (strip, consistent case)
df.columns = [str(c).strip() for c in df.columns]

def pick_col(target: str) -> str:
    # find column regardless of case (e.g., "high" vs "High")
    for c in df.columns:
        if str(c).lower() == target.lower():
            return c
    raise KeyError(f"Missing '{target}'. Columns: {list(df.columns)}")

suffix = f" {ticker}"
open_col  = f"Open{suffix}"
high_col  = f"High{suffix}"
low_col   = f"Low{suffix}"
close_col = f"Close{suffix}"
vol_col   = f"Volume{suffix}"

missing = [c for c in [open_col, high_col, low_col, close_col, vol_col] if c not in df.columns]
if missing:
    st.error(f"Missing columns: {missing}. Found: {list(df.columns)}")
    st.stop()

#Chart------
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])

fig.add_trace(go.Candlestick(
    x=df[dt_col],
    open=df[open_col],
    high=df[high_col],
    low=df[low_col],
    close=df[close_col],
    name=ticker
), row=1, col=1)

fig.add_trace(go.Bar(
    x=df[dt_col],
    y=df[vol_col],
    name="Volume"
), row=2, col=1)

fig.update_layout(
    template="plotly_dark",
    height=600,
    margin=dict(l=10, r=10, t=35, b=10),
    xaxis_rangeslider_visible=False,
    hovermode="x unified",
    showlegend=False
)

st.plotly_chart(fig, use_container_width=True)
