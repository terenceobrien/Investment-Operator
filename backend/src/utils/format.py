from __future__ import annotations

from typing import Callable

import math


def _is_number(x) -> bool:
    try:
        return x is not None and isinstance(x, (int, float)) and not math.isnan(float(x))
    except Exception:
        return False


def fmt_number(x, decimals: int = 2, default: str = "—") -> str:
    """
    Accounting-style number formatting:
      1000 -> "1,000.00"
      -1000 -> "(1,000.00)"
    """
    if not _is_number(x):
        return default
    v = float(x)
    s = f"{abs(v):,.{decimals}f}"
    return f"({s})" if v < 0 else s


def fmt_pct(x, decimals: int = 2, default: str = "—") -> str:
    """
    Accounting-style percent formatting (expects percent units, e.g. 1.2 => 1.20%).
    """
    if not _is_number(x):
        return default
    v = float(x)
    s = f"{abs(v):,.{decimals}f}%"
    return f"({s})" if v < 0 else s


def fmt_pct_ratio(x, decimals: int = 1, default: str = "—") -> str:
    """
    Accounting-style percent formatting for ratios (0.12 => 12.0%).
    """
    if not _is_number(x):
        return default
    return fmt_pct(float(x) * 100.0, decimals=decimals, default=default)


def make_number_formatter(decimals: int = 2) -> Callable:
    return lambda v: fmt_number(v, decimals=decimals)


def make_pct_formatter(decimals: int = 2) -> Callable:
    return lambda v: fmt_pct(v, decimals=decimals)


def make_pct_ratio_formatter(decimals: int = 1) -> Callable:
    return lambda v: fmt_pct_ratio(v, decimals=decimals)


def format_df_accounting(
    df,
    *,
    pct_cols: list[str] | None = None,
    pct_ratio_cols: list[str] | None = None,
    num_cols: list[str] | None = None,
    pct_decimals: int = 2,
    pct_ratio_decimals: int = 1,
    num_decimals: int = 2,
):
    """
    Return a Styler with accounting formatting applied to selected columns.
    """
    pct_cols = [c for c in (pct_cols or []) if c in df.columns]
    pct_ratio_cols = [c for c in (pct_ratio_cols or []) if c in df.columns]
    num_cols = [c for c in (num_cols or []) if c in df.columns]

    fmt = {}
    for c in pct_cols:
        fmt[c] = make_pct_formatter(decimals=pct_decimals)
    for c in pct_ratio_cols:
        fmt[c] = make_pct_ratio_formatter(decimals=pct_ratio_decimals)
    for c in num_cols:
        fmt[c] = make_number_formatter(decimals=num_decimals)

    return df.style.format(fmt)
