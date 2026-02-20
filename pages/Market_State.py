import streamlit as st
import pandas as pd
import numpy as np

from src.state.market_state import (
    build_market_state,
    save_snapshot,
    load_snapshot,
    SECTOR_ETFS,
    CROSS_ASSET,
    HORIZONS,
)
from src.state.scoring import score_market_state

from datetime import datetime
from src.state.delta import find_previous_snapshot, diff_states, diff_to_bullets, top_movers_from_delta

def render_card(title: str, value: str):
    st.markdown(
        f"""
        <div style="
            padding: 16px;
            border-radius: 12px;
            background-color: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            height: 120px;
        ">
            <div style="
                font-size: 18px;
                color: rgba(255,255,255,0.6);
                margin-bottom: 8px;
            ">
                {title}
            </div>
            <div style="
                font-size: 16px;
                font-weight: 600;
                line-height: 1.2;
                word-wrap: break-word;
            ">
                {value}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.set_page_config(page_title="Market State", layout="wide")
st.title("Market State — Sentiment & Environment")

# Controls
colA, colB, colC, colD = st.columns([1.2, 1.2, 1.2, 2.4])

with colA:
    horizon = st.selectbox("Horizon", list(HORIZONS.keys()), index=0)
with colB:
    auto_adjust = st.toggle("Use Adjusted Close", value=True)
with colC:
    persist = st.toggle("Save snapshot (JSON)", value=True)
with colD:
    snapshot_dir = st.text_input("Snapshot directory", value="data/snapshots")

# Build
with st.spinner("Fetching market data and computing state..."):
    state = build_market_state(horizon=horizon, auto_adjust=auto_adjust)
    state = score_market_state(state)

# Top tiles
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    render_card(
        "Sentiment Score (0–100)",
        f"{state.score_total:.2f}" if state.score_total is not None else "—"
    )

with c2:
    render_card(
        "Environment",
        state.environment or "—"
    )

with c3:
    lead_txt = " | ".join(
        [f"{name} ({ret:+.2f}%)" for name, ret in state.leadership_top3]
    ) if state.leadership_top3 else "—"
    render_card("Leadership (Top 3)", lead_txt)

with c4:
    render_card(
        "Sector Dispersion (σ)",
        f"{state.dispersion:.2f}" if state.dispersion is not None else "—"
    )
with c5:
    render_card(
        "Confidence",
        f"{state.confidence:.0f}" if state.confidence is not None else "-"
    )

st.divider()

# Component score bars
st.subheader("Score Components (0–20 each)")
if state.score_components:
    comp_df = pd.DataFrame(
        [{"Component": k, "Score": v} for k, v in state.score_components.items()]
    ).sort_values("Score", ascending=False)
    st.dataframe(comp_df, use_container_width=True, hide_index=True)
else:
    st.info("No score components available.")

# Tape metrics
st.subheader("Technical State")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "SPY CLV",
        f"{state.spy_clv:+.2f}" if state.spy_clv is not None else "—"
    )

with col2:
    st.metric(
        "SPY Range %",
        f"{state.spy_range_pct:.2f}%" if state.spy_range_pct is not None else "—"
    )

with col3:
    st.metric(
        "SPY Vol vs 20D",
        f"{state.spy_vol_vs_20d_pct:+.1f}%" if state.spy_vol_vs_20d_pct is not None else "—"
    )

with col4:
    st.metric(
        "Volume Confirmation",
        f"{state.volume_confirmation:+.2f}" if state.volume_confirmation is not None else "—"
    )

st.divider()

st.subheader("Technical State")

t1, t2, t3, t4 = st.columns(4)

# Format position labels
vwap_flag = (
    "Above VWAP" if state.spy_above_vwap is True
    else "Below VWAP" if state.spy_above_vwap is False
    else "—"
)

prev_close_flag = (
    "Above Prev Close" if state.spy_above_prev_close is True
    else "Below Prev Close" if state.spy_above_prev_close is False
    else "—"
)

with t1:
    render_card(
        "SPY Last",
        f"{state.spy_last_price:.2f}" if state.spy_last_price is not None else "—"
    )

with t2:
    render_card(
        "SPY VWAP",
        f"{state.spy_vwap:.2f}" if state.spy_vwap is not None else "—"
    )

with t3:
    render_card("VWAP Position", vwap_flag)

with t4:
    render_card("Prev Close Position", prev_close_flag)

st.divider()
        
st.subheader("What changed vs previous snapshot")

session_date = state.market_session_date or datetime.now().strftime("%Y-%m-%d")
if persist:
    _ = save_snapshot(state, base_dir=snapshot_dir, date_str=session_date)

prev_date_str, prev_state = find_previous_snapshot(
    snapshot_dir,
    today_date_str=session_date,
    max_lookback_business_days=10,
)

if prev_state is None:
    st.info("No prior snapshot found in the last ~10 business days. Once you have at least 2 snapshots, deltas will show here.")
else:
    d = diff_states(state, prev_state)

    st.caption(f"Comparing **{session_date}** vs **{prev_date_str}**")

    # Bullets
    bullets = diff_to_bullets(d)
    for b in bullets:
        st.markdown(f"- {b}")

    # Small “key deltas” table (score components)
    comp_delta = d.get("components_delta", {})
    if comp_delta:
        comp_df = (
            pd.DataFrame([{"Component": k, "Δ (0–20)": v} for k, v in comp_delta.items()])
            .sort_values("Δ (0–20)", ascending=False)
            .reset_index(drop=True)
        )
        st.subheader("Component deltas")
        st.dataframe(
            comp_df.style.format({"Δ (0–20)": "{:+.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

    ca_delta = d.get("cross_asset_delta", {})
    sec_delta = d.get("sector_delta", {})

    ca_pos, ca_neg = top_movers_from_delta(ca_delta, n=3)
    sec_pos, sec_neg = top_movers_from_delta(sec_delta, n=3)

    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Cross-asset delta movers")
        rows = []
        for k, v in ca_pos:
            rows.append({"Asset": k, "Δ return (pp)": v})
        for k, v in ca_neg:
            rows.append({"Asset": k, "Δ return (pp)": v})
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df.style.format({"Δ return (pp)": "{:+.2f}"}), use_container_width=True, hide_index=True)
        else:
            st.caption("No cross-asset deltas available.")

    with c2:
        st.subheader("Sector delta movers")
        rows = []
        for k, v in sec_pos:
            rows.append({"Sector ETF": k, "Δ return (pp)": v})
        for k, v in sec_neg:
            rows.append({"Sector ETF": k, "Δ return (pp)": v})
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df.style.format({"Δ return (pp)": "{:+.2f}"}), use_container_width=True, hide_index=True)
        else:
            st.caption("No sector deltas available.") 

# Cross-asset table
st.subheader("Cross-Asset Returns")
ca_rows = []
for t, name in CROSS_ASSET.items():
    r = state.cross_asset_returns.get(t)
    ca_rows.append({"Ticker": t, "Name": name, f"Return {horizon} (%)": r})
ca_df = pd.DataFrame(ca_rows).sort_values(f"Return {horizon} (%)", ascending=False)
st.dataframe(
    ca_df.style.format({f"Return {horizon} (%)": "{:+.2f}"}),
    use_container_width=True,
    hide_index=True,
)

# Sector table
st.subheader("Sector Returns (SPDRs)")
sec_rows = []
for t, name in SECTOR_ETFS.items():
    r = state.sector_returns.get(t)
    sec_rows.append({"Ticker": t, "Sector": name, f"Return {horizon} (%)": r})
sec_df = pd.DataFrame(sec_rows).sort_values(f"Return {horizon} (%)", ascending=False)
st.dataframe(
    sec_df.style.format({f"Return {horizon} (%)": "{:+.2f}"}),
    use_container_width=True,
    hide_index=True,
)

# Snapshot persistence
st.divider()
st.subheader("Snapshot")
if persist:
    path = save_snapshot(state, base_dir=snapshot_dir)
    st.success(f"Saved snapshot: {path}")
else:
    st.caption("Snapshot saving is off.")

st.caption(f"Asof (UTC): {state.asof_utc}")
