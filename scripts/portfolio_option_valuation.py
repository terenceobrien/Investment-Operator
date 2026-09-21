"""Transparent, causal option marks for the portfolio reconstruction.

US equity options are generally American-style; BSM is a European model.
Constant entry IV ignores volatility changes, early-exercise value, discrete
dividends and unavailable historical bid/ask spreads. These are estimated marks,
not recovered brokerage quotes. No exit price is used before its transaction date.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import math
import re
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

ZERO = Decimal("0")
SYMBOL_PATTERN = re.compile(r"^-?([A-Z0-9.]+?)(\d{6})([CP])(\d+(?:\.\d+)?)$")
MONTHS = "JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
DAILY_COLUMNS = [
    "Date", "Option_ID", "Fidelity_Symbol", "Underlying", "Expiration", "Strike",
    "Option_Type", "Contracts", "Contract_Multiplier", "Underlying_Close",
    "Time_To_Expiry_Years", "Entry_IV", "Entry_IVs", "Open_Lot_Count",
    "Risk_Free_Rate", "Dividend_Yield", "Estimated_Option_Price", "Actual_Option_Price",
    "Price_Used", "Option_Market_Value", "Valuation_Method", "Valuation_Methods", "Lot_Valuation_Detail", "Price_Source",
    "Estimation_Reason", "Last_Observed_Price_Date", "Option_Pricing_Incomplete_Flag",
]
LOT_COLUMNS = [
    "Lot_ID", "Option_ID", "Fidelity_Symbol", "Underlying", "Expiration", "Strike",
    "Option_Type", "Contract_Multiplier", "Quantity", "Remaining_Quantity",
    "Entry_Date", "Entry_Price", "Entry_Price_Source", "Entry_IV", "IV_Failure_Reason",
    "Risk_Free_Rate", "Dividend_Yield", "Close_Date", "Close_Price", "Average_Close_Price",
    "Entry_Net_Cash", "Close_Net_Cash", "Realized_Option_PnL",
    "Pre_Exit_Date", "Pre_Exit_Price_Used", "Pre_Exit_Model_Price", "Pre_Exit_Method",
    "Actual_Exit_Minus_Pre_Exit_Price", "Actual_Exit_Minus_Pre_Exit_Model_Price",
]


def black_scholes_price(spot, strike, time_to_expiry, risk_free_rate,
                       volatility, option_type, dividend_yield=0.0):
    """European BSM premium per share; rates/IV are annual decimal values."""
    s, k, t, r, sigma, q = map(float, (spot, strike, time_to_expiry,
                                     risk_free_rate, volatility, dividend_yield))
    kind = str(option_type).upper()
    if kind not in {"C", "CALL", "P", "PUT"}:
        raise ValueError("option_type must be C/call or P/put")
    if not all(math.isfinite(v) for v in (s, k, t, r, sigma, q)):
        raise ValueError("BSM inputs must be finite")
    if s < 0 or k <= 0 or sigma < 0:
        raise ValueError("Spot/volatility must be nonnegative and strike positive")
    call = kind in {"C", "CALL"}
    if t <= 0:
        return max(s-k, 0.0) if call else max(k-s, 0.0)
    discounted_s, discounted_k = s * math.exp(-q*t), k * math.exp(-r*t)
    if not math.isfinite(discounted_s) or not math.isfinite(discounted_k):
        raise ValueError("Discounted BSM inputs overflow")
    if s == 0 or sigma * math.sqrt(t) < 1e-12:
        return max(discounted_s-discounted_k, 0.0) if call else max(discounted_k-discounted_s, 0.0)
    d1 = (math.log(s/k) + (r-q+sigma*sigma/2)*t) / (sigma*math.sqrt(t))
    d2 = d1-sigma*math.sqrt(t)
    value = (discounted_s*norm.cdf(d1)-discounted_k*norm.cdf(d2) if call
             else discounted_k*norm.cdf(-d2)-discounted_s*norm.cdf(-d1))
    return max(float(value), 0.0)


def solve_implied_volatility(observed_option_price, spot, strike, time_to_expiry,
                             risk_free_rate, option_type, dividend_yield=0.0):
    """Entry IV in [0.0001, 5]. Warn and return NaN when no valid root exists."""
    try:
        price, s, k, t, r, q = map(float, (observed_option_price, spot, strike,
                                          time_to_expiry, risk_free_rate, dividend_yield))
        if not all(math.isfinite(v) for v in (price, s, k, t, r, q)):
            raise ValueError("missing/non-finite price, spot, date or rate")
        if t <= 0:
            raise ValueError("no positive time remaining at entry-date close; intraday expiry trade")
        if price < 0 or s <= 0 or k <= 0:
            raise ValueError("invalid price, spot or strike")
        kind = str(option_type).upper()
        if kind not in {"C", "CALL", "P", "PUT"}:
            raise ValueError("invalid call/put type")
        call = kind in {"C", "CALL"}
        intrinsic = max(s-k, 0.0) if call else max(k-s, 0.0)
        ds, dk = s*math.exp(-q*t), k*math.exp(-r*t)
        european_lower = max(ds-dk, 0.0) if call else max(dk-ds, 0.0)
        upper = ds if call else dk
        # American-style trades below intrinsic at the EOD spot often reflect
        # intraday timing. Do not force a spurious IV to match inconsistent inputs.
        tolerance = 1e-8
        if price < max(intrinsic, european_lower)-tolerance or price > upper+tolerance:
            raise ValueError("observed premium violates intrinsic/BSM price bounds at entry Close")
        def objective(sigma):
            return black_scholes_price(s, k, t, r, sigma, kind, q)-price
        low, high = objective(.0001), objective(5.0)
        if abs(low) <= tolerance:
            return .0001
        if abs(high) <= tolerance:
            return 5.0
        if low * high > 0:
            raise ValueError("entry IV is outside [0.0001, 5.0]")
        return float(brentq(objective, .0001, 5.0, xtol=1e-12))
    except (ValueError, TypeError, OverflowError, RuntimeError) as exc:
        warnings.warn(f"Entry IV unavailable: {exc}; use observed-price fallback", RuntimeWarning, stacklevel=2)
        return np.nan


def parse_option_contract(symbol, description="", action=""):
    """Parse Fidelity -BABA260807C120 and CALL/PUT description fallbacks.

    Fidelity's strike suffix is a literal dollar strike, NOT OCC's /1000 field.
    Unparseable contracts keep a stable symbol ID and can still be carried at cost.
    """
    symbol = str(symbol).strip().upper()
    text = f"{description} {action}".upper()
    match = re.search(r"\((\d+)\s+SHS\)", text)
    multiplier = int(match[1]) if match else 100
    if multiplier <= 0:
        raise ValueError(f"Invalid option multiplier for {symbol}")
    metadata = dict(Option_ID=f"UNPARSED:{symbol}", Fidelity_Symbol=symbol,
                    Underlying="", Expiration=pd.NaT, Strike=np.nan, Option_Type="",
                    Contract_Multiplier=multiplier, Parse_Error="", Multiplier_Assumed=match is None)
    symbol_match = SYMBOL_PATTERN.fullmatch(symbol)
    error = ""
    if symbol_match:
        try:
            underlying, date_code, kind, strike_text = symbol_match.groups()
            expiration = pd.Timestamp(datetime.strptime(date_code, "%y%m%d"))
            strike = float(strike_text)
            if strike <= 0:
                raise ValueError("non-positive strike")
        except ValueError as exc:
            error = str(exc)
            symbol_match = None
    if not symbol_match:
        kind_match = re.search(r"\b(CALL|PUT)\s*\(([A-Z0-9.]+)\)", text)
        date_match = re.search(rf"({MONTHS})\s+(\d{{1,2}})\s+(\d{{2}}|\d{{4}})\b", text)
        strike_match = re.search(r"\$([\d,]+(?:\.\d+)?)", text)
        try:
            if not (kind_match and date_match and strike_match):
                raise ValueError(error or "could not parse underlying, expiry, strike and call/put")
            kind, underlying = kind_match[1][0], kind_match[2]
            fmt = "%b %d %y" if len(date_match[3]) == 2 else "%b %d %Y"
            expiration = pd.Timestamp(datetime.strptime(" ".join(date_match.groups()), fmt))
            strike = float(strike_match[1].replace(",", ""))
            if strike <= 0:
                raise ValueError("non-positive strike")
        except ValueError as exc:
            metadata["Parse_Error"] = str(exc)
            return metadata
    metadata.update(Underlying=underlying, Expiration=expiration, Strike=strike,
                    Option_Type=kind, Option_ID=f"{underlying}_{expiration:%Y-%m-%d}_{kind}_{strike:g}")
    return metadata


def _spot(closes, day, underlying):
    if underlying in closes and day in closes.index:
        return float(closes.at[day, underlying])
    return np.nan


def _time(day, expiration):
    return (expiration-day).days/365.0 if pd.notna(expiration) else np.nan


def build_option_position_ledger(transactions, prices, issues, risk_free_rate,
                                dividend_yields=None, default_dividend_yield=0.0):
    """Normalize events; no future prices or close dates enter opening valuation."""
    yields = dividend_yields or {}
    closes = prices.pivot(index="Date", columns="Ticker", values="Close")
    records = []
    selected = transactions[transactions.Is_Option & transactions.Ledger_Date.notna()]
    for row in selected.itertuples():
        meta = parse_option_contract(row.Ticker, row.Description, row.Action)
        day = row.Ledger_Date
        if meta["Parse_Error"]:
            issues.add("option_contract_parse_fallback", meta["Parse_Error"], day, row.Ticker, row.Source_Row)
        kind = row.Action.upper()
        direction = "open" if "OPENING TRANSACTION" in kind else "close" if "CLOSING TRANSACTION" in kind else "auto"
        closing_method = ""
        if row.Category == "option_expiration":
            direction, closing_method = "close", "expiration_intrinsic"
        elif row.Category == "option_exercise_assignment":
            direction, closing_method = "close", "exercise_or_assignment"
        price, source = np.nan, ""
        if closing_method:
            # Exercise rows may report the STRIKE in Price, not the option quote.
            # Only explicit cash settlement on the option leg is an option premium.
            if row.Quantity_Delta != 0:
                price = abs(float(row.Amount+row.Fees)/float(row.Quantity_Delta)/meta["Contract_Multiplier"])
                source = "recorded_settlement" if row.Amount != 0 else "explicit_zero_cash_close"
        elif row.Price is not None and pd.notna(row.Price) and row.Price >= 0:
            price, source = float(row.Price), "transaction_price"
        elif row.Quantity_Delta != 0:
            price = abs(float(row.Amount+row.Fees)/float(row.Quantity_Delta)/meta["Contract_Multiplier"])
            source = "derived_from_net_cash_and_fees"
            issues.add("option_price_derived_from_cash", "Missing premium field; recovered gross per-share premium from signed net amount and fees", day, row.Ticker, row.Source_Row)
        q = float(yields.get(meta["Underlying"], default_dividend_yield))
        records.append({**meta, "Date": day, "Transaction_Date": row.Date,
                        "Source_Row": row.Source_Row, "Direction": direction,
                        "Closing_Method": closing_method, "Quantity_Delta": row.Quantity_Delta,
                        "Actual_Price": price, "Price_Source": source,
                        "Cash_Cents": row.Cash_Cents, "Entry_Spot": _spot(closes, row.Date, meta["Underlying"]),
                        "Risk_Free_Rate": float(risk_free_rate), "Dividend_Yield": q})
    return pd.DataFrame(records)


def _entry_iv(event, issues):
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always", RuntimeWarning)
        iv = solve_implied_volatility(event["Actual_Price"], event["Entry_Spot"], event["Strike"],
                                      _time(event["Transaction_Date"], event["Expiration"]),
                                      event["Risk_Free_Rate"], event["Option_Type"], event["Dividend_Yield"])
    reason = "; ".join(str(w.message) for w in captured)
    if not np.isfinite(iv):
        reason = event["Parse_Error"] or reason or "IV could not be solved"
        issues.add("option_entry_iv_unavailable", reason, event["Date"], event["Fidelity_Symbol"], event["Source_Row"])
    return iv, reason


def _new_lot(event, quantity, cash, lot_number, issues):
    iv, reason = _entry_iv(event, issues)
    return dict(Lot_ID=f"{event['Option_ID']}:{lot_number}", Option_ID=event["Option_ID"],
                Fidelity_Symbol=event["Fidelity_Symbol"], Underlying=event["Underlying"],
                Expiration=event["Expiration"], Strike=event["Strike"], Option_Type=event["Option_Type"],
                Contract_Multiplier=event["Contract_Multiplier"], Quantity=quantity,
                Remaining_Quantity=quantity, Entry_Date=event["Transaction_Date"],
                Entry_Price=event["Actual_Price"], Entry_Price_Source=event["Price_Source"],
                Entry_IV=iv, IV_Failure_Reason=reason, Risk_Free_Rate=event["Risk_Free_Rate"],
                Dividend_Yield=event["Dividend_Yield"], Close_Date=pd.NaT, Close_Price=np.nan,
                Average_Close_Price=np.nan, Entry_Net_Cash=cash, Close_Net_Cash=ZERO,
                Realized_Option_PnL=np.nan, Closed_Quantity=ZERO, Close_Premium_Notional=0.0)


def _apply_event(event, lots, issues):
    """FIFO is used for model-lot tracking, not tax cost basis."""
    delta = event["Quantity_Delta"]
    if delta == 0:
        return
    remaining = delta
    event_cash = Decimal(int(event["Cash_Cents"]))/100
    for lot in lots:
        qty = lot["Remaining_Quantity"]
        if qty == 0 or qty*remaining >= 0:
            continue
        if event["Direction"] == "open":
            issues.add("opposing_option_opening", "Opening transaction offsets existing opposite contracts; netted FIFO, verify event order", event["Date"], event["Fidelity_Symbol"], event["Source_Row"], blocks=True)
        matched = min(abs(qty), abs(remaining))
        lot["Remaining_Quantity"] += matched if qty < 0 else -matched
        remaining += matched if remaining < 0 else -matched
        lot["Close_Net_Cash"] += event_cash * matched/abs(delta)
        lot["Closed_Quantity"] += matched
        lot["Close_Premium_Notional"] += event["Actual_Price"]*float(matched)
        lot["Close_Price"] = event["Actual_Price"]
        lot["Average_Close_Price"] = lot["Close_Premium_Notional"]/float(lot["Closed_Quantity"])
        if lot["Remaining_Quantity"] == 0:
            lot["Close_Date"] = event["Date"]
            lot["Realized_Option_PnL"] = float(lot["Entry_Net_Cash"]+lot["Close_Net_Cash"])
        if remaining == 0:
            break
    if remaining:
        if event["Direction"] == "close":
            issues.add("option_close_without_open", "Closing quantity exceeds known opposing contracts; source history needs review", event["Date"], event["Fidelity_Symbol"], event["Source_Row"], blocks=True)
        lots.append(_new_lot(event, remaining, event_cash*abs(remaining)/abs(delta), len(lots)+1, issues))


def _observed_price(events):
    """No execution timestamps: use closing-fill VWAP, else opening-fill VWAP.

    An EOD position of zero never retains a quote as a portfolio asset.
    """
    available = [e for e in events if np.isfinite(e["Actual_Price"]) and e["Quantity_Delta"] != 0]
    if not available:
        return np.nan, "", ""
    closing = [e for e in available if e["Direction"] == "close"]
    chosen = closing or available
    weights = [float(abs(e["Quantity_Delta"])) for e in chosen]
    price = float(np.average([e["Actual_Price"] for e in chosen], weights=weights))
    methods = {e["Closing_Method"] or "actual_transaction" for e in chosen}
    sources = {e["Price_Source"] for e in chosen}
    return price, next(iter(methods)) if len(methods) == 1 else "mixed", ";".join(sorted(sources))


def estimate_daily_option_values(events, quantities, prices, issues):
    """Walk forward by contract, with independently frozen IV for each entry lot."""
    values = pd.DataFrame(0.0, index=quantities.index, columns=quantities.columns)
    closes = prices.pivot(index="Date", columns="Ticker", values="Close")
    daily_records, lot_records = [], []
    if events.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS), values, pd.DataFrame(columns=LOT_COLUMNS)
    for symbol, group in events.groupby("Fidelity_Symbol", sort=True):
        lots, last_actual, last_actual_date = [], np.nan, pd.NaT
        by_day = {day: rows.to_dict("records") for day, rows in group.groupby("Date")}
        contract_records = []
        meta = None
        for day in quantities.index:
            day_events = by_day.get(day, [])
            # Fidelity gives dates but no times. Explicit opening fills precede
            # closing fills within a day; preserve source order within each group.
            day_events.sort(key=lambda e: ({"open": 0, "auto": 1, "close": 2}[e["Direction"]], e["Source_Row"]))
            if day_events:
                if meta is None:
                    meta = day_events[0]
                for event in day_events:
                    if (event["Option_ID"], event["Contract_Multiplier"]) != (meta["Option_ID"], meta["Contract_Multiplier"]):
                        raise ValueError(f"Conflicting contract metadata for {symbol} on {day.date()}")
                    _apply_event(event, lots, issues)
            active = [lot for lot in lots if lot["Remaining_Quantity"] != 0]
            quantity = sum((lot["Remaining_Quantity"] for lot in active), ZERO)
            expected = quantities.at[day, symbol] if symbol in quantities else 0.0
            if not np.isclose(float(quantity), expected, atol=1e-10, rtol=0):
                raise AssertionError(f"Option lot ledger != position ledger: {symbol} {day}")
            if not active and not day_events:
                continue
            actual, actual_method, source = _observed_price(day_events)
            if np.isfinite(actual):
                last_actual, last_actual_date = actual, day
            spot = _spot(closes, day, meta["Underlying"])
            t = _time(day, meta["Expiration"])
            model_prices, used_prices, methods, reasons, weights = [], [], [], [], []
            for lot in active:
                model = np.nan
                reason = ""
                try:
                    if not np.isfinite(spot) or not np.isfinite(t):
                        raise ValueError("missing underlying Close or valid expiry")
                    if t <= 0:
                        model = black_scholes_price(spot, lot["Strike"], t, lot["Risk_Free_Rate"], 0, lot["Option_Type"], lot["Dividend_Yield"])
                        method = "expiration_intrinsic"
                    elif np.isfinite(lot["Entry_IV"]):
                        model = black_scholes_price(spot, lot["Strike"], t, lot["Risk_Free_Rate"], lot["Entry_IV"], lot["Option_Type"], lot["Dividend_Yield"])
                        method = "black_scholes_constant_iv"
                    else:
                        raise ValueError(lot["IV_Failure_Reason"] or "entry IV unavailable")
                except (ValueError, OverflowError, TypeError) as exc:
                    method, reason = "carry_last_actual_price", str(exc)
                if np.isfinite(actual):
                    used, method = actual, actual_method
                elif np.isfinite(model):
                    used = model
                else:
                    used = last_actual if np.isfinite(last_actual) else lot["Entry_Price"]
                    if not np.isfinite(used):
                        raise ValueError(f"No observed premium or entry cash to value {symbol} on {day.date()}")
                model_prices.append(model)
                used_prices.append(used)
                methods.append(method)
                weights.append(float(abs(lot["Remaining_Quantity"])))
                if reason and method == "carry_last_actual_price":
                    reasons.append(reason)
            if active:
                mark = float(np.average(used_prices, weights=weights))
                modeled = float(np.average(model_prices, weights=weights)) if all(np.isfinite(model_prices)) else np.nan
                method = methods[0] if len(set(methods)) == 1 else "mixed"
                mv = sum(float(lot["Remaining_Quantity"])*price*lot["Contract_Multiplier"] for lot, price in zip(active, used_prices))
            else:
                # Actual closing price is visible in the audit row, but NO asset
                # remains. Its net proceeds are already in cash exactly once.
                mark, modeled, method, mv = actual, np.nan, actual_method or "none", 0.0
            if symbol in values:
                values.at[day, symbol] = mv
            if "carry_last_actual_price" in methods:
                issues.add("option_carry_price_fallback", "; ".join(sorted(set(reasons))), day, symbol)
            elif "black_scholes_constant_iv" in methods:
                issues.add("option_model_estimate", "Estimated with fixed entry IV; not an observed closing quote", day, symbol, severity="info")
            display_lots = active or [lot for lot in lots if lot["Close_Date"] == day]
            ivs = [lot["Entry_IV"] for lot in display_lots]
            # A weighted IV is NOT used to reprice combined lots (BSM is nonlinear).
            # Leave aggregate Entry_IV blank when lots differ; expose all IVs.
            common_iv = ivs[0] if ivs and all(np.isfinite(v) and abs(v-ivs[0]) < 1e-12 for v in ivs) else np.nan
            contract_records.append(dict(Date=day, Option_ID=meta["Option_ID"], Fidelity_Symbol=symbol,
                Underlying=meta["Underlying"], Expiration=meta["Expiration"], Strike=meta["Strike"],
                Option_Type=meta["Option_Type"], Contracts=float(quantity), Contract_Multiplier=meta["Contract_Multiplier"],
                Underlying_Close=spot, Time_To_Expiry_Years=max(t, 0.0) if np.isfinite(t) else np.nan,
                Entry_IV=common_iv, Entry_IVs=";".join(f"{lot['Lot_ID']}={lot['Entry_IV']:.10g}" for lot in display_lots),
                Open_Lot_Count=len(active), Risk_Free_Rate=meta["Risk_Free_Rate"], Dividend_Yield=meta["Dividend_Yield"],
                Estimated_Option_Price=modeled, Actual_Option_Price=actual, Price_Used=mark,
                Option_Market_Value=mv, Valuation_Method=method,
                Valuation_Methods=";".join(sorted(set(methods))) if active else method,
                Lot_Valuation_Detail=";".join(f"{lot['Lot_ID']}|{lot_method}|{price:.10g}" for lot, lot_method, price in zip(active, methods, used_prices)),
                Price_Source=source if np.isfinite(actual) else method,
                Estimation_Reason="; ".join(sorted(set(reasons))), Last_Observed_Price_Date=last_actual_date,
                Option_Pricing_Incomplete_Flag=not np.isfinite(mv)))
        # Reconciliation uses the already-generated causal path. It can compare to
        # exit prices here, but never feeds that comparison back into prior marks.
        for lot in lots:
            record = {key: lot.get(key, np.nan) for key in LOT_COLUMNS}
            prior = [row for row in contract_records if pd.notna(lot["Close_Date"]) and lot["Entry_Date"] <= row["Date"] < lot["Close_Date"] and row["Contracts"] != 0]
            if prior:
                previous = prior[-1]
                model = np.nan
                try:
                    model = black_scholes_price(previous["Underlying_Close"], lot["Strike"], _time(previous["Date"], lot["Expiration"]), lot["Risk_Free_Rate"], lot["Entry_IV"], lot["Option_Type"], lot["Dividend_Yield"])
                except (ValueError, OverflowError, TypeError):
                    pass
                record.update(Pre_Exit_Date=previous["Date"], Pre_Exit_Price_Used=previous["Price_Used"],
                              Pre_Exit_Model_Price=model, Pre_Exit_Method=previous["Valuation_Method"],
                              Actual_Exit_Minus_Pre_Exit_Price=lot["Close_Price"]-previous["Price_Used"],
                              Actual_Exit_Minus_Pre_Exit_Model_Price=lot["Close_Price"]-model)
            lot_records.append(record)
        daily_records.extend(contract_records)
    daily = pd.DataFrame(daily_records, columns=DAILY_COLUMNS).sort_values(["Date", "Option_ID"]).reset_index(drop=True)
    if daily.duplicated(["Date", "Option_ID"]).any():
        raise ValueError("Multiple Fidelity symbols map to the same Option_ID/date; normalize aliases before valuation")
    return daily, values, pd.DataFrame(lot_records, columns=LOT_COLUMNS)


def option_reconciliation_report(daily, lots):
    modeled = daily.Valuation_Methods.str.contains("black_scholes_constant_iv", regex=False, na=False)
    fallback = daily.Valuation_Methods.str.contains("carry_last_actual_price", regex=False, na=False)
    lines = ["OPTION VALUATION RECONCILIATION (premiums per share; P&L after recorded fees)",
             f"Opening lots processed: {len(lots)}",
             f"Distinct option contracts: {daily.Option_ID.nunique()}",
             f"Opening lots successfully assigned entry IV: {int(lots.Entry_IV.notna().sum())}",
             f"Opening lots without usable entry IV: {int(lots.Entry_IV.isna().sum())}",
             f"Contracts requiring carry-price fallback: {daily.loc[fallback, 'Option_ID'].nunique()}",
             f"Option-days using Black-Scholes: {int(modeled.sum())}",
             f"Option-days using carry-price fallback: {int(fallback.sum())}",
             f"Option-days using mixed lot methods: {int(daily.Valuation_Method.eq('mixed').sum())}",
             "Intraday round trips may have no solvable expiry-day IV; actual cash/closing prices still reconcile.",
             "Model assumptions: European BSM, constant entry IV, no historical bid/ask spread or early-exercise premium."]
    def fmt(value):
        return f"{float(value):.6f}" if pd.notna(value) else "not available"
    for lot in lots[lots.Close_Date.notna()].itertuples():
        lines.extend([f"\nOption: {lot.Option_ID} | lot {lot.Lot_ID}",
                      f"Entry date: {lot.Entry_Date.date()} | contracts: {lot.Quantity} | actual premium: {fmt(lot.Entry_Price)}",
                      f"Solved entry IV: {fmt(lot.Entry_IV)}",
                      f"Close date: {lot.Close_Date.date()} | final actual premium: {fmt(lot.Close_Price)} | all-close VWAP: {fmt(lot.Average_Close_Price)}",
                      f"Model on preceding held EOD: {fmt(lot.Pre_Exit_Model_Price)} | price used: {fmt(lot.Pre_Exit_Price_Used)}",
                      f"Actual exit minus preceding model (per share): {fmt(lot.Actual_Exit_Minus_Pre_Exit_Model_Price)}",
                      f"Realized option net cash P&L: {fmt(lot.Realized_Option_PnL)}"])
    baba = daily[daily.Underlying.eq("BABA")]
    lines.append("\nBABA DAILY PATH (includes entry and zero-position exit date)")
    lines.append(baba[["Date", "Option_ID", "Contracts", "Underlying_Close", "Entry_IV", "Estimated_Option_Price", "Actual_Option_Price", "Price_Used", "Option_Market_Value", "Valuation_Method"]].to_string(index=False))
    return "\n".join(lines)+"\n"
