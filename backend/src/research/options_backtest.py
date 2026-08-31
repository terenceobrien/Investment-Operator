"""Research backtester for historical SPY put credit spreads.

The engine uses daily option closes from the joined historical options/regime
file. Hedge-trigger state from close t is only actionable on the next available
session for the selected option spread.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pandas as pd


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOINED_DATASET = (
    BACKEND_ROOT
    / "data"
    / "risk"
    / "backtest"
    / "spy_options_with_hedge_trigger.csv"
)

StrategyKey = Literal["always_sell", "benign_entries", "benign_trigger_exit"]
SpreadWidthMode = Literal["pct_spy", "fixed_dollars"]
SizingMethod = Literal["fixed_nav", "compounding_nav"]


REQUIRED_COLUMNS = [
    "date",
    "option_ticker",
    "expiration",
    "strike",
    "option_type",
    "dte",
    "underlying_close",
    "option_close",
    "moneyness",
    "hedge_trigger_active",
    "hedge_stage",
    "hedge_stage_label",
    "bhr_active",
    "credit_stress",
    "vol_stress",
]

OPTION_NUMERIC_COLUMNS = [
    "strike",
    "dte",
    "underlying_close",
    "option_close",
    "option_open",
    "option_high",
    "option_low",
    "option_volume",
    "moneyness",
    "hedge_stage",
]

HEDGE_BOOL_COLUMNS = [
    "hedge_trigger_active",
    "bhr_active",
    "credit_stress",
    "vol_stress",
    "data_quality_ok",
]

TRADE_COLUMNS = [
    "trade_id",
    "strategy",
    "entry_signal_date",
    "entry_date",
    "expiration",
    "initial_dte",
    "underlying_entry",
    "short_ticker",
    "long_ticker",
    "short_strike",
    "long_strike",
    "short_moneyness",
    "spread_width",
    "entry_credit",
    "contracts",
    "max_profit",
    "max_loss",
    "hedge_stage_at_entry",
    "bhr_at_entry",
    "credit_stress_at_entry",
    "vol_stress_at_entry",
    "hedge_trigger_at_entry",
    "exit_signal_date",
    "exit_date",
    "exit_reason",
    "underlying_exit",
    "exit_debit",
    "holding_days",
    "pnl_dollars",
    "pnl_pct_risk",
    "max_adverse_excursion",
    "max_favorable_excursion",
    "counterfactual_exit_date",
    "counterfactual_exit_reason",
    "counterfactual_pnl",
    "trigger_value_added",
]


@dataclass(frozen=True)
class BacktestConfig:
    starting_nav: float = 100_000.0
    target_dte: int = 45
    dte_tolerance: int = 5
    short_put_otm_pct: float = 0.075
    spread_width_mode: SpreadWidthMode = "pct_spy"
    spread_width_pct: float = 0.05
    spread_width_dollars: float = 25.0
    profit_target_pct: float = 0.50
    exit_dte: int = 14
    stop_loss_multiple: float | None = None
    risk_per_trade_pct: float = 0.01
    max_concurrent_positions: int = 1
    slippage_per_leg: float = 0.02
    sizing_method: SizingMethod = "fixed_nav"


@dataclass(frozen=True)
class StrategySpec:
    key: StrategyKey
    label: str
    benign_entries_only: bool
    trigger_exit: bool


@dataclass(frozen=True)
class EntryCandidate:
    signal_date: date
    expiration: date
    dte_distance: float


@dataclass(frozen=True)
class SpreadSelection:
    signal_date: date
    expiration: date
    short_ticker: str
    long_ticker: str
    short_strike: float
    long_strike: float
    underlying_signal: float
    short_moneyness_signal: float
    signal_dte: int
    hedge_trigger_active: bool | None
    hedge_stage: int | None
    hedge_stage_label: str | None
    bhr_active: bool | None
    credit_stress: bool | None
    vol_stress: bool | None


@dataclass(frozen=True)
class ExitPlan:
    exit_signal_date: date
    exit_date: date
    exit_reason: str
    exit_debit: float
    underlying_exit: float
    settlement_used: bool = False


@dataclass
class OptionData:
    frame: pd.DataFrame
    by_date: dict[date, pd.DataFrame]
    by_ticker: dict[str, pd.DataFrame]
    trading_dates: list[date]
    underlying_by_date: dict[date, float]


@dataclass
class BacktestResult:
    strategy: StrategyKey
    strategy_label: str
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    metrics: dict[str, Any]


STRATEGIES: dict[StrategyKey, StrategySpec] = {
    "always_sell": StrategySpec(
        key="always_sell",
        label="Strategy A - Always Sell",
        benign_entries_only=False,
        trigger_exit=False,
    ),
    "benign_entries": StrategySpec(
        key="benign_entries",
        label="Strategy B - Benign Entries Only",
        benign_entries_only=True,
        trigger_exit=False,
    ),
    "benign_trigger_exit": StrategySpec(
        key="benign_trigger_exit",
        label="Strategy C - Benign + Trigger Exit",
        benign_entries_only=True,
        trigger_exit=True,
    ),
}

EXIT_PRIORITY = ["trigger_exit", "stop_loss", "profit_target", "dte_exit", "expiration"]


class BacktestDataError(ValueError):
    """Raised for unusable research input data."""


def load_joined_dataset(path: str | Path = DEFAULT_JOINED_DATASET) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise BacktestDataError(f"joined options/regime dataset does not exist: {path}")
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, low_memory=False)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    raise BacktestDataError(f"unsupported dataset type: {path}")


def _parse_bool(value: Any) -> bool | None:
    if value is None or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        if float(value) == 1.0:
            return True
        if float(value) == 0.0:
            return False
    text = str(value).strip().lower()
    if text in {"true", "t", "1", "yes", "y"}:
        return True
    if text in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _is_true(value: Any) -> bool:
    return _parse_bool(value) is True


def _is_false(value: Any) -> bool:
    return _parse_bool(value) is False


def _maybe_int(value: Any) -> int | None:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return None
    return int(numeric)


def normalize_options_data(raw: pd.DataFrame) -> OptionData:
    frame = raw.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise BacktestDataError(f"joined dataset is missing required columns: {missing}")

    frame["date"] = pd.to_datetime(frame["date"], format="mixed", errors="coerce").dt.date
    frame["expiration"] = pd.to_datetime(
        frame["expiration"],
        format="mixed",
        errors="coerce",
    ).dt.date
    for column in OPTION_NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in HEDGE_BOOL_COLUMNS:
        if column in frame.columns:
            frame[column] = frame[column].map(_parse_bool)

    frame["option_ticker"] = frame["option_ticker"].astype(str)
    frame["option_type"] = frame["option_type"].astype(str).str.lower()
    frame["hedge_stage_label"] = frame["hedge_stage_label"].where(
        frame["hedge_stage_label"].notna(),
        None,
    )

    frame = frame.loc[frame["option_type"].eq("put")].copy()
    frame = frame.dropna(
        subset=[
            "date",
            "expiration",
            "option_ticker",
            "strike",
            "dte",
            "underlying_close",
            "option_close",
            "moneyness",
        ]
    )
    frame = frame.loc[
        (frame["strike"] > 0)
        & (frame["underlying_close"] > 0)
        & (frame["option_close"] >= 0)
    ].copy()
    frame["dte"] = frame["dte"].round().astype(int)

    duplicate_rows = int(frame.duplicated(["date", "option_ticker"]).sum())
    if duplicate_rows:
        raise BacktestDataError(
            f"joined dataset contains duplicate option_ticker/date rows: {duplicate_rows}"
        )
    if frame.empty:
        raise BacktestDataError("joined dataset has no valid put option observations")

    frame = frame.sort_values(["date", "expiration", "strike", "option_ticker"])
    by_date = {key: group.copy() for key, group in frame.groupby("date", sort=True)}
    by_ticker = {key: group.copy() for key, group in frame.groupby("option_ticker", sort=False)}
    trading_dates = sorted(by_date)
    underlying_by_date = (
        frame.dropna(subset=["underlying_close"])
        .drop_duplicates("date", keep="last")
        .set_index("date")["underlying_close"]
        .astype(float)
        .to_dict()
    )
    return OptionData(
        frame=frame.reset_index(drop=True),
        by_date=by_date,
        by_ticker=by_ticker,
        trading_dates=trading_dates,
        underlying_by_date=underlying_by_date,
    )


def validate_options_data(data: OptionData) -> dict[str, Any]:
    frame = data.frame
    daily = frame.drop_duplicates("date", keep="last").sort_values("date")
    hedge = daily["hedge_trigger_active"].dropna().map(_parse_bool)
    stage_counts = (
        daily["hedge_stage_label"].fillna("Missing").value_counts().sort_index().to_dict()
    )
    return {
        "first_date": min(data.trading_dates),
        "last_date": max(data.trading_dates),
        "trading_days": int(len(data.trading_dates)),
        "option_rows": int(len(frame)),
        "unique_contracts": int(frame["option_ticker"].nunique()),
        "trigger_on_pct": float(sum(value is True for value in hedge) / len(hedge))
        if len(hedge)
        else 0.0,
        "stage_distribution": {str(key): int(value) for key, value in stage_counts.items()},
        "duplicate_option_date_rows": int(frame.duplicated(["date", "option_ticker"]).sum()),
        "missing_hedge_rows": int(frame["hedge_trigger_active"].isna().sum()),
        "missing_hedge_days": int(daily["hedge_trigger_active"].isna().sum()),
    }


def _config_with_updates(config: BacktestConfig, **updates: Any) -> BacktestConfig:
    return replace(config, **updates)


def spread_width_target(config: BacktestConfig, underlying_close: float) -> float:
    if config.spread_width_mode == "fixed_dollars":
        return float(config.spread_width_dollars)
    return float(underlying_close) * float(config.spread_width_pct)


def build_entry_schedule(data: OptionData, config: BacktestConfig) -> list[EntryCandidate]:
    frame = data.frame
    eligible = frame.loc[
        frame["dte"].between(config.target_dte - config.dte_tolerance, config.target_dte + config.dte_tolerance)
    ].copy()
    if eligible.empty:
        return []

    rows: list[EntryCandidate] = []
    grouped = (
        eligible.groupby(["expiration", "date"], as_index=False)
        .agg(dte=("dte", "median"), strikes=("strike", "nunique"))
        .loc[lambda x: x["strikes"] >= 2]
    )
    for expiration, group in grouped.groupby("expiration", sort=True):
        group = group.copy()
        group["dte_distance"] = (group["dte"] - config.target_dte).abs()
        chosen = group.sort_values(["dte_distance", "date"]).iloc[0]
        rows.append(
            EntryCandidate(
                signal_date=chosen["date"],
                expiration=expiration,
                dte_distance=float(chosen["dte_distance"]),
            )
        )
    return sorted(rows, key=lambda candidate: (candidate.signal_date, candidate.expiration))


def select_spread(
    data: OptionData,
    signal_date: date,
    config: BacktestConfig,
    *,
    expiration: date | None = None,
) -> SpreadSelection | None:
    day = data.by_date.get(signal_date)
    if day is None or day.empty:
        return None

    day = day.loc[day["option_close"].notna() & day["option_close"].ge(0)].copy()
    min_dte = config.target_dte - config.dte_tolerance
    max_dte = config.target_dte + config.dte_tolerance
    day = day.loc[day["dte"].between(min_dte, max_dte)]
    if expiration is not None:
        day = day.loc[day["expiration"].eq(expiration)]
    if day.empty:
        return None

    expirations = (
        day.groupby("expiration", as_index=False)
        .agg(dte=("dte", "median"), strikes=("strike", "nunique"))
        .loc[lambda x: x["strikes"] >= 2]
    )
    if expirations.empty:
        return None
    expirations["distance"] = (expirations["dte"] - config.target_dte).abs()

    target_moneyness = 1.0 - config.short_put_otm_pct
    for _, expiration_row in expirations.sort_values(["distance", "expiration"]).iterrows():
        expiry = expiration_row["expiration"]
        expiry_rows = day.loc[day["expiration"].eq(expiry)].copy()
        if expiry_rows.empty:
            continue
        underlying = float(expiry_rows["underlying_close"].median())
        width_target = spread_width_target(config, underlying)
        expiry_rows["short_distance"] = (expiry_rows["moneyness"] - target_moneyness).abs()
        short_rows = expiry_rows.sort_values(["short_distance", "strike"], ascending=[True, False])
        for _, short in short_rows.iterrows():
            short_strike = float(short["strike"])
            long_candidates = expiry_rows.loc[expiry_rows["strike"] < short_strike].copy()
            if long_candidates.empty:
                continue
            long_target = short_strike - width_target
            long_candidates["long_distance"] = (
                long_candidates["strike"] - long_target
            ).abs()
            long = long_candidates.sort_values(["long_distance", "strike"]).iloc[0]
            long_strike = float(long["strike"])
            if long_strike >= short_strike:
                continue
            signal_credit = float(short["option_close"]) - float(long["option_close"])
            if signal_credit <= 0:
                continue
            return SpreadSelection(
                signal_date=signal_date,
                expiration=expiry,
                short_ticker=str(short["option_ticker"]),
                long_ticker=str(long["option_ticker"]),
                short_strike=short_strike,
                long_strike=long_strike,
                underlying_signal=underlying,
                short_moneyness_signal=float(short["moneyness"]),
                signal_dte=int(round(float(short["dte"]))),
                hedge_trigger_active=_parse_bool(short.get("hedge_trigger_active")),
                hedge_stage=_maybe_int(short.get("hedge_stage")),
                hedge_stage_label=(
                    None
                    if pd.isna(short.get("hedge_stage_label"))
                    else str(short.get("hedge_stage_label"))
                ),
                bhr_active=_parse_bool(short.get("bhr_active")),
                credit_stress=_parse_bool(short.get("credit_stress")),
                vol_stress=_parse_bool(short.get("vol_stress")),
            )
    return None


def get_spread_path(
    data: OptionData,
    short_ticker: str,
    long_ticker: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    short = data.by_ticker.get(short_ticker)
    long = data.by_ticker.get(long_ticker)
    if short is None or long is None or short.empty or long.empty:
        return pd.DataFrame()

    short_cols = [
        "date",
        "option_ticker",
        "expiration",
        "strike",
        "dte",
        "underlying_close",
        "option_close",
        "hedge_trigger_active",
        "hedge_stage",
        "hedge_stage_label",
        "bhr_active",
        "credit_stress",
        "vol_stress",
    ]
    long_cols = ["date", "option_ticker", "strike", "option_close"]
    path = short[short_cols].merge(
        long[long_cols],
        on="date",
        how="inner",
        suffixes=("_short", "_long"),
    )
    if start_date is not None:
        path = path.loc[path["date"] >= start_date]
    if end_date is not None:
        path = path.loc[path["date"] <= end_date]
    if path.empty:
        return pd.DataFrame()

    path = path.rename(
        columns={
            "option_ticker_short": "short_ticker",
            "option_ticker_long": "long_ticker",
            "strike_short": "short_strike",
            "strike_long": "long_strike",
            "option_close_short": "short_price",
            "option_close_long": "long_price",
        }
    )
    path["spread_value"] = path["short_price"] - path["long_price"]
    path = path.loc[path["spread_value"].ge(0)]
    return path.sort_values("date").reset_index(drop=True)


def _first_path_row_after(path: pd.DataFrame, signal_date: date, expiration: date) -> pd.Series | None:
    rows = path.loc[(path["date"] > signal_date) & (path["date"] <= expiration)]
    if rows.empty:
        return None
    return rows.iloc[0]


def _path_row_on(path: pd.DataFrame, row_date: date) -> pd.Series | None:
    rows = path.loc[path["date"].eq(row_date)]
    if rows.empty:
        return None
    return rows.iloc[0]


def _underlying_on_or_before(data: OptionData, target_date: date) -> float | None:
    dates = [row_date for row_date in data.underlying_by_date if row_date <= target_date]
    if not dates:
        return None
    return float(data.underlying_by_date[max(dates)])


def _close_exit_from_row(row: pd.Series, config: BacktestConfig) -> tuple[float, float]:
    slippage = 2.0 * config.slippage_per_leg
    return float(row["spread_value"]) + slippage, float(row["underlying_close"])


def _expiration_exit(
    data: OptionData,
    path: pd.DataFrame,
    selection: SpreadSelection,
    config: BacktestConfig,
) -> ExitPlan:
    expiration_row = _path_row_on(path, selection.expiration)
    if expiration_row is not None:
        exit_debit, underlying_exit = _close_exit_from_row(expiration_row, config)
        return ExitPlan(
            exit_signal_date=selection.expiration,
            exit_date=selection.expiration,
            exit_reason="expiration",
            exit_debit=exit_debit,
            underlying_exit=underlying_exit,
            settlement_used=False,
        )

    underlying = _underlying_on_or_before(data, selection.expiration)
    if underlying is None:
        underlying = float(path["underlying_close"].dropna().iloc[-1])
    short_intrinsic = max(selection.short_strike - underlying, 0.0)
    long_intrinsic = max(selection.long_strike - underlying, 0.0)
    settlement_value = short_intrinsic - long_intrinsic
    return ExitPlan(
        exit_signal_date=selection.expiration,
        exit_date=selection.expiration,
        exit_reason="expiration",
        exit_debit=float(settlement_value),
        underlying_exit=float(underlying),
        settlement_used=True,
    )


def _choose_exit_reason(reasons: list[str]) -> str:
    for reason in EXIT_PRIORITY:
        if reason in reasons:
            return reason
    return reasons[0]


def _simulate_exit(
    data: OptionData,
    path: pd.DataFrame,
    selection: SpreadSelection,
    config: BacktestConfig,
    *,
    entry_date: date,
    entry_credit: float,
    allow_trigger_exit: bool,
) -> ExitPlan:
    valuation_rows = path.loc[
        (path["date"] > entry_date) & (path["date"] <= selection.expiration)
    ]
    for _, row in valuation_rows.iterrows():
        signal_date = row["date"]
        reasons: list[str] = []
        signal_debit, _underlying = _close_exit_from_row(row, config)
        if allow_trigger_exit and _is_true(row.get("hedge_trigger_active")):
            reasons.append("trigger_exit")
        if (
            config.stop_loss_multiple is not None
            and signal_debit >= entry_credit * config.stop_loss_multiple
        ):
            reasons.append("stop_loss")
        if signal_debit <= entry_credit * (1.0 - config.profit_target_pct):
            reasons.append("profit_target")
        if int(row["dte"]) <= config.exit_dte:
            reasons.append("dte_exit")
        if row["date"] >= selection.expiration:
            reasons.append("expiration")

        if not reasons:
            continue

        reason = _choose_exit_reason(reasons)
        if reason == "expiration":
            return _expiration_exit(data, path, selection, config)

        execution_row = _first_path_row_after(path, signal_date, selection.expiration)
        if execution_row is None:
            return _expiration_exit(data, path, selection, config)
        exit_debit, underlying_exit = _close_exit_from_row(execution_row, config)
        return ExitPlan(
            exit_signal_date=signal_date,
            exit_date=execution_row["date"],
            exit_reason=reason,
            exit_debit=exit_debit,
            underlying_exit=underlying_exit,
        )

    return _expiration_exit(data, path, selection, config)


def _excursions(
    path: pd.DataFrame,
    *,
    entry_date: date,
    exit_date: date,
    entry_credit: float,
    contracts: int,
    config: BacktestConfig,
    exit_pnl: float,
) -> tuple[float, float]:
    rows = path.loc[(path["date"] >= entry_date) & (path["date"] <= exit_date)]
    values = [0.0, float(exit_pnl)]
    for _, row in rows.iterrows():
        debit, _underlying = _close_exit_from_row(row, config)
        values.append((entry_credit - debit) * 100.0 * contracts)
    return float(min(values)), float(max(values))


def _finalize_trade(
    *,
    trade_id: str,
    strategy: StrategySpec,
    selection: SpreadSelection,
    entry_row: pd.Series,
    entry_credit: float,
    contracts: int,
    max_loss_per_contract: float,
    exit_plan: ExitPlan,
    path: pd.DataFrame,
    config: BacktestConfig,
) -> dict[str, Any]:
    pnl = (entry_credit - exit_plan.exit_debit) * 100.0 * contracts
    max_profit = entry_credit * 100.0 * contracts
    max_loss = max_loss_per_contract * contracts
    mae, mfe = _excursions(
        path,
        entry_date=entry_row["date"],
        exit_date=exit_plan.exit_date,
        entry_credit=entry_credit,
        contracts=contracts,
        config=config,
        exit_pnl=pnl,
    )
    return {
        "trade_id": trade_id,
        "strategy": strategy.label,
        "entry_signal_date": selection.signal_date,
        "entry_date": entry_row["date"],
        "expiration": selection.expiration,
        "initial_dte": int(entry_row["dte"]),
        "underlying_entry": float(entry_row["underlying_close"]),
        "short_ticker": selection.short_ticker,
        "long_ticker": selection.long_ticker,
        "short_strike": selection.short_strike,
        "long_strike": selection.long_strike,
        "short_moneyness": selection.short_strike / float(entry_row["underlying_close"]),
        "spread_width": selection.short_strike - selection.long_strike,
        "entry_credit": entry_credit,
        "contracts": int(contracts),
        "max_profit": max_profit,
        "max_loss": max_loss,
        "hedge_stage_at_entry": selection.hedge_stage,
        "bhr_at_entry": selection.bhr_active,
        "credit_stress_at_entry": selection.credit_stress,
        "vol_stress_at_entry": selection.vol_stress,
        "hedge_trigger_at_entry": selection.hedge_trigger_active,
        "exit_signal_date": exit_plan.exit_signal_date,
        "exit_date": exit_plan.exit_date,
        "exit_reason": exit_plan.exit_reason,
        "underlying_exit": exit_plan.underlying_exit,
        "exit_debit": exit_plan.exit_debit,
        "holding_days": (exit_plan.exit_date - entry_row["date"]).days,
        "pnl_dollars": pnl,
        "pnl_pct_risk": pnl / max_loss if max_loss > 0 else math.nan,
        "max_adverse_excursion": mae,
        "max_favorable_excursion": mfe,
        "counterfactual_exit_date": None,
        "counterfactual_exit_reason": None,
        "counterfactual_pnl": math.nan,
        "trigger_value_added": math.nan,
    }


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLUMNS)


def _build_trade(
    data: OptionData,
    selection: SpreadSelection,
    strategy: StrategySpec,
    config: BacktestConfig,
    *,
    contracts_nav: float,
    sequence: int,
) -> dict[str, Any] | None:
    path = get_spread_path(
        data,
        selection.short_ticker,
        selection.long_ticker,
        start_date=selection.signal_date,
        end_date=selection.expiration,
    )
    if path.empty:
        return None

    entry_row = _first_path_row_after(path, selection.signal_date, selection.expiration)
    if entry_row is None:
        return None

    entry_credit = float(entry_row["spread_value"]) - 2.0 * config.slippage_per_leg
    if entry_credit <= 0:
        return None

    spread_width = selection.short_strike - selection.long_strike
    max_loss_per_contract = (spread_width - entry_credit) * 100.0
    if max_loss_per_contract <= 0:
        return None

    risk_budget = contracts_nav * config.risk_per_trade_pct
    contracts = math.floor(risk_budget / max_loss_per_contract)
    if contracts < 1:
        return None

    exit_plan = _simulate_exit(
        data,
        path,
        selection,
        config,
        entry_date=entry_row["date"],
        entry_credit=entry_credit,
        allow_trigger_exit=strategy.trigger_exit,
    )
    trade_id = f"{strategy.key}-{sequence:04d}-{entry_row['date']}-{selection.short_ticker}"
    trade = _finalize_trade(
        trade_id=trade_id,
        strategy=strategy,
        selection=selection,
        entry_row=entry_row,
        entry_credit=entry_credit,
        contracts=contracts,
        max_loss_per_contract=max_loss_per_contract,
        exit_plan=exit_plan,
        path=path,
        config=config,
    )

    if strategy.trigger_exit and trade["exit_reason"] == "trigger_exit":
        counterfactual_exit = _simulate_exit(
            data,
            path,
            selection,
            config,
            entry_date=entry_row["date"],
            entry_credit=entry_credit,
            allow_trigger_exit=False,
        )
        counterfactual_pnl = (
            entry_credit - counterfactual_exit.exit_debit
        ) * 100.0 * contracts
        trade["counterfactual_exit_date"] = counterfactual_exit.exit_date
        trade["counterfactual_exit_reason"] = counterfactual_exit.exit_reason
        trade["counterfactual_pnl"] = counterfactual_pnl
        trade["trigger_value_added"] = trade["pnl_dollars"] - counterfactual_pnl

    return trade


def run_backtest(
    data: OptionData | pd.DataFrame | str | Path,
    config: BacktestConfig | None = None,
    *,
    strategy: StrategyKey = "always_sell",
) -> BacktestResult:
    config = config or BacktestConfig()
    option_data = ensure_option_data(data)
    spec = STRATEGIES[strategy]
    schedule = build_entry_schedule(option_data, config)

    trades: list[dict[str, Any]] = []
    open_positions: list[tuple[date, float]] = []
    nav = config.starting_nav
    traded_expirations: set[date] = set()

    for candidate in schedule:
        realized_now = [
            position for position in open_positions if position[0] <= candidate.signal_date
        ]
        if realized_now and config.sizing_method == "compounding_nav":
            nav += sum(pnl for _exit_date, pnl in realized_now)
        open_positions = [
            position for position in open_positions if position[0] > candidate.signal_date
        ]
        if candidate.expiration in traded_expirations:
            continue
        if len(open_positions) >= config.max_concurrent_positions:
            continue

        selection = select_spread(
            option_data,
            candidate.signal_date,
            config,
            expiration=candidate.expiration,
        )
        if selection is None:
            continue
        if spec.benign_entries_only and not _is_false(selection.hedge_trigger_active):
            traded_expirations.add(candidate.expiration)
            continue

        sizing_nav = config.starting_nav if config.sizing_method == "fixed_nav" else nav
        trade = _build_trade(
            option_data,
            selection,
            spec,
            config,
            contracts_nav=sizing_nav,
            sequence=len(trades) + 1,
        )
        traded_expirations.add(candidate.expiration)
        if trade is None:
            continue
        trades.append(trade)
        open_positions.append((trade["exit_date"], float(trade["pnl_dollars"])))

    trades_frame = _empty_trades() if not trades else pd.DataFrame(trades)[TRADE_COLUMNS]
    equity = build_equity_curve(option_data, trades_frame, config.starting_nav, spec.label)
    metrics = calculate_metrics(trades_frame, equity, config.starting_nav)
    return BacktestResult(
        strategy=strategy,
        strategy_label=spec.label,
        trades=trades_frame,
        equity_curve=equity,
        metrics=metrics,
    )


def ensure_option_data(data: OptionData | pd.DataFrame | str | Path) -> OptionData:
    if isinstance(data, OptionData):
        return data
    if isinstance(data, pd.DataFrame):
        return normalize_options_data(data)
    return normalize_options_data(load_joined_dataset(data))


def build_equity_curve(
    data: OptionData,
    trades: pd.DataFrame,
    starting_nav: float,
    strategy_label: str,
) -> pd.DataFrame:
    exit_dates = []
    if not trades.empty:
        exit_dates = pd.to_datetime(trades["exit_date"], errors="coerce").dt.date.dropna().tolist()
    dates = sorted(set(data.trading_dates) | set(exit_dates))
    frame = pd.DataFrame({"date": dates})
    frame["realized_pnl"] = 0.0
    if not trades.empty:
        pnl_by_date = trades.groupby("exit_date")["pnl_dollars"].sum()
        frame["realized_pnl"] = frame["date"].map(pnl_by_date).fillna(0.0)
    frame["cumulative_pnl"] = frame["realized_pnl"].cumsum()
    frame["equity"] = starting_nav + frame["cumulative_pnl"]
    frame["running_peak"] = frame["equity"].cummax()
    frame["drawdown"] = frame["equity"] / frame["running_peak"] - 1.0
    frame["strategy"] = strategy_label
    return frame


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or pd.isna(denominator):
        return math.nan
    return float(numerator) / float(denominator)


def calculate_metrics(
    trades: pd.DataFrame,
    equity: pd.DataFrame,
    starting_nav: float,
) -> dict[str, Any]:
    total_pnl = float(trades["pnl_dollars"].sum()) if not trades.empty else 0.0
    ending_nav = starting_nav + total_pnl
    days = max(1, (max(equity["date"]) - min(equity["date"])).days) if not equity.empty else 1
    total_return = total_pnl / starting_nav
    annualized_return = (ending_nav / starting_nav) ** (365.25 / days) - 1.0 if ending_nav > 0 else math.nan
    returns = equity["equity"].pct_change().dropna() if not equity.empty else pd.Series(dtype=float)
    sharpe = math.nan
    sortino = math.nan
    if not returns.empty and returns.std(ddof=0) > 0:
        sharpe = float(returns.mean() / returns.std(ddof=0) * math.sqrt(252.0))
    downside = returns.loc[returns < 0]
    if not downside.empty and downside.std(ddof=0) > 0:
        sortino = float(returns.mean() / downside.std(ddof=0) * math.sqrt(252.0))

    if trades.empty:
        wins = trades
        losses = trades
    else:
        wins = trades.loc[trades["pnl_dollars"] > 0]
        losses = trades.loc[trades["pnl_dollars"] < 0]

    sum_wins = float(wins["pnl_dollars"].sum()) if not wins.empty else 0.0
    sum_losses = float(losses["pnl_dollars"].sum()) if not losses.empty else 0.0
    trigger_trades = (
        trades.loc[trades["exit_reason"].eq("trigger_exit")]
        if not trades.empty
        else trades
    )
    trigger_values = pd.to_numeric(
        trigger_trades.get("trigger_value_added", pd.Series(dtype=float)),
        errors="coerce",
    ).dropna()
    positive_trigger = trigger_values.loc[trigger_values > 0]
    negative_trigger = trigger_values.loc[trigger_values < 0]

    return {
        "total_pnl": total_pnl,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": float(equity["drawdown"].min()) if not equity.empty else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "trade_count": int(len(trades)),
        "win_rate": _safe_ratio(len(wins), len(trades)) if len(trades) else math.nan,
        "average_win": float(wins["pnl_dollars"].mean()) if not wins.empty else math.nan,
        "average_loss": float(losses["pnl_dollars"].mean()) if not losses.empty else math.nan,
        "win_loss_ratio": _safe_ratio(
            float(wins["pnl_dollars"].mean()) if not wins.empty else math.nan,
            abs(float(losses["pnl_dollars"].mean())) if not losses.empty else math.nan,
        ),
        "profit_factor": _safe_ratio(sum_wins, abs(sum_losses)),
        "worst_trade": float(trades["pnl_dollars"].min()) if not trades.empty else 0.0,
        "best_trade": float(trades["pnl_dollars"].max()) if not trades.empty else 0.0,
        "average_holding_days": float(trades["holding_days"].mean()) if not trades.empty else math.nan,
        "total_premium_collected": float((trades["entry_credit"] * 100.0 * trades["contracts"]).sum())
        if not trades.empty
        else 0.0,
        "total_premium_retained": total_pnl,
        "max_loss_events": int((trades["pnl_dollars"] <= -0.99 * trades["max_loss"]).sum())
        if not trades.empty
        else 0,
        "losses_gt_50pct_risk": int((trades["pnl_dollars"] <= -0.50 * trades["max_loss"]).sum())
        if not trades.empty
        else 0,
        "trigger_exit_count": int(len(trigger_trades)),
        "trigger_exit_rate": _safe_ratio(len(trigger_trades), len(trades)) if len(trades) else math.nan,
        "average_trigger_exit_pnl": float(trigger_trades["pnl_dollars"].mean())
        if not trigger_trades.empty
        else math.nan,
        "total_trigger_value_added": float(trigger_values.sum()) if not trigger_values.empty else 0.0,
        "total_losses_avoided": float(positive_trigger.sum()) if not positive_trigger.empty else 0.0,
        "total_false_exit_cost": abs(float(negative_trigger.sum())) if not negative_trigger.empty else 0.0,
    }


def compare_strategies(
    data: OptionData | pd.DataFrame | str | Path,
    config: BacktestConfig | None = None,
) -> dict[StrategyKey, BacktestResult]:
    option_data = ensure_option_data(data)
    config = config or BacktestConfig()
    return {
        key: run_backtest(option_data, config, strategy=key)
        for key in ("always_sell", "benign_entries", "benign_trigger_exit")
    }


def metrics_frame(results: dict[StrategyKey, BacktestResult]) -> pd.DataFrame:
    rows = []
    for key, result in results.items():
        row = {"strategy_key": key, "strategy": result.strategy_label}
        row.update(result.metrics)
        rows.append(row)
    return pd.DataFrame(rows)


def combined_trades(results: dict[StrategyKey, BacktestResult]) -> pd.DataFrame:
    frames = [result.trades for result in results.values() if not result.trades.empty]
    if not frames:
        return _empty_trades()
    return pd.concat(frames, ignore_index=True)


def combined_equity(results: dict[StrategyKey, BacktestResult]) -> pd.DataFrame:
    frames = [result.equity_curve for result in results.values()]
    return pd.concat(frames, ignore_index=True)


def get_trade_details(
    data: OptionData | pd.DataFrame | str | Path,
    trades: pd.DataFrame,
    trade_id: str,
) -> pd.DataFrame:
    if trades.empty or trade_id not in set(trades["trade_id"]):
        return pd.DataFrame()
    option_data = ensure_option_data(data)
    trade = trades.loc[trades["trade_id"].eq(trade_id)].iloc[0]
    short_ticker = str(trade["short_ticker"])
    long_ticker = str(trade["long_ticker"])
    path = get_spread_path(
        option_data,
        short_ticker,
        long_ticker,
        start_date=trade["entry_signal_date"],
        end_date=trade["exit_date"],
    )
    if path.empty:
        return path
    path = path.copy()
    path["open_pnl_per_spread"] = (
        float(trade["entry_credit"]) - path["spread_value"] - 0.0
    ) * 100.0
    return path


def regime_entry_summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            columns=["strategy", "hedge_stage_at_entry", "trade_count", "mean_pnl", "win_rate", "worst_trade", "average_premium"]
        )
    frame = trades.copy()
    frame["winner"] = frame["pnl_dollars"] > 0
    frame["premium"] = frame["entry_credit"] * 100.0 * frame["contracts"]
    return (
        frame.groupby(["strategy", "hedge_stage_at_entry"], dropna=False)
        .agg(
            trade_count=("trade_id", "count"),
            mean_pnl=("pnl_dollars", "mean"),
            win_rate=("winner", "mean"),
            worst_trade=("pnl_dollars", "min"),
            average_premium=("premium", "mean"),
        )
        .reset_index()
        .sort_values(["strategy", "hedge_stage_at_entry"])
    )


def run_parameter_grid(
    data: OptionData | pd.DataFrame | str | Path,
    base_config: BacktestConfig | None = None,
    *,
    dte_values: tuple[int, ...] = (30, 45, 60),
    short_otm_values: tuple[float, ...] = (0.05, 0.075, 0.10),
    spread_width_pct_values: tuple[float, ...] = (0.025, 0.05),
) -> pd.DataFrame:
    option_data = ensure_option_data(data)
    base = base_config or BacktestConfig()
    rows: list[dict[str, Any]] = []
    for target_dte in dte_values:
        for short_otm in short_otm_values:
            for width_pct in spread_width_pct_values:
                config = _config_with_updates(
                    base,
                    target_dte=target_dte,
                    short_put_otm_pct=short_otm,
                    spread_width_mode="pct_spy",
                    spread_width_pct=width_pct,
                )
                always = run_backtest(option_data, config, strategy="always_sell")
                helix = run_backtest(option_data, config, strategy="benign_trigger_exit")
                rows.append(
                    {
                        "target_dte": target_dte,
                        "short_otm_pct": short_otm,
                        "spread_width_pct": width_pct,
                        "always_trade_count": always.metrics["trade_count"],
                        "helix_trade_count": helix.metrics["trade_count"],
                        "always_total_pnl": always.metrics["total_pnl"],
                        "helix_total_pnl": helix.metrics["total_pnl"],
                        "total_pnl_difference": helix.metrics["total_pnl"] - always.metrics["total_pnl"],
                        "always_max_drawdown": always.metrics["max_drawdown"],
                        "helix_max_drawdown": helix.metrics["max_drawdown"],
                        "max_drawdown_difference": helix.metrics["max_drawdown"] - always.metrics["max_drawdown"],
                        "always_sharpe": always.metrics["sharpe"],
                        "helix_sharpe": helix.metrics["sharpe"],
                        "sharpe_difference": helix.metrics["sharpe"] - always.metrics["sharpe"],
                    }
                )
    return pd.DataFrame(rows)
