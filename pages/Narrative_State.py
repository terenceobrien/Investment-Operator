import streamlit as st
import pandas as pd

from src.narrative.bundle import build_narrative_bundle, top_n_by_channel
from src.narrative.synth import (
    synthesize_narrative_state,
    load_latest_narrative_snapshot,
    save_narrative_snapshot,
)
from src.data.market import fetch_market_moves
from src.state.market_state import build_market_state, summarize_state
from src.state.scoring import score_market_state
from src.utils.style import apply_base_style

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

st.set_page_config(page_title="Narrative State", layout="wide")
apply_base_style()
st.title("Narrative State — News & Earnings")
st.caption("News and earnings synthesis with raw inputs for auditability.")

# Controls
c1, c2, c3, c4 = st.columns(4)
with c1:
    news_category = st.selectbox("News category", ["general", "forex", "crypto", "merger"], index=0)
with c2:
    earnings_days = st.slider("Earnings lookahead (days)", 1, 14, 7)
with c3:
    ticker_csv = st.text_input("Watch tickers (comma-separated)", "SPY,QQQ,IWM,AAPL,MSFT,NVDA,TSLA,GOOGL,AMZN,META")
with c4:
    lookback_hours = st.slider("Narrative delta lookback (hours)", 12, 72, 36, step=6)

watch = [x.strip().upper() for x in ticker_csv.split(",") if x.strip()]
model_name = "gpt-4o-mini"

# Cache the ingestion (avoid hammering API on every rerun)
@st.cache_data(ttl=900)  # 15 minutes
def _get_bundle(category: str, days: int, tickers: tuple):
    return build_narrative_bundle(
        watch_tickers=list(tickers),
        news_category=category,
        news_limit=80,
        ticker_news_limit=20,
        earnings_days_ahead=days,
    ).to_dict()

bundle = _get_bundle(news_category, earnings_days, tuple(watch))
items_all = bundle["items"]

bucketed = top_n_by_channel(items_all, n=20)
items_top = bucketed["news"] + bucketed["ticker_news"] + bucketed["earnings"]

st.caption(f"As-of (UTC): {bundle['asof_utc']} • Total items: {len(items_all)} • Showing top 20 per channel ({len(items_top)} items)")

@st.cache_data(ttl=600)
def _market_state_summary() -> dict:
    try:
        state = build_market_state(horizon="1D", auto_adjust=True)
        state = score_market_state(state)
        return summarize_state(state)
    except Exception:
        return {}


@st.cache_data(ttl=300)
def _market_moves_for_watch(tickers: tuple[str, ...]) -> list[dict]:
    if not tickers:
        return []
    df = fetch_market_moves(list(tickers))
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")


asof_date = bundle["asof_utc"][:10]
snapshot_dir = "data/snapshots"
prior_date, prior_state = load_latest_narrative_snapshot(
    base_dir=snapshot_dir,
    today_date_str=asof_date,
    max_lookback_days=14,
)

if prior_state is not None:
    st.caption(f"Prior narrative snapshot loaded: {prior_date}")
else:
    st.caption("No prior narrative snapshot found in the last 14 days.")

st.subheader("LLM Synthesis")

run = st.button("Synthesize narrative", type="primary")

@st.cache_data(ttl=900)
def _cached_synth(
    bundle_for_llm: dict,
    market_state_summary: dict,
    market_moves: list[dict],
    prior_state: dict | None,
    lookback_hours: int,
):
    return synthesize_narrative_state(
        bundle_for_llm,
        market_state_summary=market_state_summary,
        market_moves=market_moves,
        prior_state=prior_state,
        max_items=80,
        lookback_hours=lookback_hours,
        model=model_name,
    )

if run:
    market_state_summary = _market_state_summary()
    market_moves = _market_moves_for_watch(tuple(watch))
    bundle_for_llm = {
        "asof_utc": bundle["asof_utc"],
        "items": items_all,
        "watch_tickers": watch,
    }

    with st.spinner("Synthesizing…"):
        out = _cached_synth(
            bundle_for_llm,
            market_state_summary,
            market_moves,
            prior_state,
            lookback_hours,
        )

    st.success("Synthesis complete")
    meta = out.get("_meta", {})
    st.caption(
        f"LLM input coverage: {meta.get('items_selected_for_llm', '—')} selected "
        f"from {meta.get('total_items_in_bundle', '—')} total • "
        f"lookback={meta.get('lookback_hours', '—')}h"
    )

    st.markdown("### One-paragraph summary")
    st.write(out["one_paragraph_summary"])

    if out.get("raw_takeaways"):
        st.markdown("### What Changed Today")
        for x in out["raw_takeaways"]:
            st.markdown(f"- {x}")

    st.markdown("### Dominant narratives")
    for i, n in enumerate(out["dominant_narratives"], start=1):
        st.markdown(f"#### {i}. {n['title']}")
        st.caption(f"Stance: {n['stance']} • Confidence: {n['confidence']}/100")
        st.write(n["why_now"])

        cols = st.columns(2)
        with cols[0]:
            st.markdown("**Key catalysts**")
            for c in n["key_catalysts"]:
                st.markdown(f"- {c}")
        with cols[1]:
            st.markdown("**What would change this**")
            for w in n["what_would_change"]:
                st.markdown(f"- {w}")

        with st.expander("Evidence"):
            for e in n["evidence"]:
                # URL can be None; keep it clean
                if e["url"]:
                    st.markdown(f"- **{e['source']}** ({e['channel']}): {e['title']} — {e['url']}")
                else:
                    st.markdown(f"- **{e['source']}** ({e['channel']}): {e['title']}")

    with st.expander("Tone + Signals"):
        st.json({"market_tone": out["market_tone"], "signals": out["signals"]})

    if out.get("counter_narratives"):
        with st.expander("Counter Narratives"):
            for x in out["counter_narratives"]:
                st.markdown(f"- {x}")

    if out.get("unknowns"):
        with st.expander("Unknowns / Watchpoints"):
            for x in out["unknowns"]:
                st.markdown(f"- {x}")

    save_path = save_narrative_snapshot(out, base_dir=snapshot_dir, date_str=asof_date)
    st.caption(f"Saved narrative snapshot: {save_path}")

st.divider()

# -----------------------------
# 2) Raw items AFTER synthesis
# -----------------------------
st.subheader("Raw Inputs (Top 20 per channel)")

def _items_to_df(items: list[dict]):
    return pd.DataFrame([{
        "channel": x.get("channel"),
        "source": x.get("source"),
        "title": x.get("title"),
        "tickers": ", ".join(x.get("tickers") or []),
        "timestamp_utc": x.get("timestamp_utc"),
        "url": x.get("url"),
    } for x in items])

tab1, tab2, tab3 = st.tabs(["News", "Ticker News", "Earnings"])

with tab1:
    st.dataframe(_items_to_df(bucketed["news"]), use_container_width=True, hide_index=True)

with tab2:
    st.dataframe(_items_to_df(bucketed["ticker_news"]), use_container_width=True, hide_index=True)

with tab3:
    st.dataframe(_items_to_df(bucketed["earnings"]), use_container_width=True, hide_index=True)
