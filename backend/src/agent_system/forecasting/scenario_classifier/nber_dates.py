"""Quarterly NBER business-cycle reference dates.

The constants in this module are based on NBER business cycle dating, expressed
at quarterly frequency for the scenario-classifier analogue diagnostics.
Recession-quarter sets are peak-to-trough inclusive of the trough quarter.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd


class NBERDateError(RuntimeError):
    """Raised when NBER-date calculations would hide unknown future history."""


NBER_PEAKS: tuple[pd.Period, ...] = tuple(
    pd.Period(value, freq="Q")
    for value in (
        "1969Q4",
        "1973Q4",
        "1980Q1",
        "1981Q3",
        "1990Q3",
        "2001Q1",
        "2007Q4",
        "2019Q4",
    )
)

NBER_RECESSION_RANGES: tuple[tuple[pd.Period, pd.Period], ...] = tuple(
    (pd.Period(start, freq="Q"), pd.Period(end, freq="Q"))
    for start, end in (
        ("1969Q4", "1970Q4"),
        ("1973Q4", "1975Q1"),
        ("1980Q1", "1980Q3"),
        ("1981Q3", "1982Q4"),
        ("1990Q3", "1991Q1"),
        ("2001Q1", "2001Q4"),
        ("2007Q4", "2009Q2"),
        ("2019Q4", "2020Q2"),
    )
)

NBER_RECESSION_QUARTERS: frozenset[pd.Period] = frozenset(
    quarter
    for start, end in NBER_RECESSION_RANGES
    for quarter in pd.period_range(start, end, freq="Q")
)

EXOGENOUS_PEAKS: frozenset[pd.Period] = frozenset({pd.Period("2019Q4", freq="Q")})


def pre_crisis_quarters(
    lead_min: int = 1,
    lead_max: int = 4,
    *,
    exclude_exogenous: bool = True,
) -> set[pd.Period]:
    """Return quarters in [peak - lead_max, peak - lead_min] for each NBER peak."""

    min_lead = _validate_positive_int(lead_min, "lead_min")
    max_lead = _validate_positive_int(lead_max, "lead_max")
    if max_lead < min_lead:
        raise NBERDateError(
            f"lead_max must be greater than or equal to lead_min; got {lead_max} < {lead_min}"
        )

    dates: set[pd.Period] = set()
    for peak in NBER_PEAKS:
        if exclude_exogenous and peak in EXOGENOUS_PEAKS:
            continue
        for lead in range(min_lead, max_lead + 1):
            dates.add(peak - lead)
    return dates


def exogenous_cycle_quarters(
    lead_min: int = 1,
    lead_max: int = 4,
) -> set[pd.Period]:
    """Return pre-window plus recession quarters for exogenous NBER cycles."""

    min_lead = _validate_positive_int(lead_min, "lead_min")
    max_lead = _validate_positive_int(lead_max, "lead_max")
    if max_lead < min_lead:
        raise NBERDateError(
            f"lead_max must be greater than or equal to lead_min; got {lead_max} < {lead_min}"
        )
    dates: set[pd.Period] = set()
    for peak in EXOGENOUS_PEAKS:
        for lead in range(min_lead, max_lead + 1):
            dates.add(peak - lead)
        for start, end in NBER_RECESSION_RANGES:
            if start == peak:
                dates.update(pd.period_range(start, end, freq="Q"))
    return dates


def recession_within(
    quarter: pd.Period | str,
    horizon_quarters: int,
    *,
    max_known_quarter: pd.Period | str | None = None,
) -> bool:
    """Return True if any quarter in (quarter, quarter + horizon] is recessionary."""

    start = parse_quarter(quarter)
    horizon = _validate_positive_int(horizon_quarters, "horizon_quarters")
    end = start + horizon
    if max_known_quarter is not None:
        max_known = parse_quarter(max_known_quarter)
        if end > max_known:
            raise NBERDateError(
                f"Cannot evaluate recession_within({start}, {horizon}); "
                f"future window ends at {end}, beyond max_known_quarter={max_known}"
            )
    forward_window = pd.period_range(start + 1, end, freq="Q")
    return any(quarter in NBER_RECESSION_QUARTERS for quarter in forward_window)


def parse_quarter(value: pd.Period | str) -> pd.Period:
    if isinstance(value, pd.Period):
        return value.asfreq("Q")
    text = str(value).strip().upper()
    if not text:
        raise NBERDateError("empty quarter value")
    try:
        return pd.Period(text, freq="Q")
    except Exception:
        try:
            return pd.Timestamp(text).to_period("Q")
        except Exception as exc:
            raise NBERDateError(f"Could not parse quarter: {value!r}") from exc


def quarter_strings(quarters: Iterable[pd.Period]) -> tuple[str, ...]:
    return tuple(str(quarter) for quarter in sorted(quarters))


def _validate_positive_int(value: int, name: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise NBERDateError(f"{name} must be an integer; got {value!r}") from exc
    if integer < 1:
        raise NBERDateError(f"{name} must be at least 1; got {value!r}")
    return integer
