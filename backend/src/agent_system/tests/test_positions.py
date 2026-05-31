"""Tests for Fidelity CSV positions ingestion."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.agent_system.positions import load_latest_positions
from src.agent_system.positions import __main__ as positions_cli
from src.agent_system.positions.loader import positions_freshness_warning
from src.agent_system.positions.parser import (
    _detect_option,
    _parse_money,
    _parse_percent,
    parse_fidelity_csv,
)
from src.agent_system.positions.types import Position, PositionsSnapshot


HEADER = (
    "Account Number,Account Name,Symbol,Description,Quantity,Last Price,"
    "Last Price Change,Current Value,Today's Gain/Loss Dollar,"
    "Today's Gain/Loss Percent,Total Gain/Loss Dollar,"
    "Total Gain/Loss Percent,Percent Of Account,Cost Basis Total,"
    "Average Cost Basis,Type\n"
)


def _write_csv(path: Path, rows: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\ufeff" + HEADER + rows, encoding="utf-8")
    return path


def _fixture_csv(path: Path) -> Path:
    return _write_csv(
        path,
        (
            'Z12345678,Taxable,ETN,EATON CORP PLC,10,"$100.00","+$1.00",'
            '"$1,000.00","+$10.00",+1.00%,"+$100.00",+11.11%,50.00%,'
            '"$900.00","$90.00",Margin\n'
            'Z12345678,Taxable,SPAXX**,FIDELITY GOVERNMENT MONEY MARKET,,'
            '"$1.00","$0.00","$750.00","$0.00",0.00%,"$0.00",0.00%,'
            '37.50%,"$750.00",,Cash\n'
            'Z12345678,Taxable,AAPL230621C00175000,"CALL (AAPL) JUN 21 2026 $175",'
            '1,"$250.00","-$5.00","$250.00","-$5.00",-2.00%,"-$50.00",'
            '-16.67%,12.50%,"$300.00","$300.00",Margin\n'
            "\n"
            '"Legal disclaimer text ignored by parser"\n'
            '"Date downloaded: 05/30/2026 04:15 PM"\n'
        ),
    )


def test_parse_money():
    assert _parse_money("$1,234.56") == 1234.56
    assert _parse_money("") is None
    assert _parse_money("$0.00") == 0.0


def test_parse_percent():
    assert _parse_percent("+5.14%") == pytest.approx(0.0514)
    assert _parse_percent("-12.5%") == pytest.approx(-0.125)
    assert _parse_percent("") is None


def test_detect_option():
    assert _detect_option("PUT (MSFT) JUN 21 2026 $300")
    assert _detect_option("CALL (AAPL) JUN 21 2026 $175")
    assert not _detect_option("EATON CORP PLC")


def test_parse_fidelity_csv_fixture_rollups_and_footer(tmp_path):
    csv_path = _fixture_csv(tmp_path / "Portfolio_Positions_May-30-2026.csv")

    snapshot = parse_fidelity_csv(csv_path)

    assert len(snapshot.positions) == 3
    assert snapshot.downloaded_at == datetime(2026, 5, 30, 16, 15, tzinfo=timezone.utc)
    assert snapshot.account_number == "Z12345678"
    assert snapshot.account_name == "Taxable"
    assert snapshot.total_nav_usd == pytest.approx(2000.0)
    assert snapshot.cash_usd == pytest.approx(750.0)
    assert snapshot.cash_pct == pytest.approx(0.375)
    assert snapshot.long_equity_usd == pytest.approx(1000.0)
    assert snapshot.margin_positions_usd == pytest.approx(1250.0)
    assert snapshot.positions[1].is_cash is True
    assert snapshot.positions[1].quantity_shares is None
    assert snapshot.positions[2].is_option is True


def test_parse_money_market_only_csv(tmp_path):
    csv_path = _write_csv(
        tmp_path / "cash.csv",
        (
            'Z12345678,Taxable,SPAXX**,FIDELITY GOVERNMENT MONEY MARKET,,'
            '"$1.00","$0.00","$1,234.56","$0.00",0.00%,"$0.00",0.00%,'
            '100.00%,"$1,234.56",,Cash\n'
            "\n"
        ),
    )

    snapshot = parse_fidelity_csv(csv_path)

    assert len(snapshot.positions) == 1
    assert snapshot.cash_usd == pytest.approx(1234.56)
    assert snapshot.cash_pct == pytest.approx(1.0)
    assert snapshot.long_equity_usd == pytest.approx(0.0)


def test_parse_empty_or_malformed_csv_raises(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        parse_fidelity_csv(empty)

    malformed = tmp_path / "bad.csv"
    malformed.write_text("Wrong,Header\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected Fidelity CSV header"):
        parse_fidelity_csv(malformed)


def test_load_latest_positions_uses_most_recent_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    old_file = _fixture_csv(tmp_path / "positions" / "old.csv")
    new_file = _write_csv(
        tmp_path / "positions" / "new.csv",
        (
            'Z12345678,Taxable,NEW,NEW HOLDING,1,"$2.00","$0.00","$2.00",'
            '"$0.00",0.00%,"$0.00",0.00%,100.00%,"$2.00","$2.00",Margin\n'
        ),
    )
    old_mtime = datetime.now(timezone.utc).timestamp() - 100
    new_mtime = datetime.now(timezone.utc).timestamp()
    os.utime(old_file, (old_mtime, old_mtime))
    os.utime(new_file, (new_mtime, new_mtime))

    snapshot = load_latest_positions()

    assert snapshot is not None
    assert snapshot.positions[0].symbol == "NEW"


def test_freshness_warning_thresholds():
    position = Position(
        symbol="ETN",
        description="Eaton",
        quantity_shares=1,
        current_value_usd=100.0,
        position_type="margin",
    )
    now = datetime.now(timezone.utc)
    fresh = PositionsSnapshot(
        source_file="fresh.csv",
        file_mtime=now - timedelta(hours=12),
        positions=[position],
        total_nav_usd=100.0,
        cash_usd=0.0,
        cash_pct=0.0,
        long_equity_usd=100.0,
        margin_positions_usd=100.0,
    )
    hours_old = fresh.model_copy_validate({"file_mtime": now - timedelta(hours=36)})
    days_old = fresh.model_copy_validate({"file_mtime": now - timedelta(days=8)})

    assert positions_freshness_warning(fresh) is None
    assert "hours old" in positions_freshness_warning(hours_old)
    assert "days old" in positions_freshness_warning(days_old)


def test_positions_snapshot_model_post_init_catches_inconsistent_total():
    position = Position(
        symbol="ETN",
        description="Eaton",
        quantity_shares=1,
        current_value_usd=100.0,
        position_type="margin",
    )
    with pytest.raises(ValueError, match="does not match"):
        PositionsSnapshot(
            source_file="bad.csv",
            file_mtime=datetime.now(timezone.utc),
            positions=[position],
            total_nav_usd=99.0,
            cash_usd=0.0,
            cash_pct=0.0,
            long_equity_usd=100.0,
            margin_positions_usd=100.0,
        )


def test_positions_cli_show_persists_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    _fixture_csv(tmp_path / "positions" / "Portfolio_Positions_May-30-2026.csv")

    result = positions_cli._cmd_show(object())

    assert result == 0
    output = capsys.readouterr().out
    assert "Total NAV" in output
    rows = [
        json.loads(line)
        for line in (tmp_path / "schema_records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[0]["schema_type"] == "PositionsSnapshot"
