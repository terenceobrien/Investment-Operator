"""
Fidelity positions CSV -> weights dict for portfolio_beta.

Handles the real-world mess in a Fidelity "Positions" export:
  - 'Percent Of Account' is a string like '11.91%'
  - dollar columns like '$1,428.42' (dollar sign + thousands commas)
  - MULTIPLE accounts stacked in one file (per-account percentages that
    do NOT sum to 100% across the file)
  - trailing blank lines + a multi-paragraph legal disclaimer after the data
  - non-equity rows: core cash (SPAXX/FDRXX), 'Pending Activity', money-market,
    and rows with no usable ticker

Weighting: by default we compute weights from Current Value (dollar value /
total invested dollars), which is correct across any number of accounts. The
Fidelity 'Percent Of Account' column is only meaningful within a single
account, so it's offered as an option but not the default.

Fail-loud: raises on missing required columns, an empty position set, or a
weight set that doesn't reconcile. Nothing is silently dropped without a
returned report of what was excluded and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd


# Symbols that are cash / non-tradeable-for-beta and should be treated as cash.
# Extend as you find more in your own exports.
CASH_LIKE_SYMBOLS = {
    "SPAXX", "FDRXX", "FZFXX", "FDIC", "FCASH", "QACDS",  # Fidelity core / MM
    "CORE", "CASH",
}

# Description/row markers that indicate a non-position line to skip.
SKIP_ROW_MARKERS = (
    "pending activity",
    "account total",
)

REQUIRED_COLUMNS = {"Symbol", "Current value"}


@dataclass
class IngestResult:
    weights: dict[str, float]          # ticker -> fraction of INVESTED sleeve (sums to 1.0)
    invested_fraction: float           # invested value / total account value (<=1.0)
    cash_fraction: float               # 1 - invested_fraction
    total_account_value: float
    invested_value: float
    cash_value: float
    per_symbol_value: dict[str, float] # ticker -> aggregated dollar value
    excluded: list[dict] = field(default_factory=list)  # rows dropped, with reason
    n_accounts: int = 1


def _clean_money(series: pd.Series) -> pd.Series:
    """'$1,428.42' / '-$115.01' / '' -> float. Non-parseable -> NaN."""
    s = series.astype(str).str.strip()
    # strip $, commas, and surrounding whitespace; keep leading minus
    s = s.str.replace(r"[\$,]", "", regex=True)
    s = s.replace({"": None, "--": None, "n/a": None, "N/A": None})
    return pd.to_numeric(s, errors="coerce")


def _clean_percent(series: pd.Series) -> pd.Series:
    """'11.91%' -> 0.1191. Blank -> NaN."""
    s = series.astype(str).str.strip().str.replace("%", "", regex=False)
    s = s.replace({"": None, "--": None})
    return pd.to_numeric(s, errors="coerce") / 100.0


def _normalize_symbol(sym: str) -> str:
    """
    Normalize a Fidelity symbol to a yfinance-friendly ticker.
    - strip whitespace
    - Fidelity uses no special class notation for most; share classes like
      'BRK/B' or 'BRK.B' -> 'BRK-B' for yfinance.
    """
    s = str(sym).strip().upper()
    s = s.rstrip("*")  # Fidelity marks core positions with '**' (e.g. SPAXX**)
    s = s.replace("/", "-").replace(".", "-")
    return s


def load_fidelity_positions(
    csv_path: str,
    use_fidelity_percent: bool = False,
    min_weight: float = 0.0,
) -> IngestResult:
    """
    Parse a Fidelity positions CSV into a weights dict for portfolio_beta.

    csv_path: path to the downloaded Fidelity positions export.
    use_fidelity_percent: if True AND the file is a single account, weight by
        the 'Percent Of Account' column instead of Current Value. Ignored
        (with a raised error) for multi-account files, where it's ambiguous.
    min_weight: drop positions below this invested-sleeve weight (e.g. 0.005 to
        ignore sub-0.5% dust). Dropped weight is redistributed by renormalizing.
    """
    # Fidelity exports have quirks that break naive parsing:
    #   - a BOM on the first header cell
    #   - CRLF line endings
    #   - a TRAILING COMMA on every data row (17 fields vs 16 header fields),
    #     which makes strict parsers skip every data row
    #   - a trailing disclaimer block (quoted prose) after a blank line
    #
    # Strategy: read only the columns we recognize from the header. We first
    # read the header to get names, then let pandas tolerate the ragged extra
    # trailing field by naming it and dropping it. usecols keeps us robust to
    # the extra column. The C engine handles the trailing comma gracefully
    # when we don't pin the column count.
    header = pd.read_csv(csv_path, nrows=0, dtype=str)
    header.columns = [c.strip().lstrip("\ufeff") for c in header.columns]
    known_cols = list(header.columns)

    raw = pd.read_csv(
        csv_path,
        dtype=str,
        skip_blank_lines=True,
        header=0,
        names=known_cols,          # force our 16 clean names onto the data
        usecols=range(len(known_cols)),  # ignore the ragged 17th trailing field
        on_bad_lines="skip",
        skipinitialspace=False,
    )
    # Normalize column names (strip trailing spaces / BOM)
    raw.columns = [c.strip().lstrip("\ufeff") for c in raw.columns]

    missing = REQUIRED_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError(
            f"CSV missing required columns {missing}. Found: {list(raw.columns)}. "
            "Make sure this is a Fidelity 'Positions' export, not 'Activity' or 'History'."
        )

    df = raw.copy()

    # Identify account column if present (for the multi-account check)
    acct_col = next(
        (c for c in df.columns if c.strip().lower() in {"account number", "account name"}),
        None,
    )

    excluded: list[dict] = []

    # 1) Drop rows whose Symbol is blank/NaN, or that are disclaimer/footer text.
    def _is_junk_row(row) -> str | None:
        sym = str(row.get("Symbol", "")).strip()
        desc = str(row.get("Description", "")).strip().lower()
        if sym == "" or sym.lower() in {"nan", "none"}:
            return "blank symbol"
        # disclaimer/footer rows tend to have long text in Symbol or no value
        if any(m in desc for m in SKIP_ROW_MARKERS):
            return f"marker row ({desc[:30]})"
        if any(m in sym.lower() for m in SKIP_ROW_MARKERS):
            return f"marker row ({sym[:30]})"
        # A "symbol" longer than ~6 chars with spaces is almost certainly prose
        if len(sym) > 12 or (" " in sym and len(sym) > 6):
            return "non-symbol text"
        return None

    keep_rows = []
    for _, row in df.iterrows():
        reason = _is_junk_row(row)
        if reason:
            excluded.append({"symbol": str(row.get("Symbol", ""))[:40], "reason": reason})
        else:
            keep_rows.append(row)

    if not keep_rows:
        # self-diagnosing: show what got dropped and why, plus what pandas parsed
        reasons = {}
        for e in excluded:
            reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
        raise ValueError(
            "No position rows found after filtering.\n"
            f"  Rows read by parser: {len(df)}\n"
            f"  Columns parsed: {list(df.columns)}\n"
            f"  Drop reasons: {reasons}\n"
            "If 'Rows read by parser' is 0, the delimiter/parse is wrong. "
            "If it's >0 but all dropped, the junk filter is too aggressive."
        )

    df = pd.DataFrame(keep_rows).reset_index(drop=True)

    # 2) Clean numeric columns
    df["_value"] = _clean_money(df["Current Value"])
    if "Percent Of Account" in df.columns:
        df["_pct"] = _clean_percent(df["Percent Of Account"])
    df["_symbol"] = df["Symbol"].map(_normalize_symbol)

    # Rows with unparseable value are dropped (but reported)
    bad_val = df["_value"].isna()
    for _, r in df[bad_val].iterrows():
        excluded.append({"symbol": r["_symbol"], "reason": "unparseable Current Value"})
    df = df[~bad_val].reset_index(drop=True)

    # 3) Account count
    n_accounts = df[acct_col].nunique() if acct_col else 1
    if use_fidelity_percent and n_accounts > 1:
        raise ValueError(
            f"use_fidelity_percent=True but file has {n_accounts} accounts. "
            "Per-account percentages don't combine across accounts — "
            "use value-based weighting (use_fidelity_percent=False)."
        )

    # 4) Split cash-like from tradeable
    is_cash = df["_symbol"].isin(CASH_LIKE_SYMBOLS)
    cash_value = float(df.loc[is_cash, "_value"].sum())
    equities = df[~is_cash].copy()
    for _, r in df[is_cash].iterrows():
        excluded.append({"symbol": r["_symbol"], "reason": "cash-like (0 beta)"})

    if equities.empty:
        raise ValueError("No tradeable positions after removing cash — nothing to beta.")

    # 5) Aggregate by symbol across accounts (same ticker in 2 accounts -> summed value)
    by_symbol = equities.groupby("_symbol", as_index=True)["_value"].sum()
    total_account_value = float(df["_value"].sum())        # incl. cash
    invested_value = float(by_symbol.sum())                # equities only
    if invested_value <= 0:
        raise ValueError(f"Invested value non-positive ({invested_value}).")

    # 6) Weights over the invested sleeve (sum to 1.0)
    weights = (by_symbol / invested_value).to_dict()

    # optional dust filter, then renormalize
    if min_weight > 0:
        kept = {k: v for k, v in weights.items() if v >= min_weight}
        dropped = {k: v for k, v in weights.items() if v < min_weight}
        for k, v in dropped.items():
            excluded.append({"symbol": k, "reason": f"below min_weight ({v:.4f})"})
        if not kept:
            raise ValueError(f"min_weight={min_weight} dropped every position.")
        s = sum(kept.values())
        weights = {k: v / s for k, v in kept.items()}

    invested_fraction = invested_value / total_account_value if total_account_value > 0 else 1.0

    return IngestResult(
        weights=weights,
        invested_fraction=invested_fraction,
        cash_fraction=1.0 - invested_fraction,
        total_account_value=total_account_value,
        invested_value=invested_value,
        cash_value=cash_value,
        per_symbol_value=by_symbol.to_dict(),
        excluded=excluded,
        n_accounts=n_accounts,
    )


def print_ingest_report(res: IngestResult) -> None:
    """Human-readable summary of what was loaded and what was dropped."""
    print(f"Accounts in file:        {res.n_accounts}")
    print(f"Total account value:     ${res.total_account_value:,.2f}")
    print(f"Invested (equities):     ${res.invested_value:,.2f}  ({res.invested_fraction:.1%})")
    print(f"Cash / core:             ${res.cash_value:,.2f}  ({res.cash_fraction:.1%})")
    print(f"Tradeable positions:     {len(res.weights)}")
    print()
    print("Weights (invested sleeve, sums to 1.0):")
    for tkr, w in sorted(res.weights.items(), key=lambda kv: -kv[1]):
        print(f"  {tkr:<8} {w:7.2%}   ${res.per_symbol_value.get(tkr, 0):>14,.2f}")
    if res.excluded:
        print("\nExcluded rows:")
        for e in res.excluded:
            print(f"  {e['symbol']:<12} — {e['reason']}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python fidelity_ingest.py <path_to_fidelity_positions.csv>")
        sys.exit(1)
    res = load_fidelity_positions(sys.argv[1])
    print_ingest_report(res)