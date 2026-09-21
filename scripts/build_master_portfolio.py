#!/usr/bin/env python3
"""Reconstruct a Fidelity daily portfolio ledger from transactions and prices.

No network requests, benchmark series, or tax basis. Option marks can be estimates.
Dependencies: pandas, numpy, scipy, pandas_market_calendars.
See docs/portfolio_ledger.md for accounting conventions and limitations.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

from portfolio_option_valuation import (
    black_scholes_price, solve_implied_volatility, parse_option_contract,
    build_option_position_ledger, estimate_daily_option_values, option_reconciliation_report,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRANSACTIONS = Path.home() / "Downloads" / "Full Account History.csv"
DEFAULT_PRICES = ROOT / "prices.csv"
DEFAULT_OUTPUT = ROOT / "data" / "portfolio"
DEFAULT_RISK_FREE_RATE = 0.04  # Annual continuously compounded decimal, not percent.
DEFAULT_DIVIDEND_YIELD = 0.0
DIVIDEND_YIELDS = {}  # Optional underlying-specific assumptions, e.g. {"XYZ": 0.015}.
CORE_SYMBOLS = {"SPAXX"}  # Explicitly configured core cash, not all money-market funds.
ZERO = Decimal("0")
QTY_TOLERANCE = 1e-9  # Diagnostics only; quantities are never rounded to this tolerance.
OPTION_PATTERN = re.compile(r"^-([A-Z0-9.]+?)(\d{6})([CP])(\d+(?:\.\d+)?)$")
ISSUE_COLUMNS = ["Severity", "Issue", "Date", "Ticker", "Source_Row", "Detail", "Invalidates_Ledger_From_Date"]


class Issues:
    def __init__(self):
        self.rows = []

    def add(self, issue, detail, date=None, ticker="", row=None,
            severity="warning", blocks=False):
        self.rows.append(dict(Severity=severity, Issue=issue, Date=date,
                              Ticker=ticker, Source_Row=row, Detail=detail,
                              Invalidates_Ledger_From_Date=blocks))

    def frame(self):
        return pd.DataFrame(self.rows, columns=ISSUE_COLUMNS)


def parse_date(value, context):
    for fmt in ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"):
        try:
            return pd.Timestamp(datetime.strptime(str(value).strip(), fmt))
        except ValueError:
            pass
    raise ValueError(f"{context}: invalid date {value!r}")


def parse_decimal(value, context, blank=None):
    text = str(value).strip()
    if not text:
        return blank
    text = text.replace(",", "").replace("$", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{context}: invalid number {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"{context}: non-finite number {value!r}")
    return number


def cents(value):
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise ValueError(f"Cash amount contains fractions of a cent: {value}")
    return int(scaled)


def load_transactions(path):
    raw = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    raw.columns = raw.columns.str.strip()
    required = {"Run Date", "Action", "Symbol", "Quantity", "Amount ($)"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Missing Fidelity fields: {sorted(required - set(raw.columns))}")
    if raw.empty:
        raise ValueError("Transaction file is empty")
    if "Account Number" in raw and raw["Account Number"].nunique() != 1:
        raise ValueError("Expected exactly one account; filter the transaction input first")
    return raw


def normalize_transactions(raw, issues):
    records = []
    for i, source in raw.iterrows():
        line = i + 2
        run_date = parse_date(source["Run Date"], f"transaction row {line}")
        symbol = source["Symbol"].strip().upper()
        action = source["Action"].strip()
        amount = parse_decimal(source["Amount ($)"], f"row {line} Amount")
        if amount is None:
            raise ValueError(f"Row {line}: Amount is required, including explicit zero for non-cash events")
        quantity = parse_decimal(source["Quantity"], f"row {line} Quantity", ZERO)
        commission = parse_decimal(source.get("Commission ($)", ""), f"row {line} commission", ZERO)
        fee = parse_decimal(source.get("Fees ($)", ""), f"row {line} fees", ZERO)
        if commission < 0 or fee < 0:
            issues.add("negative_fee_field", "Fee rebate needs review", run_date, symbol, line, blocks=True)
        option = bool(symbol.startswith("-") or OPTION_PATTERN.fullmatch(symbol))
        metadata = parse_option_contract(symbol, source.get("Description", ""), action) if option else {}
        expiration = metadata.get("Expiration", pd.NaT)
        effective = run_date
        # Fidelity posts these expirations the next morning. Only explicit expiration
        # records are backdated; fee/dividend 'as of' text does not move cash dates.
        if action.upper().startswith("EXPIRED") and option:
            match = re.search(r"as of (\d{4}-\d{2}-\d{2})", action, re.I)
            effective = parse_date(match[1], f"row {line} expiration") if match else expiration if pd.notna(expiration) else run_date
            if (pd.notna(expiration) and effective != expiration) or effective > run_date:
                raise ValueError(f"Row {line}: contradictory option expiration dates")
            if amount != 0 and effective != run_date:
                raise ValueError(f"Row {line}: expiration unexpectedly has cash; review before backdating")
        record = dict(Source_Row=line, Run_Date=run_date, Date=effective,
                      Action=action, Ticker=symbol, Quantity=quantity,
                      Price=parse_decimal(source.get("Price ($)", ""), f"row {line} Price"),
                      Amount=amount, Amount_Cents=cents(amount),
                      Fees=commission + fee, Fee_Cents=cents(commission + fee),
                      Accrued_Interest=parse_decimal(source.get("Accrued Interest ($)", ""), f"row {line} accrued interest", ZERO),
                      Description=source.get("Description", "").strip(),
                      Account_Type=source.get("Type", "").strip(),
                      Settlement_Date=source.get("Settlement Date", "").strip(),
                      Is_Option=bool(option), Expiration=expiration,
                      Is_Core=symbol in CORE_SYMBOLS,
                      Option_ID=metadata.get("Option_ID", ""), Underlying=metadata.get("Underlying", ""),
                      Strike=metadata.get("Strike", np.nan), Option_Type=metadata.get("Option_Type", ""),
                      Contract_Multiplier=metadata.get("Contract_Multiplier", 1))
        records.append(record)
    for i in raw.index[raw.duplicated(keep=False)]:
        r = records[i]
        issues.add("duplicate_transaction", "Exact duplicate retained; verify against brokerage", r["Date"], r["Ticker"], r["Source_Row"], blocks=True)
    return pd.DataFrame(records).sort_values(["Date", "Source_Row"]).reset_index(drop=True)


def classify_transactions(transactions, issues):
    tx = transactions.copy()
    categories, confident, deltas, cash_values = [], [], [], []
    for row in tx.itertuples():
        action = row.Action.upper()
        category, known, delta, cash = "other", True, ZERO, row.Amount_Cents
        # Narrow, explicit bank movement rules. Trade proceeds, journals, and
        # generic 'transfer' descriptions are never presumed external capital.
        if action.startswith(("ELECTRONIC FUNDS TRANSFER RECEIVED", "BANK WIRE RECEIVED")) and not row.Ticker and row.Quantity == 0 and cash > 0:
            category = "external_deposit"
        elif action.startswith(("ELECTRONIC FUNDS TRANSFER PAID", "ELECTRONIC FUNDS TRANSFER SENT", "BANK WIRE SENT")) and not row.Ticker and row.Quantity == 0 and cash < 0:
            category = "external_withdrawal"
        elif action.startswith("DIVIDEND RECEIVED"):
            category = "dividend"
            # Cash dividends (including SPAXX) are internal income. A separate
            # reinvestment purchases shares; it is never an external contribution.
        elif action.startswith(("INTEREST EARNED", "INTEREST RECEIVED", "MARGIN INTEREST", "INTEREST CHARGED")):
            category = "interest"
        elif action.startswith(("FEE CHARGED", "ADVISORY FEE")):
            category = "fee"
        elif action.startswith("EXPIRED") and row.Is_Option:
            category, delta = "option_expiration", row.Quantity
        elif action.startswith(("EXERCISED", "ASSIGNED", "ASSIGNMENT")):
            category = "option_exercise_assignment" if row.Is_Option else "corporate_action"
            delta = row.Quantity
            known = bool(row.Ticker) and delta != 0
        elif "AUTO-JOURNAL" in action and action.startswith("JOURNALED"):
            category = "internal_cash_activity"
            # Cash/margin subaccount journals do not create account-level holdings.
            # Their signed quantities and amounts must cancel; verified below.
        elif row.Is_Core and action.startswith(("REINVESTMENT", "YOU BOUGHT", "YOU SOLD")):
            category, cash = "internal_cash_activity", 0
            # Cash INCLUDES the core fund. A $1 sweep/reinvestment/redemption just
            # changes its representation; neither shares nor cash are counted again.
            if row.Price != Decimal("1") or abs(row.Amount + row.Quantity) > Decimal("0.01") or row.Fees != 0:
                known = False
        elif action.startswith(("YOU BOUGHT", "REINVESTMENT")):
            category = "option_buy" if row.Is_Option else "buy"
            delta = row.Quantity
            known = bool(row.Ticker) and delta > 0 and cash <= 0
        elif action.startswith("YOU SOLD"):
            category = "option_sell" if row.Is_Option else "sell"
            delta = row.Quantity
            known = bool(row.Ticker) and delta < 0 and cash >= 0
        elif action.startswith(("STOCK SPLIT", "MERGER", "SPINOFF", "SPIN-OFF", "REORGANIZATION")):
            category, known = "corporate_action", False
        else:
            known = False
        if category in {"dividend", "interest", "fee", "external_deposit", "external_withdrawal"} and row.Quantity != 0:
            known = False
        if not known:
            issues.add("unclassified_or_ambiguous_transaction", f"{category}: {row.Action}; amount retained as cash, quantity interpretation requires review", row.Date, row.Ticker, row.Source_Row, blocks=True)
        categories.append(category)
        confident.append(known)
        deltas.append(delta)
        cash_values.append(cash)
    tx["Category"], tx["Confident"] = categories, confident
    tx["Quantity_Delta"], tx["Cash_Cents"] = deltas, cash_values
    journals = tx[tx.Action.str.contains("AUTO-JOURNAL", case=False)]
    for (day, ticker), group in journals.groupby(["Date", "Ticker"]):
        if sum(group.Quantity, ZERO) != 0 or group.Amount_Cents.sum() != 0:
            issues.add("unbalanced_auto_journal", "Cash/margin journal legs do not cancel; holdings require review", day, ticker, blocks=True)
            tx.loc[group.index, "Confident"] = False
    for row in tx.itertuples():
        if row.Category not in {"buy", "sell", "option_buy", "option_sell"}:
            continue
        multiplier = 1
        if row.Is_Option:
            multiplier = row.Contract_Multiplier
        if row.Price is None:
            issues.add("missing_transaction_price", "Cannot cross-check trade amount", row.Date, row.Ticker, row.Source_Row)
        else:
            expected = -row.Quantity * row.Price * multiplier - row.Fees - row.Accrued_Interest
            # Displayed execution price can be rounded, especially fractional orders.
            tolerance = max(Decimal("0.02"), abs(row.Quantity) * multiplier * Decimal("0.005"))
            if abs(row.Amount - expected) > tolerance:
                issues.add("trade_amount_mismatch", f"Net amount {row.Amount}; price x quantity less fees implies {expected}. Net amount remains authoritative.", row.Date, row.Ticker, row.Source_Row)
    return tx


def load_prices(path, issues):
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {"Date", "Ticker", "Close", "Adj Close"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Missing price fields: {sorted(required - set(raw.columns))}")
    records = []
    for i, row in raw.iterrows():
        day = parse_date(row.Date, f"prices row {i + 2}")
        ticker = row.Ticker.strip().upper()
        if not ticker:
            raise ValueError(f"Prices row {i + 2}: empty ticker")
        values = {}
        for field in ("Close", "Adj Close"):
            value = parse_decimal(row[field], f"prices row {i + 2} {field}")
            if value is not None and value <= 0:
                raise ValueError(f"Prices row {i + 2}: non-positive {field}")
            values[field] = float(value) if value is not None else np.nan
        records.append({"Date": day, "Ticker": ticker, **values})
    prices = pd.DataFrame(records)
    if prices.empty or prices.duplicated(["Date", "Ticker"]).any():
        raise ValueError("Prices must be nonempty with exactly one row per Date/Ticker")
    return prices.sort_values(["Date", "Ticker"])


def build_trading_calendar(prices, transactions, issues):
    inception = transactions.Date.min()
    calendar = pd.DatetimeIndex(sorted(prices.loc[prices.Date >= inception, "Date"].unique()), name="Date")
    if calendar.empty:
        raise ValueError("No price dates on or after account inception")
    expected = mcal.get_calendar("NYSE").schedule(start_date=inception, end_date=calendar[-1]).index
    for day in expected.difference(calendar):
        issues.add("missing_trading_date", "Entire NYSE session is absent from the supplied price calendar", day, blocks=True)
    for day in calendar.difference(expected):
        issues.add("nontrading_price_date", "Price-file date is not a NYSE session; retained as requested", day, blocks=True)
    return calendar


def assign_ledger_dates(transactions, calendar, issues):
    tx = transactions.copy()
    tx["Ledger_Date"] = pd.NaT
    for i, row in tx.iterrows():
        pos = calendar.searchsorted(row.Date)
        if pos == len(calendar):
            issues.add("transaction_after_price_coverage", "Transaction excluded from daily output; update prices for full reconciliation", row.Date, row.Ticker, row.Source_Row)
            continue
        day = calendar[pos]
        tx.at[i, "Ledger_Date"] = day
        if day != row.Date:
            issues.add("transaction_mapped_to_next_price_date", f"Effective {row.Date.date()} activity included on {day.date()}", day, row.Ticker, row.Source_Row, severity="info")
    return tx


def build_daily_position_matrix(transactions, calendar, is_option=False):
    selected = transactions[transactions.Is_Option.eq(is_option) & ~transactions.Is_Core]
    selected = selected.loc[selected.Quantity_Delta.map(lambda q: q != 0).astype(bool)]
    tickers = sorted(selected.Ticker.unique())
    changes = {}
    for row in selected.itertuples():
        if pd.notna(row.Ledger_Date):
            key = (row.Ledger_Date, row.Ticker)
            changes[key] = changes.get(key, ZERO) + row.Quantity_Delta
    # Decimal accumulation preserves fractional shares without floating cancellation
    # dust. Convert only at the pandas valuation/output boundary; never round shares.
    balances = dict.fromkeys(tickers, ZERO)
    records = []
    for day in calendar:
        for ticker in tickers:
            balances[ticker] += changes.get((day, ticker), ZERO)
        records.append({ticker: float(q) for ticker, q in balances.items()})
    return pd.DataFrame(records, index=calendar, columns=tickers, dtype=float)


def reconstruct_cash(transactions, calendar):
    names = ["External_Flow", "External_Deposits", "External_Withdrawals", "Buy_Cash_Flow", "Sell_Cash_Flow", "Option_Buy_Cash_Flow", "Option_Sell_Cash_Flow", "Dividends", "Interest", "Fees", "Other_Internal_Cash_Flow", "Option_Net_Cash_Flow", "Raw_Transaction_Cash_Flow", "Core_Bookkeeping_Adjustment", "Net_Cash_Flow"]
    daily = pd.DataFrame(0, index=calendar, columns=names, dtype="int64")
    for row in transactions.itertuples():
        if pd.isna(row.Ledger_Date):
            continue
        day, category = row.Ledger_Date, row.Category
        amount, fees = row.Cash_Cents, row.Fee_Cents
        daily.at[day, "Raw_Transaction_Cash_Flow"] += row.Amount_Cents
        daily.at[day, "Core_Bookkeeping_Adjustment"] += amount - row.Amount_Cents
        daily.at[day, "Net_Cash_Flow"] += amount
        if category in {"external_deposit", "external_withdrawal"}:
            daily.at[day, "External_Flow"] += amount
            daily.at[day, "External_Deposits" if amount > 0 else "External_Withdrawals"] += amount
        elif category in {"buy", "sell", "option_buy", "option_sell"}:
            field = {"buy": "Buy_Cash_Flow", "sell": "Sell_Cash_Flow", "option_buy": "Option_Buy_Cash_Flow", "option_sell": "Option_Sell_Cash_Flow"}[category]
            # Amount is already NET of commissions/fees. Diagnostics split this
            # into gross trade cash and negative Fees; cash uses net Amount once.
            daily.at[day, field] += amount + fees
            daily.at[day, "Fees"] -= fees
        elif category in {"dividend", "interest", "fee"}:
            daily.at[day, {"dividend": "Dividends", "interest": "Interest", "fee": "Fees"}[category]] += amount
        else:
            daily.at[day, "Other_Internal_Cash_Flow"] += amount
        if row.Is_Option:
            daily.at[day, "Option_Net_Cash_Flow"] += amount
    daily["Cash"] = daily.Net_Cash_Flow.cumsum()
    daily["Net_Internal_Cash_Flow"] = daily.Net_Cash_Flow - daily.External_Flow
    parts = ["Buy_Cash_Flow", "Sell_Cash_Flow", "Option_Buy_Cash_Flow", "Option_Sell_Cash_Flow", "Dividends", "Interest", "Fees", "Other_Internal_Cash_Flow"]
    assert daily[parts].sum(axis=1).equals(daily.Net_Internal_Cash_Flow)
    assert (daily.Raw_Transaction_Cash_Flow + daily.Core_Bookkeeping_Adjustment).equals(daily.Net_Cash_Flow)
    return daily / 100.0


def value_positions(quantities, prices, issues):
    closes = prices.pivot(index="Date", columns="Ticker", values="Close").reindex(index=quantities.index, columns=quantities.columns)
    held = quantities.ne(0)
    missing = held & closes.isna()
    values = (quantities * closes).where(held, 0.0)
    for day, ticker in missing.stack().loc[lambda s: s].index:
        issues.add("missing_price_while_held", "No Close price; no forward fill; securities value and NAV unavailable", day, ticker)
    # No skipna portfolio sums: one unpriced held security invalidates the total.
    total = values.sum(axis=1, skipna=False)
    return values, total, missing.any(axis=1), closes


def handle_options(transactions, quantities, prices, issues, risk_free_rate,
                   dividend_yields, default_dividend_yield):
    events = build_option_position_ledger(transactions, prices, issues, risk_free_rate,
                                         dividend_yields, default_dividend_yield)
    daily, values, lots = estimate_daily_option_values(events, quantities, prices, issues)
    held = quantities.ne(0)
    result = pd.DataFrame(index=quantities.index)
    result["Open_Option_Position_Flag"] = held.any(axis=1)
    result["Option_Pricing_Incomplete_Flag"] = (held & values.isna()).any(axis=1)
    result["Options_Market_Value"] = values.sum(axis=1, skipna=False)
    result["Option_Valuation_Method"] = "none"
    result["Option_MV_Estimated_Flag"] = False
    for day, rows in daily[daily.Contracts.ne(0)].groupby("Date"):
        methods = set(rows.Valuation_Method)
        result.at[day, "Option_Valuation_Method"] = next(iter(methods)) if len(methods) == 1 else "mixed"
        result.at[day, "Option_MV_Estimated_Flag"] = any(method != "actual_transaction" for method in methods)
    result["Option_Realized_Cash_Flow"] = 0.0
    # Preserve the original exact, after-fee cash result at fully closed episodes.
    # Modeling changes marks only; it never changes premiums, fees or external flow.
    for ticker, group in transactions[transactions.Is_Option].groupby("Ticker"):
        balance, episode_cash = ZERO, 0
        for day, rows in group.dropna(subset=["Ledger_Date"]).groupby("Ledger_Date", sort=True):
            balance += sum(rows.Quantity_Delta, ZERO)
            episode_cash += int(rows.Cash_Cents.sum())
            if balance == 0:
                result.at[day, "Option_Realized_Cash_Flow"] += episode_cash / 100
                episode_cash = 0
        expiration = group.Expiration.iloc[0]
        if pd.notna(expiration):
            for day in quantities.index[quantities.index >= expiration]:
                if ticker in quantities and quantities.at[day, ticker] != 0:
                    issues.add("unresolved_expired_option", "Intrinsic/fallback mark supplied, but no expiration/closing/assignment record; position resolution requires review", day, ticker, blocks=True)
        for row in group[group.Category.eq("option_expiration")].itertuples():
            if pd.notna(row.Ledger_Date) and quantities.at[row.Ledger_Date, ticker] != 0:
                issues.add("expiration_not_flat", "Explicit expiration did not fully close the contract", row.Ledger_Date, ticker, row.Source_Row, blocks=True)
        for row in group[group.Category.eq("option_exercise_assignment")].itertuples():
            if pd.isna(row.Ledger_Date):
                continue
            stock_legs = transactions[(transactions.Ledger_Date == row.Ledger_Date) &
                                      (transactions.Ticker == row.Underlying)]
            if row.Amount == 0 and (stock_legs.empty or sum(stock_legs.Quantity_Delta, ZERO) == 0):
                issues.add("exercise_assignment_missing_stock_leg", "Zero-cash option close has no underlying share delivery; no synthetic proceeds or shares invented", row.Ledger_Date, ticker, row.Source_Row, blocks=True)
    return result, values, daily, lots


def calculate_nav(cash, securities, options, missing):
    result = cash.join(options)
    result["Securities_Market_Value"] = securities
    result["Missing_Security_Price_Flag"] = missing
    result["NAV_Incomplete_Flag"] = missing | result.Option_Pricing_Incomplete_Flag
    result["Known_Assets_Subtotal"] = result.Cash + securities
    result["Total_NAV"] = result.Cash + securities + result.Options_Market_Value
    return result


def run_validation_checks(master, transactions, stocks, options, calendar, issues):
    included = transactions[transactions.Ledger_Date.notna()]
    for quantities, label in [(stocks, "security"), (options, "option")]:
        for ticker in quantities:
            expected = float(sum(included.loc[included.Ticker.eq(ticker), "Quantity_Delta"], ZERO))
            assert quantities[ticker].iloc[-1] == expected, f"Ending quantity mismatch: {ticker}"
            raw_signed_quantity = float(sum(included.loc[included.Ticker.eq(ticker), "Quantity"], ZERO))
            if abs(expected - raw_signed_quantity) > QTY_TOLERANCE:
                issues.add("raw_quantity_reconciliation_mismatch", f"Ledger quantity {expected}; original signed transaction quantities total {raw_signed_quantity}", calendar[-1], ticker, blocks=True)
            full_history = float(sum(transactions.loc[transactions.Ticker.eq(ticker), "Quantity_Delta"], ZERO))
            if abs(expected - full_history) > QTY_TOLERANCE:
                issues.add("ending_quantity_vs_full_history", f"At price cutoff: {expected}; full transaction history: {full_history}", calendar[-1], ticker)
            for day in quantities.index[quantities[ticker] < -QTY_TOLERANCE]:
                # Signed short options are valid liabilities. Unmatched closing
                # events are checked separately by the option lot ledger.
                issues.add(f"negative_{label}_quantity", f"Quantity {quantities.at[day, ticker]}; {'short option liability' if label == 'option' else 'verify short position or missing activity'}", day, ticker,
                           severity="info" if label == "option" else "warning", blocks=label != "option")
            trades = included[(included.Ticker == ticker) & included.Category.isin(["buy", "sell"])]
            if expected > QTY_TOLERANCE and not trades.empty and trades.iloc[-1].Category == "sell":
                bought = float(sum(trades.loc[trades.Category.eq("buy"), "Quantity_Delta"], ZERO))
                if expected < bought * 0.001:
                    issues.add("possible_exit_residual", f"Residual {expected} after sale is <0.1% of total purchases; verify fractional exit", calendar[-1], ticker)
    expected_cash = included.Cash_Cents.sum() / 100
    assert np.isclose(master.Cash.iloc[-1], expected_cash, atol=1e-8, rtol=0)
    delta = master.Cash.diff()
    delta.iloc[0] = master.Cash.iloc[0]
    residual = delta - master.External_Flow - master.Net_Internal_Cash_Flow
    master["Cash_Reconciliation_Residual"] = residual.where(residual.abs() > 1e-8, 0.0)
    for day in master.index[residual.abs() > 0.005]:
        issues.add("unexplained_cash_jump", f"Cash movement residual {residual.at[day]}", day, blocks=True)
    for row in included[~included.Confident & included.Cash_Cents.ne(0)].itertuples():
        issues.add("unexplained_cash_activity", f"Unclassified signed cash amount {row.Cash_Cents / 100}", row.Ledger_Date, row.Ticker, row.Source_Row, blocks=True)
    for day in master.index[master.Cash < -0.005]:
        issues.add("negative_cash_balance", f"Trade-date cash {master.at[day, 'Cash']}; may be margin borrowing, verify against statement", day)
    if calendar[-1] > transactions.Run_Date.max():
        issues.add("transaction_coverage_ends_before_prices", "Holdings carried past last transaction date; confirm history export covers the price cutoff", transactions.Run_Date.max() + pd.Timedelta(days=1), blocks=True)
    # A provided statement is needed for independent reconciliation; matching this
    # ledger to its source history cannot prove that the source export is complete.
    issues.add("no_independent_holdings_snapshot", "No brokerage holdings/cash statement supplied. Reconciled to full transaction history only; inception assumes zero prior cash/positions.", calendar[-1], severity="info")
    master["Ledger_Reconciliation_Incomplete_Flag"] = False
    for issue in issues.rows:
        if issue["Invalidates_Ledger_From_Date"]:
            master.loc[master.index >= issue["Date"], "Ledger_Reconciliation_Incomplete_Flag"] = True
    master["NAV_Potentially_Incomplete_Flag"] = master.NAV_Incomplete_Flag | master.Ledger_Reconciliation_Incomplete_Flag
    master["Return_Eligible_Flag"] = ~master.NAV_Potentially_Incomplete_Flag & master.Total_NAV.notna()


def calculate_returns(master):
    result = master.copy()
    prev = result.Total_NAV.shift(1)
    valid = result.Return_Eligible_Flag & result.Return_Eligible_Flag.shift(1, fill_value=False) & prev.gt(0)
    result["Daily_Return"] = ((result.Total_NAV - result.External_Flow) / prev - 1).where(valid)
    result["Cumulative_Return"] = np.nan
    # Establish inception base only if first-row NAV is trustworthy. Do not restart
    # after missing valuations, and never let pandas cumprod silently skip a gap.
    if result.Return_Eligible_Flag.iloc[0] and result.Total_NAV.iloc[0] > 0:
        result.iloc[0, result.columns.get_loc("Cumulative_Return")] = 0.0
        result.loc[result.index[1:], "Cumulative_Return"] = (1 + result.Daily_Return.iloc[1:]).cumprod(skipna=False) - 1
    result["Cumulative_Return_Incomplete_Flag"] = result.Cumulative_Return.isna()
    return result


def current_positions(stocks, stock_values, closes, options, option_values):
    records = []
    for kind, qty, values in [("Security", stocks, stock_values), ("Option", options, option_values)]:
        for ticker in qty:
            quantity = qty[ticker].iloc[-1]
            if quantity == 0:
                continue
            records.append(dict(Ticker=ticker, Instrument_Type=kind, Quantity=quantity,
                                Latest_Close=closes[ticker].iloc[-1] if kind == "Security" else np.nan,
                                Current_Market_Value=values[ticker].iloc[-1]))
    return pd.DataFrame(records, columns=["Ticker", "Instrument_Type", "Quantity", "Latest_Close", "Current_Market_Value"])


def build_ledger(transaction_path, price_path, risk_free_rate=DEFAULT_RISK_FREE_RATE,
                 dividend_yields=None, default_dividend_yield=DEFAULT_DIVIDEND_YIELD,
                 include_option_details=False):
    dividend_yields = DIVIDEND_YIELDS if dividend_yields is None else dividend_yields
    if not np.isfinite(risk_free_rate) or abs(risk_free_rate) > 1:
        raise ValueError("Risk-free rate must be a finite annual decimal (4% = 0.04)")
    if any(not np.isfinite(q) or not 0 <= q <= 1 for q in [default_dividend_yield, *dividend_yields.values()]):
        raise ValueError("Dividend yields must be finite annual decimals between 0 and 1")
    issues = Issues()
    tx = classify_transactions(normalize_transactions(load_transactions(transaction_path), issues), issues)
    prices = load_prices(price_path, issues)
    calendar = build_trading_calendar(prices, tx, issues)
    tx = assign_ledger_dates(tx, calendar, issues)
    stocks = build_daily_position_matrix(tx, calendar)
    options = build_daily_position_matrix(tx, calendar, is_option=True)
    cash = reconstruct_cash(tx, calendar)
    stock_values, securities, missing, closes = value_positions(stocks, prices, issues)
    option_summary, option_values, option_daily, option_lots = handle_options(
        tx, options, prices, issues, risk_free_rate, dividend_yields, default_dividend_yield)
    master = calculate_nav(cash, securities, option_summary, missing)
    master["Security_Position_Count"] = stocks.ne(0).sum(axis=1)
    master["Option_Position_Count"] = options.ne(0).sum(axis=1)
    master["Position_Count"] = master.Security_Position_Count + master.Option_Position_Count
    run_validation_checks(master, tx, stocks, options, calendar, issues)
    master = calculate_returns(master)
    master = pd.concat([master, stocks.add_prefix("QTY_"), options.add_prefix("QTY_"), stock_values.add_prefix("MV_"), option_values.add_prefix("MV_")], axis=1)
    first = ["Cash", "Securities_Market_Value", "Options_Market_Value", "Total_NAV", "External_Flow", "Daily_Return", "Cumulative_Return"]
    master = master[first + [c for c in master if c not in first]]
    positions = current_positions(stocks, stock_values, closes, options, option_values)
    # The position summary must reconcile to the final-row component values.
    for kind, field in [("Security", "Securities_Market_Value"), ("Option", "Options_Market_Value")]:
        total = positions.loc[positions.Instrument_Type.eq(kind), "Current_Market_Value"].sum(skipna=False)
        assert np.isclose(total, master[field].iloc[-1], equal_nan=True)
    result = (master, issues.frame(), tx, positions)
    return (*result, option_daily, option_lots) if include_option_details else result


def reconciliation_report(master, issues, tx, positions):
    end = master.iloc[-1]
    def value(number, percent=False):
        if pd.isna(number):
            return "UNAVAILABLE (see reconciliation issues)"
        return f"{number:.4%}" if percent else f"{number:,.2f}"
    missing = issues[issues.Issue.eq("missing_price_while_held")]
    negative = issues[issues.Issue.eq("negative_security_quantity")]
    unexplained = issues[issues.Issue.isin(["unexplained_cash_jump", "unexplained_cash_activity"])]
    lines = [
        "PORTFOLIO RECONCILIATION (trade-date cash; USD)",
        f"Account inception (first transaction): {tx.Date.min().date()}",
        f"Daily output: {master.index[0].date()} through {master.index[-1].date()} ({len(master)} dates)",
        f"Latest transaction posting: {tx.Run_Date.max().date()}",
        f"External deposits: {value(master.External_Deposits.sum())}",
        f"External withdrawals (signed): {value(master.External_Withdrawals.sum())}",
        f"Net external contributions: {value(master.External_Flow.sum())}",
        f"Ending cash (including core cash): {value(end.Cash)}",
        f"Ending securities market value: {value(end.Securities_Market_Value)}",
        f"Ending options market value: {value(end.Options_Market_Value)}",
        f"Ending total NAV: {value(end.Total_NAV)}",
        f"Ending cumulative time-weighted return: {value(end.Cumulative_Return, True)}",
        f"Stock/ETF securities ever held: {len([c for c in master if c.startswith('QTY_') and not c.startswith('QTY_-')])}",
        f"Distinct option contracts: {len([c for c in master if c.startswith('QTY_-')])}",
        f"Current non-zero positions: {len(positions)}",
        f"Missing held prices: {len(missing)} date/ticker observations",
        f"Incomplete option pricing dates: {int(master.Option_Pricing_Incomplete_Flag.sum())}",
        f"Dates with estimated option marks: {int(master.Option_MV_Estimated_Flag.sum())}",
        f"Negative security quantities: {len(negative)} date/ticker observations",
        f"Suspicious unexplained cash events: {len(unexplained)}",
        f"Transactions not confidently classified: {int((~tx.Confident).sum())}",
        f"Net option premium cash flows (after fees): {value(master.Option_Net_Cash_Flow.sum())}",
        f"Realized net cash from fully closed option episodes: {value(master.Option_Realized_Cash_Flow.sum())}",
        f"Core bookkeeping cash adjustment: {value(master.Core_Bookkeeping_Adjustment.sum())}",
        "Quantities and cash reconcile to source transactions; no independent holdings statement supplied.",
        "First daily return is blank. Returns include labeled option model/fallback marks where applicable.",
        "\nCURRENT POSITIONS (at final price date)",
        positions.to_string(index=False),
        "\nISSUE COUNTS",
        issues.groupby(["Severity", "Issue"]).size().to_string() if len(issues) else "None",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transactions", type=Path, default=DEFAULT_TRANSACTIONS)
    parser.add_argument("--prices", type=Path, default=DEFAULT_PRICES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--risk-free-rate", type=float, default=DEFAULT_RISK_FREE_RATE, help="Annual continuously compounded decimal; default 0.04")
    parser.add_argument("--dividend-yield", type=float, default=DEFAULT_DIVIDEND_YIELD, help="Default continuous dividend yield; default 0")
    parser.add_argument("--dividend-yield-for", action="append", default=[], metavar="TICKER=RATE", help="Override underlying dividend yield; repeatable")
    args = parser.parse_args(argv)
    yields = dict(DIVIDEND_YIELDS)
    for setting in args.dividend_yield_for:
        try:
            ticker, rate = setting.split("=", 1)
            if not ticker.strip():
                raise ValueError("empty ticker")
            yields[ticker.strip().upper()] = float(rate)
        except ValueError:
            parser.error("--dividend-yield-for must be TICKER=RATE, e.g. XYZ=0.015")
    master, issues, tx, positions, option_daily, option_lots = build_ledger(
        args.transactions, args.prices, args.risk_free_rate, yields, args.dividend_yield,
        include_option_details=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    master.to_csv(args.output_dir / "master_portfolio_daily.csv", index_label="Date", date_format="%Y-%m-%d")
    issues.to_csv(args.output_dir / "portfolio_reconciliation_issues.csv", index=False, date_format="%Y-%m-%d")
    tx.to_csv(args.output_dir / "normalized_transactions.csv", index=False, date_format="%Y-%m-%d")
    positions.to_csv(args.output_dir / "current_positions.csv", index=False)
    option_daily.to_csv(args.output_dir / "master_option_daily.csv", index=False, date_format="%Y-%m-%d")
    option_lots.to_csv(args.output_dir / "option_position_ledger.csv", index=False, date_format="%Y-%m-%d")
    report = reconciliation_report(master, issues, tx, positions)
    option_report = option_reconciliation_report(option_daily, option_lots)
    (args.output_dir / "reconciliation_report.txt").write_text(report)
    (args.output_dir / "option_reconciliation_report.txt").write_text(option_report)
    print(report)
    print(option_report)
    print(f"Outputs saved to {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
