import streamlit as st
from io import BytesIO

from src.brief.memo import MemoInputs, render_memo_markdown
from src.data.macro import fetch_regime_signals
from src.utils.style import apply_base_style

st.set_page_config(page_title="Memo Generator", page_icon="📝", layout="wide")
apply_base_style()
st.title("Memo Generator (V1)")
st.caption("Draft a structured trade memo with optional macro context.")

# Optional macro context toggle
include_macro = st.checkbox("Include current macro regime context", value=True)

macro_regime = None
if include_macro:
    try:
        sig = fetch_regime_signals()
        macro_regime = {k: sig[k].trend for k in ["Growth", "Inflation", "Liquidity"]}
    except Exception as e:
        st.warning(f"Macro regime unavailable: {e}")

with st.form("memo_form"):
    c1, c2, c3 = st.columns(3)
    title = c1.text_input("Memo title", value="Trade memo")
    ticker = c2.text_input("Ticker", value="SPY")
    direction = c3.selectbox("Direction", ["Long", "Short"])

    c4, c5, c6 = st.columns(3)
    horizon = c4.text_input("Horizon", value="2–6 weeks")
    conviction = c5.selectbox("Conviction", ["Low", "Medium", "High"])
    position_size = c6.text_input("Position size", value="(e.g., 2% NAV)")

    thesis = st.text_area("Thesis (1–3 paragraphs)", height=120)

    key_drivers = st.text_area("Key drivers (one per line)", height=100)
    catalysts = st.text_area("Catalysts / events (one per line)", height=90)
    risks = st.text_area("Risks (one per line)", height=100)
    invalidation = st.text_area("Invalidation (one per line)", height=90)

    entry_plan = st.text_area("Entry plan", height=90)
    exit_plan = st.text_area("Exit plan", height=90)
    notes = st.text_area("Notes", height=90)

    submitted = st.form_submit_button("Generate memo", type="primary")

if not submitted:
    st.info("Fill the form and click **Generate memo**.")
    st.stop()

m = MemoInputs(
    title=title.strip() or "Trade memo",
    ticker=ticker.strip().upper(),
    direction=direction,
    horizon=horizon.strip(),
    conviction=conviction,
    position_size=position_size.strip(),
    thesis=thesis,
    key_drivers=key_drivers.splitlines(),
    risks=risks.splitlines(),
    invalidation=invalidation.splitlines(),
    catalysts=catalysts.splitlines(),
    entry_plan=entry_plan,
    exit_plan=exit_plan,
    notes=notes,
)

md = render_memo_markdown(m, macro_regime=macro_regime)

st.subheader("Preview")
st.markdown(md)

# Download button
st.subheader("Download")
b = md.encode("utf-8")
st.download_button(
    label="Download memo (.md)",
    data=b,
    file_name=f"{m.ticker}_memo.md",
    mime="text/markdown",
)
