import streamlit as st
import pandas as pd

from src.narrative.bundle import build_narrative_bundle, top_n_by_channel
from src.narrative.synth import synthesize_narrative_state

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

st.set_page_config(page_title="Narrative State", layout="wide")
st.title("Narrative State — News & Earnings")

# Controls
c1, c2, c3 = st.columns(3)
with c1:
    news_category = st.selectbox("News category", ["general", "forex", "crypto", "merger"], index=0)
with c2:
    earnings_days = st.slider("Earnings lookahead (days)", 1, 14, 7)
with c3:
    ticker_csv = st.text_input("Watch tickers (comma-separated)", "SPY,QQQ,IWM,AAPL,MSFT,NVDA,TSLA,GOOGL,AMZN,META")

watch = [x.strip().upper() for x in ticker_csv.split(",") if x.strip()]

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

st.subheader("LLM Synthesis")

run = st.button("Synthesize narrative", type="primary")

@st.cache_data(ttl=900)
def _cached_synth(bundle_for_llm: dict):
    return synthesize_narrative_state(bundle_for_llm, market_state_summary={}, max_items=60, model="gpt-4o-mini")

if run:
    # Build a small bundle to feed the LLM (top 20 per channel)
    bundle_for_llm = {"asof_utc": bundle["asof_utc"], "items": items_top}

    with st.spinner("Synthesizing…"):
        out = _cached_synth(bundle_for_llm)

    st.success("Synthesis complete")

    st.markdown("### One-paragraph summary")
    st.write(out["one_paragraph_summary"])

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
