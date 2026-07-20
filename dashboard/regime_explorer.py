"""Regime time-series explorer dashboard.

Streamlit app for exploring the regime state history. Three panels:
1. Time series (composite + layers)
2. Historical context (current vs distribution)
3. Environment timeline and runs

Run locally:
    streamlit run dashboard/regime_explorer.py
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from plotly.subplots import make_subplots


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env", override=True)

from src.agent_system.regime.timeseries import load_regime_timeseries  # noqa: E402


st.set_page_config(
    page_title="Helix Regime Explorer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


LAYER_COLORS = {
    "monetary": "#7B68EE",
    "credit": "#FF8C42",
    "volatility": "#E74C3C",
    "breadth": "#27AE60",
    "positioning": "#3498DB",
}

ENVIRONMENT_COLORS = {
    # Bullish — greens (light to vivid)
    "Trend Day — Broad Participation": "#10B981",
    "Risk-On — Liquidity Driven": "#22C55E",
    "Risk-On Rotation Day": "#84CC16",
    "Risk-On Rotation — Vol Caution": "#BEF264",

    # Neutral — visually distinct slate vs lavender
    "Mixed / Neutral": "#64748B",
    "Chop / Layer Divergence": "#A78BFA",

    # Cautionary — amber, orange, cyan
    "Complacency Warning": "#F59E0B",
    "Negative Gamma — Volatile": "#F97316",
    "Fear Exhaustion — Mean Reversion Setup": "#06B6D4",

    # Risk-off — reds
    "Risk-Off / Headline Risk": "#EF4444",
    "Risk-Off — Credit Stress": "#B91C1C",
}


def _color_for_environment(env: str) -> str:
    return ENVIRONMENT_COLORS.get(env, "#94A3B8")


def _compute_runs(df: pd.DataFrame) -> list[dict]:
    """Compute contiguous environment runs from a regime time-series DataFrame."""

    if df.empty:
        return []

    env = df["environment"].fillna("")
    changed = env != env.shift()
    run_id = changed.cumsum()

    runs = []
    for _rid, group in df.groupby(run_id):
        environment = group["environment"].iloc[0]
        if not environment:
            continue
        comp_start = group["score_total"].iloc[0]
        comp_end = group["score_total"].iloc[-1]
        runs.append(
            {
                "start_date": group.index[0],
                "end_date": group.index[-1],
                "environment": environment,
                "n_days": len(group),
                "composite_start": (
                    float(comp_start) if pd.notna(comp_start) else None
                ),
                "composite_end": float(comp_end) if pd.notna(comp_end) else None,
            }
        )
    return runs


@st.cache_data(ttl=300)
def get_full_dataframe() -> pd.DataFrame:
    """Cached load of the full regime time series."""

    return load_regime_timeseries()


def render_sidebar(
    df: pd.DataFrame,
) -> tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    st.sidebar.title("Filters")

    if df.empty:
        st.sidebar.warning("No regime data available.")
        return None, None

    min_date = df.index.min().date()
    max_date = df.index.max().date()

    st.sidebar.markdown("**Date range**")
    preset = st.sidebar.radio(
        "Quick range",
        options=["30 days", "90 days", "1 year", "2 years", "All", "Custom"],
        index=2,
        label_visibility="collapsed",
    )

    if preset == "30 days":
        start = max(min_date, max_date - timedelta(days=30))
        end = max_date
    elif preset == "90 days":
        start = max(min_date, max_date - timedelta(days=90))
        end = max_date
    elif preset == "1 year":
        start = max(min_date, max_date - timedelta(days=365))
        end = max_date
    elif preset == "2 years":
        start = max(min_date, max_date - timedelta(days=730))
        end = max_date
    elif preset == "All":
        start = min_date
        end = max_date
    else:
        start = st.sidebar.date_input(
            "Start",
            value=max(min_date, max_date - timedelta(days=90)),
            min_value=min_date,
            max_value=max_date,
        )
        end = st.sidebar.date_input(
            "End",
            value=max_date,
            min_value=min_date,
            max_value=max_date,
        )

    st.sidebar.divider()
    return pd.Timestamp(start), pd.Timestamp(end)


def render_time_series(
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    st.subheader("Time series")

    df_window = df.loc[start:end].copy()
    if df_window.empty:
        st.info("No data in selected range.")
        return

    view_mode = st.radio(
        "View",
        options=[
            "Composite with environment bands",
            "All layers overlaid",
            "Layers as small multiples",
        ],
        horizontal=True,
        label_visibility="collapsed",
    )

    if view_mode == "Composite with environment bands":
        _render_composite_with_bands(df_window)
    elif view_mode == "All layers overlaid":
        _render_layers_overlaid(df_window)
    else:
        _render_layers_small_multiples(df_window)


def _render_composite_with_bands(df: pd.DataFrame) -> None:
    fig = go.Figure()

    for run in _compute_runs(df):
        fig.add_vrect(
            x0=run["start_date"],
            x1=run["end_date"] + pd.Timedelta(days=1),
            fillcolor=_color_for_environment(run["environment"]),
            opacity=0.35,
            layer="below",
            line_width=0,
        )

    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["score_total"],
            mode="lines",
            name="Composite",
            line=dict(color="#FFFFFF", width=2.8),
            hovertemplate=(
                "<b>%{x|%Y-%m-%d}</b><br>"
                "Composite: %{y:.1f}<br>"
                "Environment: %{customdata}<extra></extra>"
            ),
            customdata=df["environment"].fillna("-"),
        )
    )

    fig.add_hline(
        y=50,
        line=dict(color="#666666", width=1, dash="dash"),
        annotation_text="Neutral (50)",
        annotation_position="right",
    )
    fig.add_hline(
        y=70,
        line=dict(color="#22C55E", width=1, dash="dot"),
        annotation_text="Bullish (70)",
        annotation_position="right",
    )
    fig.add_hline(
        y=30,
        line=dict(color="#EF4444", width=1, dash="dot"),
        annotation_text="Bearish (30)",
        annotation_position="right",
    )

    fig.update_layout(
        template="plotly_dark",
        height=520,
        margin=dict(l=40, r=20, t=20, b=40),
        yaxis=dict(title="Composite Score", range=[0, 100]),
        xaxis=dict(title="Date"),
        showlegend=False,
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)

    envs_in_window = df["environment"].dropna().unique()
    if len(envs_in_window) > 0:
        chips_html = " ".join(
            f'<span style="background:{_color_for_environment(env)};'
            f"padding:4px 12px;border-radius:12px;color:white;"
            f"font-size:12px;margin-right:6px;opacity:0.85"
            f'">{env}</span>'
            for env in envs_in_window
        )
        st.markdown(chips_html, unsafe_allow_html=True)


def _render_layers_overlaid(df: pd.DataFrame) -> None:
    fig = go.Figure()

    for layer, color in LAYER_COLORS.items():
        col = f"layer_{layer}"
        if col not in df.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df[col],
                mode="lines",
                name=layer.capitalize(),
                line=dict(color=color, width=1.8),
                hovertemplate=(
                    f"<b>%{{x|%Y-%m-%d}}</b><br>"
                    f"{layer.capitalize()}: %{{y:.2f}}/10<extra></extra>"
                ),
            )
        )

    fig.add_hline(y=6.5, line=dict(color="#22C55E", width=1, dash="dot"))
    fig.add_hline(y=3.5, line=dict(color="#EF4444", width=1, dash="dot"))
    fig.add_hline(y=5.0, line=dict(color="#666666", width=1, dash="dash"))

    fig.update_layout(
        template="plotly_dark",
        height=520,
        margin=dict(l=40, r=20, t=20, b=40),
        yaxis=dict(title="Layer Score", range=[0, 10]),
        xaxis=dict(title="Date"),
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_layers_small_multiples(df: pd.DataFrame) -> None:
    layers = ["monetary", "credit", "volatility", "breadth", "positioning"]

    fig = make_subplots(
        rows=5,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=[layer.capitalize() for layer in layers],
    )

    for row, layer in enumerate(layers, 1):
        col = f"layer_{layer}"
        if col not in df.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df[col],
                mode="lines",
                line=dict(color=LAYER_COLORS[layer], width=1.6),
                showlegend=False,
                hovertemplate="%{x|%Y-%m-%d}: %{y:.2f}<extra></extra>",
            ),
            row=row,
            col=1,
        )
        fig.add_hline(
            y=5.0,
            line=dict(color="#444444", width=0.8, dash="dash"),
            row=row,
            col=1,
        )
        fig.update_yaxes(range=[0, 10], row=row, col=1)

    fig.update_layout(
        template="plotly_dark",
        height=720,
        margin=dict(l=40, r=20, t=40, b=40),
    )

    st.plotly_chart(fig, use_container_width=True)


def render_historical_context(
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    st.subheader("Current state in historical context")

    df_window = df.loc[start:end].copy()
    if df_window.empty or len(df_window) < 2:
        st.info("Not enough data in selected range.")
        return

    latest_row = df_window.iloc[-1]
    asof = df_window.index[-1].strftime("%Y-%m-%d")
    st.caption(
        f"Comparing latest reading ({asof}) against distribution over the "
        "selected range"
    )

    metrics_to_show = [
        ("score_total", "Composite"),
        ("layer_monetary", "Monetary"),
        ("layer_credit", "Credit"),
        ("layer_volatility", "Volatility"),
        ("layer_breadth", "Breadth"),
        ("layer_positioning", "Positioning"),
        ("vix_level", "VIX"),
        ("hy_spread_level", "HY Spread (bps)"),
    ]

    rows = []
    for col, label in metrics_to_show:
        if col not in df_window.columns:
            continue
        series = pd.to_numeric(df_window[col], errors="coerce").dropna()
        if series.empty:
            continue
        current = latest_row[col]
        if pd.isna(current):
            continue
        percentile = float((series <= current).mean() * 100)
        rows.append(
            {
                "Metric": label,
                "Current": round(float(current), 2),
                "Percentile": f"{percentile:.0f}",
                "Min": round(float(series.min()), 2),
                "Mean": round(float(series.mean()), 2),
                "Max": round(float(series.max()), 2),
                "Observations": int(len(series)),
            }
        )

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("**Distributions over selected range**")
    cols = st.columns(3)
    histogram_metrics = [
        ("score_total", "Composite"),
        ("vix_level", "VIX"),
        ("layer_credit", "Credit Layer"),
    ]

    for index, (col, label) in enumerate(histogram_metrics):
        if col not in df_window.columns:
            continue
        series = pd.to_numeric(df_window[col], errors="coerce").dropna()
        if series.empty:
            continue
        current = latest_row[col]

        with cols[index]:
            fig = go.Figure()
            fig.add_trace(
                go.Histogram(
                    x=series,
                    nbinsx=30,
                    marker=dict(color="#7B68EE", line=dict(width=0)),
                    opacity=0.75,
                    showlegend=False,
                )
            )
            if pd.notna(current):
                fig.add_vline(
                    x=float(current),
                    line=dict(color="#FFD700", width=2.5),
                    annotation_text=f"Now: {current:.1f}",
                    annotation_position="top",
                    annotation_yshift=10,
                )
            fig.update_layout(
                template="plotly_dark",
                height=260,
                margin=dict(l=10, r=10, t=40, b=30),
                xaxis_title=label,
                yaxis_title=None,
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)


def render_environment_panel(
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> None:
    st.subheader("Environment over time")

    df_window = df.loc[start:end].copy()
    if df_window.empty:
        st.info("No data in selected range.")
        return

    _render_environment_ribbon(df_window)
    _render_environment_frequency(df_window)
    _render_environment_runs_table(df_window)


def _render_environment_ribbon(df: pd.DataFrame) -> None:
    """Dense strip showing each day's environment as a colored cell."""

    if df.empty:
        return

    unique_envs = list(df["environment"].dropna().unique())
    env_to_id = {env: index for index, env in enumerate(unique_envs)}
    z_values = [[env_to_id.get(env, -1) for env in df["environment"].fillna("")]]

    n = len(unique_envs)
    if n == 0:
        return

    colorscale = []
    for index, env in enumerate(unique_envs):
        color = _color_for_environment(env)
        pos_low = index / n
        pos_high = (index + 1) / n
        colorscale.append([pos_low, color])
        colorscale.append([pos_high, color])

    hover_text = [
        [
            f"{date.strftime('%Y-%m-%d')}<br>{env}"
            for date, env in zip(df.index, df["environment"].fillna("—"))
        ]
    ]

    fig = go.Figure(
        data=go.Heatmap(
            z=z_values,
            x=df.index,
            y=["Environment"],
            colorscale=colorscale,
            showscale=False,
            hoverinfo="text",
            text=hover_text,
            zmin=0,
            zmax=n - 1 if n > 1 else 1,
            xgap=0,
            ygap=0,
        )
    )

    fig.update_layout(
        template="plotly_dark",
        height=110,
        margin=dict(l=40, r=20, t=10, b=30),
        yaxis=dict(
            showticklabels=False,
            fixedrange=True,
        ),
        xaxis=dict(
            title=None,
            type="date",
        ),
        showlegend=False,
    )

    st.markdown("**Daily environment ribbon**")
    st.plotly_chart(fig, use_container_width=True)


