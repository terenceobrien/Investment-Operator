"""Calibrate scenario return CSVs from representative historical date baskets."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.agent_system.services.calibration_utils import (
    HORIZON_DAYS,
    MARKET_COLUMNS,
    THEME_COLUMNS,
    calibrated_row,
    confirm_apply,
    load_json,
    load_csv_rows,
    old_market_values,
    old_theme_values,
    print_comparison,
    print_summary,
    single_ticker_distribution,
    write_csv,
)
from src.agent_system.services.scenario_translation import SCENARIO_TRANSLATION
from src.agent_system.services.theme_basket_pricer import ThemeBasketPricer


# Behavioral macro scenarios. Dates are chosen so that the forward 63d return
# reflects what happened DURING the scenario, not the recovery from it. Each
# scenario is defined by behavioral characteristics (returns, volatility, breadth,
# credit, policy) rather than narrative causes.
# March-April 2020 is intentionally excluded as an exogenous COVID shock.
# 2022-04 appears in both stagflation and growth_scare_no_credit candidate
# considerations, but is placed in stagflation here because growth weakness was
# more dominant than the fake-out recovery pattern.
SCENARIO_DATE_GRID = {
    # SPY +5% to +12% over 63d, broad participation, vol compressed, credit healthy,
    # Fed accommodative or neutral, small caps participating.
    "expansion_disinflation": [
        "2017-05-31",  # synchronized global growth, broad participation
        "2013-09-30",  # post-taper-tantrum recovery
        "2021-03-31",  # vaccine reopening rally
        "2024-06-28",  # broadening after narrow leadership
        "2003-06-30",  # post-bear-market recovery
        "1995-09-29",  # mid-cycle goldilocks
        "2019-06-28",  # Powell pivot to accommodation
    ],
    # SPY +2% to +8% over 63d, narrow leadership, breadth deteriorating,
    # Fed restrictive, growth outperforming value, vol low but rising.
    "late_cycle_expansion": [
        "2017-07-31",  # FAANG dominance, narrow leadership
        "2024-02-29",  # AI narrative dominant
        "2024-09-30",  # narrow leadership continuing
        "2019-12-31",  # late cycle, low vol pre-COVID
        "2018-06-29",  # mid-2018 late cycle
        "2007-04-30",  # pre-GFC late cycle
        "1999-04-30",  # dot-com late stage
    ],
    # SPY -2% to +3% over 63d, energy and commodities outperforming,
    # CPI rising, real yields rising, Fed tightening or restrictive,
    # growth still positive.
    "inflation_shock": [
        "2021-11-30",  # supply chain inflation surge
        "2008-05-30",  # oil at $130 pre-GFC
        "2011-03-31",  # Arab Spring oil spike
        "2022-01-31",  # pre-Ukraine inflation acceleration
        "2018-04-30",  # tariff-driven inflation concerns
    ],
    # SPY -5% to +2% over 63d, growth weak or contracting, inflation persistent,
    # commodities outperforming, Fed in difficult position. Distinct from
    # inflation_shock by growth weakness.
    "stagflation": [
        "2022-04-29",  # peak stagflation 2022 (Q2 was textbook)
        "2022-06-30",  # CPI peak with growth slowing
        "2008-06-30",  # oil at $147 plus growth slowing
        "2011-07-29",  # debt ceiling plus inflation
    ],
    # SPY -3% to -10% over 63d, VIX spiking to 22-35, but credit spreads contained,
    # Fed pivots dovish, recovery typically begins within 63d. "Fake-out" sell-off.
    "growth_scare_no_credit": [
        "2018-10-31",  # Q4 selloff with Fed pivot ahead
        "2015-08-31",  # China deval scare
        "2011-08-31",  # Eurozone scare, no US credit stress
        "2022-10-31",  # peak Fed fear before pivot signal
        "2016-01-29",  # energy/EM scare early 2016
    ],
    # SPY -10% to -30% over 63d, VIX > 30, credit spreads blowing out,
    # banks stressed, sustained drawdown.
    "credit_led_recession": [
        "2008-09-30",  # Lehman / GFC
        "2008-06-30",  # mid-GFC accelerating
        "2001-09-28",  # post-9/11 recession deepening
        "2000-09-29",  # dot-com bust beginning
        "1990-07-31",  # S&L crisis recession
        "2002-06-28",  # late dot-com bust continuing
    ],
}

THEME_EXPOSURE_MATRIX_PATH = (
    BACKEND_ROOT / "data" / "reference" / "theme_exposure_matrix.json"
    if (BACKEND_ROOT / "data" / "reference" / "theme_exposure_matrix.json").exists()
    else REPO_ROOT / "data" / "reference" / "theme_exposure_matrix.json"
)
REFERENCE_DIR = REPO_ROOT / "data" / "reference"
THEME_RETURNS_PATH = REPO_ROOT / "data" / "reference" / "scenario_theme_returns.csv"
MARKET_RETURNS_PATH = REPO_ROOT / "data" / "reference" / "scenario_market_returns.csv"
OVERRIDES_PATH = REFERENCE_DIR / "scenario_calibration_overrides.json"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "price_history"
SOURCE = "basket_calibration_v1"


def _load_theme_matrix() -> dict:
    raw = load_json(THEME_EXPOSURE_MATRIX_PATH)
    if isinstance(raw.get("themes"), dict):
        return dict(raw["themes"])
    if "themes" not in raw:
        return {str(key): value for key, value in raw.items() if key != "metadata"}
    return {}


def _load_overrides() -> dict:
    if not OVERRIDES_PATH.exists():
        return {}
    with OVERRIDES_PATH.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return raw.get("overrides", {}) if isinstance(raw, dict) else {}


def _override_row(
    *,
    scenario_id: str,
    theme_id: str,
    override: dict,
) -> dict:
    return {
        "scenario_id": scenario_id,
        "theme_id": theme_id,
        "expected_return": override["expected_return"],
        "volatility": override["volatility"],
        "p10": None,
        "p25": None,
        "p75": None,
        "p90": None,
        "n_observations": 0,
        "horizon_days": HORIZON_DAYS,
        "source": "manual_override",
        "last_updated": date.today().isoformat(),
        "notes": f"Manual override: {override.get('rationale', 'see scenario_calibration_overrides.json')}",
    }


def main() -> int:
    pricer = ThemeBasketPricer(
        theme_exposure_matrix_path=str(THEME_EXPOSURE_MATRIX_PATH),
        cache_dir=str(CACHE_DIR),
    )
    theme_matrix = _load_theme_matrix()
    overrides = _load_overrides()
    print(f"Loaded {len(theme_matrix)} themes from matrix")
    print(
        f"Loaded overrides for {sum(len(v) for v in overrides.values())} "
        f"scenario \u00d7 theme cells across {len(overrides)} scenarios"
    )
    theme_baskets = {
        theme_id: basket
        for theme_id, basket in theme_matrix.items()
        if isinstance(basket, dict) and basket
    }
    old_theme = old_theme_values(load_csv_rows(THEME_RETURNS_PATH))
    old_market = old_market_values(load_csv_rows(MARKET_RETURNS_PATH))

    theme_rows: list[dict] = []
    market_rows: list[dict] = []
    for scenario_id, dates in SCENARIO_DATE_GRID.items():
        for theme_id in sorted(theme_matrix):
            override = overrides.get(scenario_id, {}).get(theme_id)
            if override:
                theme_rows.append(
                    _override_row(
                        scenario_id=scenario_id,
                        theme_id=theme_id,
                        override=override,
                    )
                )
                continue
            if theme_id not in theme_baskets:
                continue
            stats = pricer.get_basket_distribution(theme_id, dates, horizon_days=HORIZON_DAYS)
            row = calibrated_row(
                scenario_id=scenario_id,
                item_key=theme_id,
                item_column="theme_id",
                stats=stats,
                source=SOURCE,
                notes=", ".join(dates),
            )
            if row is not None:
                theme_rows.append(row)

        for ticker in ("SPY", "QQQ", "IWM"):
            stats = single_ticker_distribution(pricer, ticker, dates)
            row = calibrated_row(
                scenario_id=scenario_id,
                item_key=ticker,
                item_column="ticker",
                stats=stats,
                source=SOURCE,
                notes=", ".join(dates),
            )
            if row is not None:
                market_rows.append(row)

    deltas = []
    deltas.extend(
        print_comparison(
            "THEME CALIBRATION COMPARISON",
            theme_rows,
            old_theme,
            "theme_id",
        )
    )
    deltas.extend(
        print_comparison(
            "MARKET CALIBRATION COMPARISON",
            market_rows,
            old_market,
            "ticker",
        )
    )

    print("\nSCENARIO TRANSLATION (legacy \u2192 behavioral)")
    print("-" * 80)
    for legacy_id, mapping in SCENARIO_TRANSLATION.items():
        parts = [
            f"{behavioral_id} ({weight:.0%})"
            for behavioral_id, weight in mapping.items()
        ]
        print(f"{legacy_id:<28} \u2192 {', '.join(parts)}")
    print()

    print()
    if not confirm_apply():
        print("Calibration not applied.")
        return 0

    write_csv(THEME_RETURNS_PATH, THEME_COLUMNS, theme_rows)
    write_csv(MARKET_RETURNS_PATH, MARKET_COLUMNS, market_rows)
    print_summary(
        theme_rows=theme_rows,
        market_rows=market_rows,
        deltas=deltas,
        theme_path=THEME_RETURNS_PATH,
        market_path=MARKET_RETURNS_PATH,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
