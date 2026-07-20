"""
Shock template library for running Helix behavioral scenarios through
FRB/US (pyfrbus).

Design principle: templates are GENERIC and stable across cycles. All
regime-conditioning enters through (a) the LONGBASE baseline vintage,
(b) the per-cycle parameters in the scenario map YAML, and (c) downstream
Helix layers. Do not hand-edit templates per cycle. If you need a new
shock *structure*, add a new template — do not bend parameters until an
old one imitates it.

Every template has the signature:

    template(frbus, with_adds, start, end, **params) -> pd.DataFrame

where `with_adds` is the output of frbus.init_trac(start, end, data) —
the baseline dataset with tracking residuals — and the return value is
the solved scenario DataFrame over [start, end].

Only targeted variables are forced. Everything else in the 367-variable
system responds endogenously (Okun dynamics, Phillips block, inertial
Taylor rule, term structure, credit premia, identities enforced).

Templates fail loudly: unknown parameters, missing columns, and
inconsistent parameter combinations raise TemplateError immediately.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class TemplateError(RuntimeError):
    """Raised when a template is invoked with bad parameters or data."""


# ─── helpers ────────────────────────────────────────────────────────────


def _require_columns(data: pd.DataFrame, cols: list[str], context: str) -> None:
    missing = [c for c in cols if c not in data.columns]
    if missing:
        candidates = {}
        for m in missing:
            stem = m.replace("_aerr", "")[:4]
            candidates[m] = [c for c in data.columns if stem in c][:8]
        raise TemplateError(
            f"{context}: columns missing from dataset: {missing}. "
            f"Similar columns present: {candidates}. "
            "Check the variable name against the LONGBASE vintage you loaded."
        )


def _quarterly_factors_from_annualized(rates_annualized: list[float]) -> np.ndarray:
    """Convert annualized growth rates (%) to quarterly gross factors."""
    return (1.0 + np.asarray(rates_annualized, dtype=float) / 100.0) ** 0.25


def _baseline_growth_annualized(
    with_adds: pd.DataFrame, var: str, start: pd.Period, n_quarters: int
) -> np.ndarray:
    """Annualized q/q growth of `var` in the baseline over [start, start+n)."""
    window = with_adds.loc[start - 1 : start + n_quarters - 1, var].astype(float)
    q_growth = window.pct_change().dropna().to_numpy()
    return ((1.0 + q_growth) ** 4 - 1.0) * 100.0


def _resolve_gdp_trajectory(
    with_adds: pd.DataFrame,
    start: pd.Period,
    end: pd.Period,
    growth_annualized: list[float] | None,
    growth_delta_annualized: list[float] | None,
    context: str,
) -> tuple[np.ndarray, pd.Period]:
    """Build a GDP level trajectory from exactly one growth specification.

    Absolute (`growth_annualized`): the path IS the growth rate — use when
    the scenario's meaning is a specific outcome (e.g. a recession of a
    given depth), independent of baseline drift.

    Relative (`growth_delta_annualized`): baseline growth plus delta — use
    when the meaning is a push against current expectations.
    """
    if (growth_annualized is None) == (growth_delta_annualized is None):
        raise TemplateError(
            f"{context}: provide exactly one of growth_annualized or "
            "growth_delta_annualized"
        )
    if growth_annualized is not None:
        rates = list(growth_annualized)
    else:
        n = len(growth_delta_annualized)
        base_rates = _baseline_growth_annualized(with_adds, "xgdp", start, n)
        rates = list(base_rates + np.asarray(growth_delta_annualized, dtype=float))

    shock_end = start + len(rates) - 1
    if shock_end > end:
        raise TemplateError(
            f"{context}: shock length {len(rates)} quarters exceeds horizon "
            f"({start}..{end})"
        )
    traj = with_adds.loc[start - 1, "xgdp"] * np.cumprod(
        _quarterly_factors_from_annualized(rates)
    )
    return traj, shock_end


def _apply_aerr_add(
    d: pd.DataFrame,
    var_aerr: str,
    add_path: list[float],
    start: pd.Period,
    end: pd.Period,
    context: str,
) -> None:
    """Additively shock an _aerr column over [start, start+len)."""
    n = len(add_path)
    add_end = start + n - 1
    if add_end > end:
        raise TemplateError(f"{context}: add-factor path exceeds horizon")
    d.loc[start:add_end, var_aerr] = (
        d.loc[start:add_end, var_aerr].astype(float).to_numpy()
        + np.asarray(add_path, dtype=float)
    )


# ─── templates ──────────────────────────────────────────────────────────


def baseline(frbus, with_adds: pd.DataFrame, start: pd.Period, end: pd.Period) -> pd.DataFrame:
    """No shock. Solve the model on the tracking-residual baseline.

    LONGBASE contains history plus the Fed's extended projection;
    init_trac residuals make the solution reproduce that projection
    exactly, so this equals the Fed's baseline by construction. It exists
    so every scenario flows through the same solve path and output schema.
    """
    return frbus.solve(start, end, with_adds)


def demand_gdp_path(
    frbus,
    with_adds: pd.DataFrame,
    start: pd.Period,
    end: pd.Period,
    *,
    growth_annualized: list[float] | None = None,
    growth_delta_annualized: list[float] | None = None,
    instrument: str = "eco_aerr",
) -> pd.DataFrame:
    """Force a real GDP path via a demand-side instrument (default: consumption).

    Sign is unconstrained: negative paths are recessions/scares, positive
    paths are demand lifts. After the forced quarters the trajectory is
    released and model dynamics take over (unemployment, inflation, and
    the policy rate all respond endogenously).

    Behavioral scenario use: growth_scare_no_credit (moderate negative
    absolute path, no credit shock — FRB/US's endogenous credit-premium
    response to a demand scare is mild, which IS the 'credit stays
    healthy' version).
    """
    _require_columns(with_adds, ["xgdp", instrument], "demand_gdp_path")
    traj, shock_end = _resolve_gdp_trajectory(
        with_adds, start, end, growth_annualized, growth_delta_annualized,
        "demand_gdp_path",
    )
    d = with_adds.copy()
    d.loc[start:end, "xgdp_t"] = np.nan
    d.loc[start:shock_end, "xgdp_t"] = traj
    return frbus.mcontrol(start, end, d, targ=["xgdp"], traj=["xgdp_t"], inst=[instrument])


def demand_with_inflation_addfactor(
    frbus,
    with_adds: pd.DataFrame,
    start: pd.Period,
    end: pd.Period,
    *,
    picxfe_aerr_add: list[float],
    growth_annualized: list[float] | None = None,
    growth_delta_annualized: list[float] | None = None,
    instrument: str = "eco_aerr",
) -> pd.DataFrame:
    """Demand path combined with a core-inflation add factor. Either side
    can be positive or negative, and the GDP path is optional.

    picxfe_aerr_add — additive pp (annualized) on the core PCE inflation
    residual per quarter. Negative = disinflationary surprise, positive =
    supply-side inflation pressure. Applied BEFORE the solve, so the
    Taylor rule sees and responds to it.

    If no growth path is given, the template is a pure inflation
    add-factor solve (demand responds endogenously to the inflation and
    policy response — this is the inflation_shock configuration).

    Behavioral scenario use:
      expansion_disinflation — positive growth delta + negative inflation add
      inflation_shock        — no growth path + large positive inflation add
      stagflation            — negative growth path + positive inflation add
    """
    _require_columns(
        with_adds, ["xgdp", "picxfe_aerr", instrument], "demand_with_inflation_addfactor"
    )
    d = with_adds.copy()
    _apply_aerr_add(
        d, "picxfe_aerr", picxfe_aerr_add, start, end, "demand_with_inflation_addfactor"
    )

    no_gdp_path = growth_annualized is None and growth_delta_annualized is None
    if no_gdp_path:
        return frbus.solve(start, end, d)

    traj, shock_end = _resolve_gdp_trajectory(
        d, start, end, growth_annualized, growth_delta_annualized,
        "demand_with_inflation_addfactor",
    )
    d.loc[start:end, "xgdp_t"] = np.nan
    d.loc[start:shock_end, "xgdp_t"] = traj
    return frbus.mcontrol(start, end, d, targ=["xgdp"], traj=["xgdp_t"], inst=[instrument])


def investment_path(
    frbus,
    with_adds: pd.DataFrame,
    start: pd.Period,
    end: pd.Period,
    *,
    ebfi_level_delta_pct: list[float],
    instrument: str = "ebfi_aerr",
) -> pd.DataFrame:
    """Force business fixed investment relative to its baseline level.

    ebfi_level_delta_pct — per-quarter % deviation of the BFI *level* from
    baseline, e.g. [-2.0, -5.0, -8.0, -8.0] for a capex rollover or
    [1.0, 2.0, 3.0, 3.0] for a boom. Trajectory releases afterward.

    Forcing the path through ebfi_aerr (not consumption) produces the
    investment-led mix of unemployment/inflation/rates responses — the
    instrument choice is the economic content of the scenario.
    """
    _require_columns(with_adds, ["ebfi", instrument], "investment_path")

    n = len(ebfi_level_delta_pct)
    shock_end = start + n - 1
    if shock_end > end:
        raise TemplateError(
            f"investment_path: shock length {n} quarters exceeds horizon ({start}..{end})"
        )

    baseline_levels = with_adds.loc[start:shock_end, "ebfi"].astype(float).to_numpy()
    traj = baseline_levels * (1.0 + np.asarray(ebfi_level_delta_pct, dtype=float) / 100.0)

    d = with_adds.copy()
    d.loc[start:end, "ebfi_t"] = np.nan
    d.loc[start:shock_end, "ebfi_t"] = traj
    return frbus.mcontrol(start, end, d, targ=["ebfi"], traj=["ebfi_t"], inst=[instrument])


def investment_boom_sticky_inflation(
    frbus,
    with_adds: pd.DataFrame,
    start: pd.Period,
    end: pd.Period,
    *,
    ebfi_level_delta_pct: list[float],
    picxfe_aerr_add: list[float],
    instrument: str = "ebfi_aerr",
) -> pd.DataFrame:
    """Investment boom combined with an exogenous core-inflation add factor.

    Behavioral scenario use: late_cycle_expansion — investment running
    above baseline while inflation stays sticky above the Phillips
    block's endogenous path, forcing the Taylor rule to stay restrictive.
    The current-regime flavor (e.g. 'AI capex') enters purely through the
    parameter magnitudes.
    """
    _require_columns(
        with_adds, ["ebfi", "picxfe_aerr", instrument], "investment_boom_sticky_inflation"
    )
    d = with_adds.copy()
    _apply_aerr_add(
        d, "picxfe_aerr", picxfe_aerr_add, start, end, "investment_boom_sticky_inflation"
    )

    n_inv = len(ebfi_level_delta_pct)
    inv_end = start + n_inv - 1
    if inv_end > end:
        raise TemplateError("investment_boom_sticky_inflation: shock length exceeds horizon")

    baseline_levels = d.loc[start:inv_end, "ebfi"].astype(float).to_numpy()
    traj = baseline_levels * (1.0 + np.asarray(ebfi_level_delta_pct, dtype=float) / 100.0)
    d.loc[start:end, "ebfi_t"] = np.nan
    d.loc[start:inv_end, "ebfi_t"] = traj

    return frbus.mcontrol(start, end, d, targ=["ebfi"], traj=["ebfi_t"], inst=[instrument])


def credit_spread_shock(
    frbus,
    with_adds: pd.DataFrame,
    start: pd.Period,
    end: pd.Period,
    *,
    rbbbp_aerr_add: list[float],
    growth_annualized: list[float] | None = None,
    growth_delta_annualized: list[float] | None = None,
    instrument: str = "eco_aerr",
) -> pd.DataFrame:
    """Corporate credit premium shock, optionally combined with a demand path.

    rbbbp_aerr_add — additive pp path on the BBB risk/term premium
    residual, e.g. [1.5, 1.2, 0.8, 0.4] for a spread blowout that fades.
    In FRB/US, rbbbp feeds the BBB corporate rate identity
    (rbbb = rbbbp + rg10) AND the equity premium equation (reqp loads on
    rbbbp), so a premium shock tightens financial conditions through both
    corporate borrowing costs and equity valuations — the credit-led
    transmission channel.

    Note: rbbbp is an investment-grade premium. FRB/US has no HY spread or
    default cycle; this is the model's credit-stress lever, mapped loosely
    (not 1:1) to Helix's HY-OAS-based credit layer.

    Behavioral scenario use: credit_led_recession — spread shock plus a
    forced demand contraction. Contrast with growth_scare_no_credit
    (demand_gdp_path alone, spreads stay near baseline).
    """
    _require_columns(
        with_adds, ["xgdp", "rbbbp_aerr", instrument], "credit_spread_shock"
    )
    d = with_adds.copy()
    _apply_aerr_add(d, "rbbbp_aerr", rbbbp_aerr_add, start, end, "credit_spread_shock")

    no_gdp_path = growth_annualized is None and growth_delta_annualized is None
    if no_gdp_path:
        return frbus.solve(start, end, d)

    traj, shock_end = _resolve_gdp_trajectory(
        d, start, end, growth_annualized, growth_delta_annualized, "credit_spread_shock"
    )
    d.loc[start:end, "xgdp_t"] = np.nan
    d.loc[start:shock_end, "xgdp_t"] = traj
    return frbus.mcontrol(start, end, d, targ=["xgdp"], traj=["xgdp_t"], inst=[instrument])


def oil_price_shock(
    frbus,
    with_adds: pd.DataFrame,
    start: pd.Period,
    end: pd.Period,
    *,
    oil_price_multiplier: list[float],
    oil_var: str = "poil",
) -> pd.DataFrame:
    """Multiply the (exogenous) oil price against baseline, then solve.

    oil_price_multiplier — per-quarter gross multipliers on the baseline
    oil price, e.g. [1.40, 1.35, 1.25, 1.15] for a +40% spike that decays.
    Quarters beyond the list keep the baseline path.

    Retained for oil-specific tails; can also be layered conceptually
    under inflation_shock when the supply shock is energy-driven (run
    both and compare transmission).

    oil_var defaults to 'poil'. VERIFY against your LONGBASE vintage —
    if absent the template raises with candidate column names.
    """
    _require_columns(with_adds, [oil_var], "oil_price_shock")

    n = len(oil_price_multiplier)
    shock_end = start + n - 1
    if shock_end > end:
        raise TemplateError(
            f"oil_price_shock: shock length {n} quarters exceeds horizon ({start}..{end})"
        )

    d = with_adds.copy()
    base = d.loc[start:shock_end, oil_var].astype(float).to_numpy()
    d.loc[start:shock_end, oil_var] = base * np.asarray(oil_price_multiplier, dtype=float)
    return frbus.solve(start, end, d)


# ─── registry ───────────────────────────────────────────────────────────

TEMPLATES = {
    "baseline": baseline,
    "demand_gdp_path": demand_gdp_path,
    "demand_with_inflation_addfactor": demand_with_inflation_addfactor,
    "investment_path": investment_path,
    "investment_boom_sticky_inflation": investment_boom_sticky_inflation,
    "credit_spread_shock": credit_spread_shock,
    "oil_price_shock": oil_price_shock,
}