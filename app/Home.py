import streamlit as st

st.set_page_config(
    page_title="AI Financial Operator – V1",
    page_icon="📈",
    layout="wide",
)

st.title("📈 AI Financial Operator – V1")
st.caption("Human-in-the-loop daily brief + portfolio snapshot + memo generator.")

st.markdown(
    """
### What this app will do (V1)
- **Daily Brief:** market moves + macro changes + watchlist news (with sources)
- **Portfolio Snapshot:** exposures & concentration (manual CSV input for now)
- **Memo Generator:** 1-page thesis memo from your notes + links
"""
)

st.info("Go to **Daily Brief** in the left sidebar to start.")