def _render_environment_frequency(df: pd.DataFrame) -> None:
    """Horizontal bar chart of total days per environment over the window."""

    if df.empty:
        return

    counts = df["environment"].value_counts()
    if counts.empty:
        return

    total_days = int(counts.sum())
    envs = counts.index.tolist()
    days = counts.values.tolist()
    percentages = [day_count / total_days * 100 for day_count in days]

    sorted_data = sorted(zip(envs, days, percentages), key=lambda item: item[1])
    envs_s = [env for env, _days, _pct in sorted_data]
    days_s = [day_count for _env, day_count, _pct in sorted_data]
    pcts_s = [pct for _env, _days, pct in sorted_data]

    bar_text = [f"{pct:.1f}%  ·  {day_count}d" for day_count, pct in zip(days_s, pcts_s)]
    colors = [_color_for_environment(env) for env in envs_s]

    fig = go.Figure(
        data=go.Bar(
            y=envs_s,
            x=pcts_s,
            text=bar_text,
            textposition="outside",
            orientation="h",
            marker=dict(color=colors),
            hovertemplate=(
                "<b>%{y}</b><br>%{x:.1f}% of period<br>"
                "%{customdata} days<extra></extra>"
            ),
            customdata=days_s,
        )
    )

    fig.update_layout(
        template="plotly_dark",
        height=max(220, 36 * len(envs_s) + 60),
        margin=dict(l=40, r=80, t=20, b=40),
        xaxis=dict(
            title="% of selected period",
            range=[0, max(pcts_s) * 1.18],
        ),
        yaxis=dict(title=None),
        showlegend=False,
        bargap=0.25,
    )

    st.markdown(f"**Frequency over selected period** ({total_days} trading days)")
    st.plotly_chart(fig, use_container_width=True)


