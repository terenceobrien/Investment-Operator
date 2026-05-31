"""Fidelity CSV parser for brokerage positions."""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from src.agent_system.positions.types import Position, PositionsSnapshot


EXPECTED_COLUMNS = [
    "Account Number",
    "Account Name",
    "Symbol",
    "Description",
    "Quantity",
    "Last Price",
    "Last Price Change",
    "Current Value",
    "Today's Gain/Loss Dollar",
    "Today's Gain/Loss Percent",
    "Total Gain/Loss Dollar",
    "Total Gain/Loss Percent",
    "Percent Of Account",
    "Cost Basis Total",
    "Average Cost Basis",
    "Type",
]

_ACCOUNT_RE = re.compile(r"^[A-Za-z]+\d+$")
_OPTION_WORD_RE = re.compile(r"\b(CALL|PUT)\b", re.IGNORECASE)
_OPTION_SHAPE_RE = re.compile(r"\b(20\d{2})\b.*\$\d+(?:\.\d+)?", re.IGNORECASE)


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"N/A", "--"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace("$", "").replace(",", "").replace("%", "").replace("+", "")
    text = text.strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return -parsed if negative else parsed


def _parse_money(value: str) -> float | None:
    """Parse "$1,234.56" -> 1234.56. Returns None for empty/unparseable."""
    return _parse_number(value)


def _parse_percent(value: str) -> float | None:
    """Parse "+5.14%" -> 0.0514. Returns None for empty/unparseable."""
    parsed = _parse_number(value)
    if parsed is None:
        return None
    return parsed / 100.0


def _parse_quantity(value: str | None) -> float | None:
    return _parse_number(value)


def _detect_option(description: str) -> bool:
    """Heuristic: True if description looks like an open option contract."""
    text = (description or "").strip()
    if not text:
        return False
    if _OPTION_WORD_RE.search(text):
        return True
    return bool(_OPTION_SHAPE_RE.search(text))


def _parse_downloaded_at(rows: list[list[str]]) -> datetime | None:
    for row in rows:
        text = " ".join(cell.strip().strip('"') for cell in row if cell.strip())
        if "date downloaded" not in text.lower():
            continue
        candidate = re.sub(r"(?i).*date downloaded\s*:?\s*", "", text).strip(" ,")
        candidate = re.sub(r"(?i)^downloaded\s*", "", candidate).strip(" ,")
        for fmt in (
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%B %d, %Y",
            "%b %d, %Y",
        ):
            try:
                parsed = datetime.strptime(candidate, fmt)
            except ValueError:
                continue
            return parsed.replace(tzinfo=timezone.utc)
    return None


def _normalize_row(header: list[str], row: list[str]) -> dict[str, str]:
    padded = list(row) + [""] * max(0, len(header) - len(row))
    return {column: padded[idx].strip() for idx, column in enumerate(header)}


def _position_from_row(row: dict[str, str]) -> Position:
    symbol = row["Symbol"].strip()
    description = row["Description"].strip()
    type_raw = row["Type"].strip()
    position_type = type_raw.lower()
    if position_type not in {"cash", "margin"}:
        raise ValueError(f"Unsupported Fidelity Type value {type_raw!r} for {symbol}")

    current_value = _parse_money(row["Current Value"])
    if current_value is None:
        raise ValueError(f"Current Value is missing or invalid for {symbol}")

    is_cash = position_type == "cash" or symbol.endswith("**")
    return Position(
        symbol=symbol,
        description=description,
        quantity_shares=_parse_quantity(row["Quantity"]),
        current_value_usd=current_value,
        last_price_usd=_parse_money(row["Last Price"]),
        cost_basis_total_usd=_parse_money(row["Cost Basis Total"]),
        average_cost_basis_usd=_parse_money(row["Average Cost Basis"]),
        total_gain_loss_usd=_parse_money(row["Total Gain/Loss Dollar"]),
        total_gain_loss_pct=_parse_percent(row["Total Gain/Loss Percent"]),
        percent_of_account=_parse_percent(row["Percent Of Account"]),
        position_type=position_type,
        is_cash=is_cash,
        is_option=_detect_option(description),
    )


def parse_fidelity_csv(csv_path: Path) -> PositionsSnapshot:
    """
    Parse a Fidelity portfolio CSV export into a PositionsSnapshot.

    Stops at the first blank row after the header. Footer/legal rows are
    ignored except for best-effort parsing of the Date downloaded line.
    """
    path = Path(csv_path)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
    except OSError as exc:
        raise ValueError(f"Could not read Fidelity positions CSV {path}: {exc}") from exc

    if not rows:
        raise ValueError(f"Fidelity positions CSV is empty: {path}")

    header = [cell.strip() for cell in rows[0]]
    if header != EXPECTED_COLUMNS:
        raise ValueError(
            "Unexpected Fidelity CSV header. Expected exact columns "
            f"{EXPECTED_COLUMNS!r}, got {header!r}"
        )

    data_rows: list[dict[str, str]] = []
    footer_rows: list[list[str]] = []
    for idx, raw_row in enumerate(rows[1:], start=1):
        if all(not cell.strip() for cell in raw_row):
            footer_rows = rows[idx + 1 :]
            break
        row = _normalize_row(header, raw_row)
        account_number = row["Account Number"].strip()
        if not _ACCOUNT_RE.match(account_number):
            footer_rows = rows[idx:]
            break
        data_rows.append(row)

    if not data_rows:
        raise ValueError(f"No valid Fidelity position rows found in {path}")

    positions = [_position_from_row(row) for row in data_rows]
    account_source = next(
        (row for row, position in zip(data_rows, positions) if not position.is_cash),
        data_rows[0],
    )
    total_nav = sum(position.current_value_usd for position in positions)
    cash_usd = sum(position.current_value_usd for position in positions if position.is_cash)
    long_equity_usd = sum(
        position.current_value_usd
        for position in positions
        if not position.is_cash and not position.is_option
    )
    margin_positions_usd = sum(
        position.current_value_usd
        for position in positions
        if position.position_type == "margin"
    )
    file_mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    return PositionsSnapshot(
        source_file=str(path),
        downloaded_at=_parse_downloaded_at(footer_rows),
        file_mtime=file_mtime,
        account_number=account_source["Account Number"] or None,
        account_name=account_source["Account Name"] or None,
        positions=positions,
        total_nav_usd=total_nav,
        cash_usd=cash_usd,
        cash_pct=(cash_usd / total_nav) if total_nav else 0.0,
        long_equity_usd=long_equity_usd,
        margin_positions_usd=margin_positions_usd,
    )
