import streamlit as st
import pandas as pd
from pathlib import Path

from src.utils.dates import utc_now_iso
from src.data.portfolio import load_portfolio_csv
from src.brief.portfolio import compute_portfolio_snapshot
from src.data.macro import fetch_regime_signals
from src.brief.portfolio import add_regime_aware_flags

st.set_page_config(page_title="Portfolio Snapshot", page_icon="🧩", layout="wide")

st.title("Portfolio Snapshot (V1)")
st.caption(f"Generated: {utc_now_iso()}")

st.markdown(
    """
This page loads your **default portfolio file** from:
- `data/portfolio.csv`

You can also upload a different CSV to override it.
CSV columns:
- **ticker**
- **weight** (decimals summing to 1.0 or percents)
- **theme** (optional)
"""
)

# Optional override upload
uploaded = st.file_uploader("Override with an uploaded portfolio CSV (optional)", type=["csv"])

DEFAULT_PATH = Path("data/portfolio.csv")

df = None

if uploaded is not None:
    df = load_portfolio_csv(uploaded)
    st.success("Loaded uploaded portfolio CSV.")
else:
    if DEFAULT_PATH.exists():
        # Read from disk and reuse the same cleaning function
        with DEFAULT_PATH.open("rb") as f:
            df = load_portfolio_csv(f)
        st.info(f"Loaded default portfolio: {DEFAULT_PATH}")
    else:
        st.error(f"Default portfolio file not found: {DEFAULT_PATH}")
        st.stop()

# Compute snapshot
with st.spinner("Computing snapshot..."):
    snap = compute_portfolio_snapshot(df)

    # Fetch macro regime (optional; won't break page if unavailable)
macro = None
macro_error = None
try:
    macro = fetch_regime_signals()
except Exception as e:
    macro_error = str(e)

# Combine flags with regime-aware flags
snap["flags"] = add_regime_aware_flags(
    base_flags=snap["flags"],
    macro_signals=macro,
    summary=snap["summary"],
    theme_exposure=snap["theme_exposure"],
    top_positions=snap["top_positions"],
)

st.subheader("🧭 Macro Regime")
if macro is None:
    st.warning(f"Macro regime unavailable: {macro_error}" if macro_error else "Macro regime unavailable.")
else:
    cols = st.columns(3)
    for idx, key in enumerate(["Growth", "Inflation", "Liquidity"]):
        sig = macro[key]
        with cols[idx]:
            st.metric(
                label=key,
                value=sig.trend,
                delta=f"MoM: {sig.mom:+.2f} | YoY: {sig.yoy:+.2f}",
            )
            st.caption(sig.name)
    st.caption("Liquidity uses NFCI (higher = tighter).")

summary = snap["summary"]

# Summary metrics
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Positions (ex-cash)", summary["n_positions"])
c2.metric("Cash", f"{summary['cash_weight']:.1%}")
c3.metric("Top 1 (invested)", f"{summary['top1_invested']:.1%}")
c4.metric("Top 3 (invested)", f"{summary['top3_invested']:.1%}")
c5.metric("Top 5 (invested)", f"{summary['top5_invested']:.1%}")

st.divider()

# Flags
st.subheader("⚠️ Flags")
flags = snap["flags"]
if not flags:
    st.success("No major concentration flags triggered (V1 thresholds).")
else:
    for f in flags:
        st.warning(f)

st.divider()

# Top positions
st.subheader("📌 Top Positions")
tp = snap["top_positions"].copy()
tp["weight"] = tp["weight"].map(lambda x: f"{x:.2%}")
tp["w_norm"] = tp["w_norm"].map(lambda x: f"{x:.1%}")
tp = tp.rename(columns={"w_norm": "share_of_invested"})
st.dataframe(tp, use_container_width=True, hide_index=True)

# Theme exposure
st.subheader("🏷️ Theme Exposure")
te = snap["theme_exposure"].copy()
te["weight"] = te["weight"].map(lambda x: f"{x:.2%}")
st.dataframe(te, use_container_width=True, hide_index=True)
