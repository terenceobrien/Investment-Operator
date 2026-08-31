"""Streamlit research app for Helix-aware SPY put-spread backtests.

Run locally:
    streamlit run backend/research/options_backtest_app.py
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.research.options_backtest import (  # noqa: E402
    BacktestConfig,
    DEFAULT_JOINED_DATASET,
    compare_strategies,
    combined_equity,
    combined_trades,
    get_trade_details,
    load_joined_dataset,
    metrics_frame,
    normalize_options_data,
    regime_entry_summary,
    run_parameter_grid,
    validate_options_data,
)


st.set_page_config(
    page_title="Helix Options Strategy Lab",
    layout="wide",
    initial_sidebar_state="expanded",
)


STRATEGY_ORDER = [
    "Strategy A - Always Sell",
    "Strategy B - Benign Entries Only",
    "Strategy C - Benign + Trigger Exit",
]


def _fmt_money(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"${float(value):,.0f}"


def _fmt_price(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"${float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100.0:,.1f}%"


def _fmt_num(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):,.2f}"


def _compact_date(value: Any) -> str:
    if pd.isna(value):
        return "n/a"
    return str(value)


def _config_payload(config: BacktestConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload["max_concurrent_positions"] = int(payload["max_concurrent_positions"])
    return payload


@st.cache_data(show_spinner=False)
def _load_research_data(path_string: str):
    raw = load_joined_dataset(path_string)
    data = normalize_options_data(raw)
    return data, validate_options_data(data)


@st.cache_data(show_spinner=False)
def _run_comparison(path_string: str, config_payload: dict[str, Any]):
    data, _coverage = _load_research_data(path_string)
    config = BacktestConfig(**config_payload)
    results = compare_strategies(data, config)
    return (
        results,
        metrics_frame(results),
        combined_trades(results),
        combined_equity(results),
    )


@st.cache_data(show_spinner=False)
def _run_grid(path_string: str, config_payload: dict[str, Any]) -> pd.DataFrame:
    data, _coverage = _load_research_data(path_string)
    return run_parameter_grid(data, BacktestConfig(**config_payload))


def _render_sidebar() -> tuple[str, dict[str, Any]]:
    st.sidebar.title("Backtest Controls")

    dataset_path = st.sidebar.text_input(
        "Joined dataset",
        value=str(DEFAULT_JOINED_DATASET),
        help="Historical SPY options rows joined to Helix hedge-trigger state.",
    )

    starting_nav = st.sidebar.number_input(
        "Starting NAV",
        min_value=10_000.0,
        max_value=10_000_000.0,
        value=100_000.0,
        step=10_000.0,
        format="%.0f",
    )

    target_dte = st.sidebar.slider("Target entry DTE", 21, 90, 45, 1)
    dte_tolerance = st.sidebar.slider("DTE tolerance (+/- calendar days)", 0, 15, 5, 1)
    short_otm_pct = st.sidebar.slider("Short put OTM %", 2.5, 15.0, 7.5, 0.5) / 100.0

    spread_mode_label = st.sidebar.radio(
        "Spread width mode",
        ["% of SPY", "Fixed dollars"],
        index=1,
        horizontal=True,
    )
    if spread_mode_label == "% of SPY":
        spread_width_pct = st.sidebar.slider("Spread width % of SPY", 1.0, 10.0, 5.0, 0.5) / 100.0
        spread_width_dollars = 25.0
        spread_width_mode = "pct_spy"
    else:
        spread_width_pct = 0.05
        spread_width_dollars = st.sidebar.number_input(
            "Spread width dollars",
            min_value=1.0,
            max_value=100.0,
            value=5.0,
            step=1.0,
        )
        spread_width_mode = "fixed_dollars"

    profit_target_pct = st.sidebar.slider("Profit target", 10, 90, 50, 5) / 100.0
    exit_dte = st.sidebar.slider("DTE exit", 0, 45, 14, 1)

    stop_label = st.sidebar.selectbox(
        "Stop loss",
        ["None", "1.5x credit", "2.0x credit", "3.0x credit"],
    )
    stop_map = {
        "None": None,
        "1.5x credit": 1.5,
        "2.0x credit": 2.0,
        "3.0x credit": 3.0,
    }

    risk_label = st.sidebar.selectbox("Risk per trade", ["0.5%", "1.0%", "2.0%"], index=1)
    risk_map = {"0.5%": 0.005, "1.0%": 0.01, "2.0%": 0.02}

    max_concurrent_positions = st.sidebar.selectbox(
        "Max concurrent positions",
        [1, 2, 4],
        index=0,
    )
    slippage_per_leg = st.sidebar.number_input(
        "Slippage per leg",
        min_value=0.0,
        max_value=1.0,
        value=0.02,
        step=0.01,
        format="%.2f",
    )
    sizing_label = st.sidebar.radio(
        "Sizing method",
        ["Fixed NAV", "Compounding NAV"],
        horizontal=True,
    )

    config = BacktestConfig(
        starting_nav=starting_nav,
        target_dte=int(target_dte),
        dte_tolerance=int(dte_tolerance),
        short_put_otm_pct=float(short_otm_pct),
        spread_width_mode=spread_width_mode,
        spread_width_pct=float(spread_width_pct),
        spread_width_dollars=float(spread_width_dollars),
        profit_target_pct=float(profit_target_pct),
        exit_dte=int(exit_dte),
        stop_loss_multiple=stop_map[stop_label],
        risk_per_trade_pct=risk_map[risk_label],
        max_concurrent_positions=int(max_concurrent_positions),
        slippage_per_leg=float(slippage_per_leg),
        sizing_method="fixed_nav" if sizing_label == "Fixed NAV" else "compounding_nav",
    )

    payload = _config_payload(config)
    clicked = st.sidebar.button("Run Backtest", type="primary", use_container_width=True)
    if "active_options_config" not in st.session_state:
        st.session_state["active_options_config"] = payload
    elif clicked:
        if st.session_state["active_options_config"] != payload:
            st.session_state.pop("options_backtest_grid", None)
        st.session_state["active_options_config"] = payload

    if st.session_state["active_options_config"] != payload:
        st.sidebar.warning("Controls changed. Click Run Backtest to apply them.")

    active_payload = st.session_state["active_options_config"]
    st.sidebar.info(
        f"Active slippage: ${active_payload['slippage_per_leg']:.2f} per leg, "
        f"${active_payload['slippage_per_leg'] * 2.0:.2f} per spread side."
    )
    return dataset_path, active_payload


def _render_coverage(coverage: dict[str, Any], dataset_path: str) -> None:
    stage_distribution = coverage.get("stage_distribution", {})
    stage_frame = pd.DataFrame(
        [{"hedge_stage_label": key, "trading_days": value} for key, value in stage_distribution.items()]
    )

    with st.expander("Data Coverage And Field Mapping", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("First date", _compact_date(coverage["first_date"]))
        col2.metric("Last date", _compact_date(coverage["last_date"]))
        col3.metric("Trading days", f"{coverage['trading_days']:,}")
        col4.metric("Unique contracts", f"{coverage['unique_contracts']:,}")

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("Option rows", f"{coverage['option_rows']:,}")
        col6.metric("Trigger ON days", _fmt_pct(coverage["trigger_on_pct"]))
        col7.metric("Duplicate option/date", f"{coverage['duplicate_option_date_rows']:,}")
        col8.metric("Missing hedge days", f"{coverage['missing_hedge_days']:,}")

        st.caption(f"Source: {dataset_path}")
        st.markdown(
            """
            Field mapping: option identity and prices use `date`, `option_ticker`,
            `expiration`, `strike`, `dte`, `underlying_close`, `option_close`,
            and `moneyness`. Helix state uses `bhr_active`, `credit_stress`,
            `vol_stress`, `hedge_trigger_active`, `hedge_stage`, and
            `hedge_stage_label`.
            """
        )
        if not stage_frame.empty:
            st.dataframe(stage_frame, use_container_width=True, hide_index=True)


def _render_summary(metrics: pd.DataFrame) -> None:
    st.subheader("Strategy Comparison")
    ordered = metrics.set_index("strategy").reindex(STRATEGY_ORDER).dropna(how="all").reset_index()
    columns = st.columns(max(1, len(ordered)))
    for column, (_, row) in zip(columns, ordered.iterrows()):
        with column:
            st.markdown(f"**{row['strategy']}**")
            st.metric("Total return", _fmt_pct(row["total_return"]))
            st.metric("Max drawdown", _fmt_pct(row["max_drawdown"]))
            st.metric("Sharpe", _fmt_num(row["sharpe"]))
            st.metric("Win rate", _fmt_pct(row["win_rate"]))
            st.metric("Worst trade", _fmt_money(row["worst_trade"]))
            st.metric("Trades", f"{int(row['trade_count']):,}")

    helix = metrics.loc[metrics["strategy"].eq("Strategy C - Benign + Trigger Exit")]
    if not helix.empty:
        row = helix.iloc[0]
        st.subheader("Helix Trigger Accounting")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Trigger value added", _fmt_money(row["total_trigger_value_added"]))
        col2.metric("Trigger exits", f"{int(row['trigger_exit_count']):,}")
        col3.metric("Losses avoided", _fmt_money(row["total_losses_avoided"]))
        col4.metric("False-exit cost", _fmt_money(row["total_false_exit_cost"]))


def _render_equity_charts(equity: pd.DataFrame) -> None:
    if equity.empty:
        st.info("No equity curve available.")
        return

    plot_frame = equity.copy()
    plot_frame["date"] = pd.to_datetime(plot_frame["date"])

    equity_fig = px.line(
        plot_frame,
        x="date",
        y="equity",
        color="strategy",
        title="Equity Curve",
        labels={"equity": "Equity", "date": "Date", "strategy": "Strategy"},
    )
    equity_fig.update_layout(legend_title_text="", hovermode="x unified")
    st.plotly_chart(equity_fig, use_container_width=True)

    drawdown_fig = px.line(
        plot_frame,
        x="date",
        y="drawdown",
        color="strategy",
        title="Drawdown",
        labels={"drawdown": "Drawdown", "date": "Date", "strategy": "Strategy"},
    )
    drawdown_fig.update_yaxes(tickformat=".0%")
    drawdown_fig.update_layout(legend_title_text="", hovermode="x unified")
    st.plotly_chart(drawdown_fig, use_container_width=True)


def _filter_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        strategy_filter = st.multiselect(
            "Strategy",
            sorted(trades["strategy"].dropna().unique()),
            default=sorted(trades["strategy"].dropna().unique()),
        )
    with col2:
        exit_filter = st.multiselect(
            "Exit reason",
            sorted(trades["exit_reason"].dropna().unique()),
            default=sorted(trades["exit_reason"].dropna().unique()),
        )
    with col3:
        pnl_filter = st.selectbox("P&L", ["All", "Winning", "Losing"])
    with col4:
        trigger_only = st.checkbox("Trigger exits only")

    filtered = trades.loc[
        trades["strategy"].isin(strategy_filter)
        & trades["exit_reason"].isin(exit_filter)
    ].copy()
    if pnl_filter == "Winning":
        filtered = filtered.loc[filtered["pnl_dollars"] > 0]
    elif pnl_filter == "Losing":
        filtered = filtered.loc[filtered["pnl_dollars"] < 0]
    if trigger_only:
        filtered = filtered.loc[filtered["exit_reason"].eq("trigger_exit")]
    return filtered


def _render_trade_table(filtered: pd.DataFrame) -> None:
    display_cols = [
        "trade_id",
        "strategy",
        "entry_signal_date",
        "entry_date",
        "exit_date",
        "exit_reason",
        "expiration",
        "initial_dte",
        "short_strike",
        "long_strike",
        "entry_credit",
        "exit_debit",
        "contracts",
        "pnl_dollars",
        "pnl_pct_risk",
        "trigger_value_added",
    ]
    available_cols = [column for column in display_cols if column in filtered.columns]
    st.dataframe(
        filtered[available_cols].sort_values(["entry_date", "strategy"]),
        use_container_width=True,
        hide_index=True,
    )


def _render_trade_detail(data, trades: pd.DataFrame, filtered: pd.DataFrame) -> None:
    if filtered.empty:
        st.info("No trades match the current filters.")
        return

    labels = {
        row["trade_id"]: (
            f"{row['entry_date']} | {row['strategy']} | {row['exit_reason']} | "
            f"{_fmt_money(row['pnl_dollars'])}"
        )
        for _, row in filtered.iterrows()
    }
    selected_id = st.selectbox("Inspect trade", list(labels), format_func=lambda key: labels[key])
    trade = trades.loc[trades["trade_id"].eq(selected_id)].iloc[0]
    details = get_trade_details(data, trades, selected_id)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Entry credit", _fmt_price(trade["entry_credit"]))
    c2.metric("Exit debit", _fmt_price(trade["exit_debit"]))
    c3.metric("P&L", _fmt_money(trade["pnl_dollars"]))
    c4.metric("P&L / risk", _fmt_pct(trade["pnl_pct_risk"]))
    c5.metric("Holding days", f"{int(trade['holding_days'])}")

    if details.empty:
        st.info("No option path available for this trade.")
        return

    details = details.copy()
    details["date"] = pd.to_datetime(details["date"])

    price_fig = go.Figure()
    price_fig.add_trace(
        go.Scatter(
            x=details["date"],
            y=details["underlying_close"],
            mode="lines",
            name="SPY close",
        )
    )
    price_fig.add_trace(
        go.Scatter(
            x=details["date"],
            y=[trade["short_strike"]] * len(details),
            mode="lines",
            name="Short strike",
            line={"dash": "dash"},
        )
    )
    price_fig.add_trace(
        go.Scatter(
            x=details["date"],
            y=[trade["long_strike"]] * len(details),
            mode="lines",
            name="Long strike",
            line={"dash": "dot"},
        )
    )
    price_fig.update_layout(title="SPY Price During Trade", hovermode="x unified")
    st.plotly_chart(price_fig, use_container_width=True)

    spread_fig = go.Figure()
    spread_fig.add_trace(
        go.Scatter(
            x=details["date"],
            y=details["spread_value"],
            mode="lines+markers",
            name="Spread value",
        )
    )
    spread_fig.add_trace(
        go.Scatter(
            x=details["date"],
            y=details["open_pnl_per_spread"],
            mode="lines",
            name="Open P&L per spread",
            yaxis="y2",
        )
    )
    spread_fig.update_layout(
        title="Spread Value And Open P&L",
        hovermode="x unified",
        yaxis={"title": "Spread value"},
        yaxis2={"title": "Open P&L", "overlaying": "y", "side": "right"},
    )
    st.plotly_chart(spread_fig, use_container_width=True)

    state = details[
        [
            "date",
            "hedge_stage_label",
            "bhr_active",
            "credit_stress",
            "vol_stress",
            "hedge_trigger_active",
        ]
    ].drop_duplicates("date")
    state_plot = state.copy()
    for column in ["bhr_active", "credit_stress", "vol_stress", "hedge_trigger_active"]:
        state_plot[column] = state_plot[column].fillna(False).astype(int)
    state_long = state_plot.melt(
        id_vars=["date"],
        value_vars=["bhr_active", "credit_stress", "vol_stress", "hedge_trigger_active"],
        var_name="state",
        value_name="active",
    )
    state_fig = px.line(
        state_long,
        x="date",
        y="active",
        color="state",
        markers=True,
        title="Helix States Through Trade",
    )
    state_fig.update_yaxes(tickvals=[0, 1], ticktext=["Off", "On"])
    state_fig.update_layout(hovermode="x unified")
    st.plotly_chart(state_fig, use_container_width=True)

    trigger_rows = state.loc[state["hedge_trigger_active"].fillna(False).astype(bool)]
    if not trigger_rows.empty:
        st.markdown("**Trigger-active observations during selected trade**")
        st.dataframe(trigger_rows, use_container_width=True, hide_index=True)


def _render_trade_explorer(data, trades: pd.DataFrame) -> None:
    st.subheader("Trade Explorer")
    filtered = _filter_trades(trades)
    _render_trade_table(filtered)
    st.divider()
    _render_trade_detail(data, trades, filtered)


def _render_regime_analysis(trades: pd.DataFrame) -> None:
    st.subheader("Entry Regime Analysis")
    summary = regime_entry_summary(trades)
    if summary.empty:
        st.info("No trades available for regime analysis.")
        return
    st.dataframe(summary, use_container_width=True, hide_index=True)


def _heatmap(grid: pd.DataFrame, metric: str, width_pct: float) -> go.Figure:
    subset = grid.loc[grid["spread_width_pct"].eq(width_pct)].copy()
    subset["short_otm_label"] = (subset["short_otm_pct"] * 100.0).map(lambda value: f"{value:g}%")
    pivot = subset.pivot(index="target_dte", columns="short_otm_label", values=metric)
    fig = px.imshow(
        pivot,
        aspect="auto",
        text_auto=".2f",
        color_continuous_scale="RdYlGn",
        title=f"{metric.replace('_', ' ').title()} | Width {width_pct * 100.0:g}% SPY",
    )
    fig.update_layout(xaxis_title="Short OTM", yaxis_title="Target DTE")
    return fig


def _render_parameter_grid(path_string: str, config_payload: dict[str, Any]) -> None:
    st.subheader("Parameter Grid")
    st.caption("Robustness, not optimization.")
    st.markdown(
        """
        This grid compares Always Sell against Benign + Trigger Exit over a
        deliberately small parameter set: DTE 30/45/60, short OTM 5%/7.5%/10%,
        and spread width 2.5%/5% of SPY.
        """
    )
    run_grid = st.button("Run Small Parameter Grid", type="secondary")
    if not run_grid and "options_backtest_grid" not in st.session_state:
        st.info("Run the grid when you want a compact robustness check.")
        return

    if run_grid:
        with st.spinner("Running small robustness grid..."):
            st.session_state["options_backtest_grid"] = _run_grid(path_string, config_payload)

    grid = st.session_state["options_backtest_grid"]
    st.dataframe(grid, use_container_width=True, hide_index=True)

    for width_pct in sorted(grid["spread_width_pct"].dropna().unique()):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.plotly_chart(_heatmap(grid, "total_pnl_difference", width_pct), use_container_width=True)
        with col2:
            st.plotly_chart(_heatmap(grid, "max_drawdown_difference", width_pct), use_container_width=True)
        with col3:
            st.plotly_chart(_heatmap(grid, "sharpe_difference", width_pct), use_container_width=True)


def main() -> None:
    st.title("Helix Options Strategy Lab")
    st.caption("Test whether the Helix hedge regime improves systematic SPY put-spread selling.")

    dataset_path, config_payload = _render_sidebar()
    dataset = Path(dataset_path)
    if not dataset.exists():
        st.error(f"Joined dataset not found: {dataset}")
        st.stop()

    with st.spinner("Loading joined options and Helix state data..."):
        data, coverage = _load_research_data(str(dataset))

    _render_coverage(coverage, str(dataset))
    st.info(
        "Execution timing: hedge state is observed at close t; entries and trigger exits "
        "execute on the next available session with valid prices for both option legs. "
        "Option prices are daily closes, and prices are not forward-filled."
    )
    st.warning(
        "Two-year options history is a mechanism test, not sufficient evidence of "
        "long-run tail-risk robustness."
    )

    with st.spinner("Running strategy comparison..."):
        results, metrics, trades, equity = _run_comparison(str(dataset), config_payload)

    st.caption(
        f"Active execution friction: ${config_payload['slippage_per_leg']:.2f} per leg. "
        f"Entry credits are reduced and exit debits are increased by "
        f"${2.0 * config_payload['slippage_per_leg']:.2f} per spread side."
    )

    _render_summary(metrics)

    overview_tab, trade_tab, regime_tab, grid_tab = st.tabs(
        ["Charts", "Trade Explorer", "Regime Analysis", "Parameter Grid"]
    )
    with overview_tab:
        _render_equity_charts(equity)
        with st.expander("Metrics Table"):
            st.dataframe(metrics, use_container_width=True, hide_index=True)

    with trade_tab:
        _render_trade_explorer(data, trades)

    with regime_tab:
        _render_regime_analysis(trades)

    with grid_tab:
        _render_parameter_grid(str(dataset), config_payload)


if __name__ == "__main__":
    main()