def _render_environment_runs_table(df: pd.DataFrame) -> None:
    """Sortable table of all runs in the selected window."""

    runs = _compute_runs(df)
    if not runs:
        st.info("No environment runs in selected range.")
        return

    rows = []
    for run in runs:
        comp_change = None
        if run["composite_start"] is not None and run["composite_end"] is not None:
            comp_change = round(run["composite_end"] - run["composite_start"], 1)
        rows.append(
            {
                "Start": run["start_date"].strftime("%Y-%m-%d"),
                "End": run["end_date"].strftime("%Y-%m-%d"),
                "Days": run["n_days"],
                "Environment": run["environment"],
                "Composite start": (
                    round(run["composite_start"], 1)
                    if run["composite_start"] is not None
                    else None
                ),
                "Composite end": (
                    round(run["composite_end"], 1)
                    if run["composite_end"] is not None
                    else None
                ),
                "Change": comp_change,
            }
        )

    st.markdown("**Run detail**")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def main() -> None:
    st.title("Helix Regime Explorer")

    df = get_full_dataframe()

    if df.empty:
        st.warning(
            "No regime state data available. Run the backfill or daily cron first:\n\n"
            "```bash\npython -m scripts.backfill_regime_states\n```"
        )
        return

    start, end = render_sidebar(df)
    if start is None or end is None:
        return

    st.caption(
        f"Showing {start.date()} to {end.date()}  ·  "
        f"{len(df.loc[start:end])} of {len(df)} total regime states"
    )

    st.divider()
    render_time_series(df, start, end)

    st.divider()
    render_historical_context(df, start, end)

    st.divider()
    render_environment_panel(df, start, end)

    st.sidebar.divider()
    st.sidebar.caption(
        "Data refreshes every 5 minutes. To force reload, use the menu "
        "(top-right) -> Clear cache."
    )


if __name__ == "__main__":
    main()
