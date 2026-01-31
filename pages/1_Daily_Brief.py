import streamlit as st

from src.utils.dates import utc_now_iso
from src.brief.daily import build_daily_brief, DEFAULT_TICKERS
from src.brief.what_matters import generate_what_matters_today, heuristic_what_matters

st.set_page_config(page_title="Daily Brief", page_icon="🗞️", layout="wide")

st.title("🗞️ Daily Brief")
st.caption(f"Generated: {utc_now_iso()}")

with st.sidebar:
    st.subheader("Universe")
    tickers = st.text_area(
        "Tickers (comma-separated)",
        value=", ".join(DEFAULT_TICKERS),
    )
    tickers_list = [t.strip() for t in tickers.split(",") if t.strip()]

    st.subheader("Controls")
    gen_summary = st.checkbox("Generate 'What matters today' (uses API)", value=False)
    run = st.button("Run Daily Brief", type="primary")

if not run:
    st.info("Click **Run Daily Brief** in the sidebar.")
    st.stop()

with st.spinner("Building brief..."):
    result = build_daily_brief(tickers_list)

# ✅ Everything below is safe because result now exists

# What matters today (optional)
st.subheader("🧠 What matters today")
if gen_summary:
    try:
        movers_df = result["sections"].get("Market Moves (1D)")
        text = generate_what_matters_today(
            macro_signals=result["macro"],
            market_moves_df=movers_df,
            portfolio_flags=[],
            model="gpt-5-mini",
        )
        st.markdown(text)
    except Exception as e:
        st.warning(f"LLM summary unavailable ({e}). Showing heuristic summary.")
        st.markdown(
            heuristic_what_matters(
                result["macro"],
                movers_df,
                [],
            )
        )
else:
    st.caption("Enable the checkbox in the sidebar to generate the summary.")

st.divider()

# Macro panel
st.subheader("🧭 Macro Regime (V1)")
signals = result["macro"]
cols = st.columns(3)
for i, b in enumerate(["Growth", "Inflation", "Liquidity"]):
    sig = signals[b]
    with cols[i]:
        st.metric(
            label=b,
            value=f"{sig.trend}",
            delta=f"MoM: {sig.mom:+.2f} | YoY: {sig.yoy:+.2f}",
        )
        st.caption(sig.name)

st.caption("Interpretation: Liquidity uses NFCI (higher = tighter).")

st.divider()

# Sections
for title, df in result["sections"].items():
    st.subheader(title)
    if df is None or df.empty:
        st.warning("No data returned.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
