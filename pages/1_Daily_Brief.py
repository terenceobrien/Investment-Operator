import streamlit as st
from datetime import date

from src.utils.dates import utc_now_iso
from src.utils.format import fmt_number, format_df_accounting
from src.utils.style import apply_base_style
from src.brief.daily import build_daily_brief, DEFAULT_TICKERS, INDICATOR_MAP
from src.brief.macro_snapshot import assemble_snapshot_data, render_snapshot
from src.data.releases import fetch_release_calendar
from src.brief.what_matters import generate_what_matters_today, heuristic_what_matters

st.set_page_config(page_title="Daily Brief", page_icon="🗞️", layout="wide")

apply_base_style()

st.title("Macro Brief")
st.caption(f"Generated: {utc_now_iso()}")

with st.sidebar:
    st.subheader("Universe")
    tickers = st.text_area(
        "Tickers (comma-separated)",
        value=", ".join(DEFAULT_TICKERS),
    )
    tickers_list = [t.strip() for t in tickers.split(",") if t.strip()]

    # Optional: keep a manual "refresh" if you want
    refresh = st.button("Refresh", type="primary")


# --- Cache the brief so you don't refetch market data on every rerun ---
@st.cache_data(ttl=900)  # 15 min
def cached_brief(tickers_key: str):
    return build_daily_brief(tickers_key.split(","))


tickers_key = ",".join(tickers_list)

# Force cache bust on refresh
if refresh:
    cached_brief.clear()

with st.spinner("Building brief..."):
    result = cached_brief(tickers_key)

# --- Macro snapshot region ---------------------------------------------------
@st.cache_data(ttl=1800)
def cached_snapshot():
    # fetch the full list of indicator series once per half-hour
    return assemble_snapshot_data()

snapshot_data = cached_snapshot()
render_snapshot(snapshot_data, default_years=1)


# --- Cache the LLM summary so it runs once/day per ticker universe ---
@st.cache_data(ttl=86400)  # 24 hours
def cached_what_matters(run_date: str, tickers_key: str, macro_sig_key: str, movers_csv: str):
    """
    Cache key includes date + tickers universe + a light macro signature + movers snapshot.
    This prevents repeated API calls on Streamlit reruns.
    """
    # We will re-create minimal objects inside to avoid caching issues with complex types
    movers_df = None
    if movers_csv:
        movers_df = st.session_state.get("_movers_df_for_summary")  # fallback if needed

    # Note: We pass movers_df directly in the caller; this func only exists for cache keying.
    return "OK"


st.subheader("What matters today")

movers_df = result["sections"].get("Market Moves (1D)")

# Create a small signature so summary updates when macro materially changes
macro_sig_key = "|".join(
    [f"{k}:{result['macro'][k].latest:.3f}:{result['macro'][k].trend}" for k in ["Growth", "Inflation", "Liquidity"]]
)

# Movers snapshot for cache key (small + stable)
movers_csv = ""
if movers_df is not None and not movers_df.empty:
    # keep it small; top rows only
    movers_csv = movers_df.head(30).to_csv(index=False)

# Store movers_df in session state so we can retrieve if needed
st.session_state["_movers_df_for_summary"] = movers_df

# Use date + tickers + macro signature + movers snapshot as the cache key.
# The cached_what_matters function itself returns dummy "OK" but enables stable caching keys;
# we use st.cache_data on the actual generation below via the same key pattern.
summary_cache_key = (date.today().isoformat(), tickers_key, macro_sig_key, movers_csv)


@st.cache_data(ttl=86400)
def generate_summary_cached(run_date: str, tickers_key: str, macro_sig_key: str, movers_csv: str):
    # Rebuild movers_df from CSV to keep caching deterministic
    local_movers = None
    if movers_csv:
        from io import StringIO
        import pandas as pd

        local_movers = pd.read_csv(StringIO(movers_csv))

    try:
        return generate_what_matters_today(
            macro_signals=result["macro"],
            market_moves_df=local_movers,
            portfolio_flags=[],
            model="gpt-4o-mini",
        )
    except Exception as e:
        # Bubble up error so caller can fallback
        raise e


try:
    with st.spinner("Generating summary..."):
        text = generate_summary_cached(*summary_cache_key)
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

st.divider()

# Macro panel
st.subheader("Macro Regime (V2)")
signals = result["macro"]
cols = st.columns(3)
for i, b in enumerate(["Growth", "Inflation", "Liquidity"]):
    sig = signals[b]
    with cols[i]:
        # Label delta depending on frequency (monthly vs weekly)
        delta_label = "MoM" if len(sig.history_12m) <= 12 else "WoW"
        yoy_label = "12m" if len(sig.history_12m) <= 12 else "52w"

        st.metric(
            label=b,
            value=f"{sig.trend} ({fmt_number(sig.latest, 2)}σ)",
            delta=f"{delta_label}: {fmt_number(sig.mom, 2)} | {yoy_label}: {fmt_number(sig.yoy, 2)}",
        )
        st.caption(sig.name)
        st.line_chart(sig.history_12m)

    with st.expander(f"{b} components"):
        st.json(sig.components)

st.divider()

# Sections
for title, df in result["sections"].items():
    st.subheader(title)
    if df is None or df.empty:
        st.warning("No data returned.")
    else:
        if title == "Market Moves (1D)":
            styled = format_df_accounting(
                df,
                pct_cols=["chg_pct_1d"],
                num_cols=["last"],
                pct_decimals=2,
                num_decimals=2,
            )
            st.dataframe(styled, width='stretch', hide_index=True)
        elif title in ("Today’s Economic Releases", "Liquidity Updates"):
            styled = format_df_accounting(
                df,
                num_cols=["latest", "previous", "change"],
                num_decimals=2,
            )
            st.dataframe(styled, width='stretch', hide_index=True)
        else:
            st.dataframe(df, width='stretch', hide_index=True)

with st.expander("Economic Calendar (next 7 days)"):
    cal = fetch_release_calendar(INDICATOR_MAP, days_ahead=7)
    st.dataframe(cal, width='stretch', hide_index=True)
