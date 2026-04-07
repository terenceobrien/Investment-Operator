from __future__ import annotations

import streamlit as st


def apply_base_style() -> None:
    """
    Minimal global CSS for consistent spacing and numeric readability.
    """
    st.markdown(
        """
        <style>
            .block-container {
                padding-top: 2rem;
                padding-bottom: 2.5rem;
            }
            h1, h2, h3 {
                letter-spacing: 0.2px;
            }
            div[data-testid="stMetricValue"],
            div[data-testid="stMetricDelta"],
            div[data-testid="stDataFrame"] {
                font-variant-numeric: tabular-nums;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
