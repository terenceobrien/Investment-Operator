"""Monte Carlo portfolio simulation for accepted trade exposures."""
from __future__ import annotations

# V1 LIMITATIONS — to be addressed in future versions:
# 1. Correlation structure: idiosyncratic returns are drawn independently per trade.
#    Trades in the same theme will have correlated systematic returns (via shared
#    theme draws) but zero residual correlation. This understates tail risk for
#    concentrated theme positions. V2 should add a residual correlation matrix.
# 2. Delta: options and spreads use a flat 0.5 delta placeholder. V2 should
#    compute actual delta from strikes, expiry, and implied vol.
# 3. Scenario return assumptions: all values are manually seeded. Confidence will
#    remain "low" until the backtest pipeline populates the CSV sources.
# 4. Position sizes are treated as fixed. V2 should support path-dependent sizing.

from datetime import datetime, timezone

import numpy as np

from src.agent_system.schemas.monte_carlo import (
    MonteCarloConfig,
    MonteCarloPathResult,
    TradeExposure,
)
from src.agent_system.services.scenario_assumptions_loader import (
    ScenarioAssumptionsLoader,
)


class MonteCarloEngine:
    """Run scenario-conditioned Monte Carlo simulations for trade exposures."""

    def __init__(
        self,
        assumptions_loader: ScenarioAssumptionsLoader,
        config: MonteCarloConfig | None = None,
    ) -> None:
        self.assumptions_loader = assumptions_loader
        self.config = config or MonteCarloConfig()

    def run(
        self,
        exposures: list[TradeExposure],
        scenario_probabilities: dict[str, float],
    ) -> MonteCarloPathResult:
        scenario_ids, probabilities = self._validate_inputs(
            exposures,
            scenario_probabilities,
        )
        if self.config.random_seed is not None:
            np.random.seed(self.config.random_seed)

        sampled_indices = np.random.choice(
            len(scenario_ids),
            size=self.config.n_paths,
            p=probabilities,
        )
        sampled_scenarios = np.array(scenario_ids, dtype=object)[sampled_indices]
        scenario_counts = {
            scenario_id: int(np.sum(sampled_indices == idx))
            for idx, scenario_id in enumerate(scenario_ids)
        }

        market_returns = self._draw_market_returns(
            sampled_scenarios,
            scenario_ids,
        )
        trade_return_matrix, contribution_matrix, divergence_warnings = (
            self._draw_trade_returns(
                exposures,
                scenario_ids,
                probabilities,
                sampled_scenarios,
                market_returns,
            )
        )
        portfolio_returns = contribution_matrix.sum(axis=1)
        per_scenario_mean = self._per_scenario_mean(
            portfolio_returns,
            sampled_scenarios,
            scenario_ids,
        )
        best_scenario = max(per_scenario_mean, key=per_scenario_mean.get)
        worst_scenario = min(per_scenario_mean, key=per_scenario_mean.get)
        tail_mask = self._worst_tail_mask(portfolio_returns, percentile=5)

        return MonteCarloPathResult(
            n_paths=self.config.n_paths,
            n_trades=len(exposures),
            scenarios_sampled=scenario_counts,
            portfolio_expected_return=float(np.mean(portfolio_returns)),
            portfolio_median_return=float(np.median(portfolio_returns)),
            portfolio_p10=float(np.percentile(portfolio_returns, 10)),
            portfolio_p25=float(np.percentile(portfolio_returns, 25)),
            portfolio_p75=float(np.percentile(portfolio_returns, 75)),
            portfolio_p90=float(np.percentile(portfolio_returns, 90)),
            portfolio_prob_loss=float(np.mean(portfolio_returns < 0)),
            portfolio_prob_loss_5pct=float(np.mean(portfolio_returns < -0.05)),
            portfolio_prob_loss_10pct=float(np.mean(portfolio_returns < -0.10)),
            portfolio_expected_shortfall_5pct=float(np.mean(portfolio_returns[tail_mask])),
            portfolio_best_scenario=best_scenario,
            portfolio_worst_scenario=worst_scenario,
            per_scenario_mean_return=per_scenario_mean,
            ticker_median_returns=self._ticker_stat(
                exposures,
                trade_return_matrix,
                np.median,
            ),
            ticker_p10=self._ticker_percentile(exposures, trade_return_matrix, 10),
            ticker_p90=self._ticker_percentile(exposures, trade_return_matrix, 90),
            ticker_prob_loss=self._ticker_prob_loss(exposures, trade_return_matrix),
            ticker_worst_scenario=self._ticker_scenario_extreme(
                exposures,
                trade_return_matrix,
                sampled_scenarios,
                scenario_ids,
                worst=True,
            ),
            ticker_best_scenario=self._ticker_scenario_extreme(
                exposures,
                trade_return_matrix,
                sampled_scenarios,
                scenario_ids,
                worst=False,
            ),
            ticker_portfolio_contribution=self._ticker_stat(
                exposures,
                contribution_matrix,
                np.mean,
            ),
            ticker_tail_contribution=self._ticker_tail_contribution(
                exposures,
                contribution_matrix,
                tail_mask,
            ),
            theme_concentration=self._theme_concentration(exposures),
            divergence_warnings=divergence_warnings,
            assumption_confidence=self._assumption_confidence(exposures),
            correlation_structure_used=self.config.correlation_structure,
            ran_at=datetime.now(timezone.utc),
        )

    def _validate_inputs(
        self,
        exposures: list[TradeExposure],
        scenario_probabilities: dict[str, float],
    ) -> tuple[list[str], np.ndarray]:
        if not exposures:
            raise ValueError("Monte Carlo simulation requires at least one TradeExposure.")
        if not scenario_probabilities:
            raise ValueError("Monte Carlo simulation requires scenario probabilities.")
        scenario_ids = list(scenario_probabilities)
        probabilities = np.array(
            [float(scenario_probabilities[scenario_id]) for scenario_id in scenario_ids],
            dtype=float,
        )
        if np.any(probabilities < 0):
            raise ValueError("Scenario probabilities cannot be negative.")
        probability_sum = float(np.sum(probabilities))
        if not np.isfinite(probability_sum) or probability_sum <= 0:
            raise ValueError("Scenario probabilities must sum to a positive finite value.")
        if abs(probability_sum - 1.0) > 0.02:
            raise ValueError(
                "Scenario probabilities must sum to approximately 1.0 "
                f"(got {probability_sum:.4f})."
            )
        return scenario_ids, probabilities / probability_sum

    def _draw_market_returns(
        self,
        sampled_scenarios: np.ndarray,
        scenario_ids: list[str],
    ) -> np.ndarray:
        market_returns = np.zeros(self.config.n_paths, dtype=float)
        for scenario_id in scenario_ids:
            mask = sampled_scenarios == scenario_id
            count = int(np.sum(mask))
            if count == 0:
                continue
            assumption = self.assumptions_loader.get_market_return(scenario_id, "SPY")
            market_returns[mask] = np.random.normal(
                assumption.expected_return,
                assumption.volatility,
                count,
            )
        return market_returns

    def _draw_trade_returns(
        self,
        exposures: list[TradeExposure],
        scenario_ids: list[str],
        probabilities: np.ndarray,
        sampled_scenarios: np.ndarray,
        market_returns: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        n_paths = self.config.n_paths
        n_trades = len(exposures)
        trade_returns = np.zeros((n_paths, n_trades), dtype=float)
        contributions = np.zeros((n_paths, n_trades), dtype=float)
        warnings: list[str] = []
        theme_draws: dict[str, np.ndarray] = {}

        for idx, exposure in enumerate(exposures):
            theme_returns = self._theme_return_paths(
                exposure.theme,
                scenario_ids,
                sampled_scenarios,
                theme_draws,
            )
            idio_vol = exposure.idiosyncratic_volatility
            if idio_vol == 0.0:
                idio_vol = 0.05
                warnings.append(
                    f"{exposure.underlying}: idiosyncratic volatility was 0.0; "
                    "applied 5.0% floor."
                )
            idiosyncratic_returns = np.random.normal(0.0, idio_vol, n_paths)
            underlying_returns = (
                exposure.market_beta * market_returns
                + exposure.theme_exposure * exposure.theme_beta * theme_returns
                + idiosyncratic_returns
            )
            column = underlying_returns * exposure.delta
            trade_returns[:, idx] = column
            contributions[:, idx] = column * exposure.position_size_pct
            warning = self._divergence_warning(
                exposure,
                scenario_ids,
                probabilities,
            )
            if warning:
                warnings.append(warning)

        return trade_returns, contributions, warnings

    def _theme_return_paths(
        self,
        theme: str,
        scenario_ids: list[str],
        sampled_scenarios: np.ndarray,
        theme_draws: dict[str, np.ndarray],
    ) -> np.ndarray:
        if theme in theme_draws:
            return theme_draws[theme]
        returns = np.zeros(self.config.n_paths, dtype=float)
        for scenario_id in scenario_ids:
            mask = sampled_scenarios == scenario_id
            count = int(np.sum(mask))
            if count == 0:
                continue
            assumption = self.assumptions_loader.get_theme_return(scenario_id, theme)
            returns[mask] = np.random.normal(
                assumption.expected_return,
                assumption.volatility,
                count,
            )
        theme_draws[theme] = returns
        return returns

    def _divergence_warning(
        self,
        exposure: TradeExposure,
        scenario_ids: list[str],
        probabilities: np.ndarray,
    ) -> str | None:
        if not self.config.use_scenario_pnl_override or not exposure.scenario_exposures:
            return None
        factor_model_return = 0.0
        scenario_pnl_return = 0.0
        for scenario_id, probability in zip(scenario_ids, probabilities):
            market = self.assumptions_loader.get_market_return(scenario_id, "SPY")
            theme = self.assumptions_loader.get_theme_return(scenario_id, exposure.theme)
            factor_model_return += float(probability) * (
                exposure.market_beta * market.expected_return
                + exposure.theme_exposure
                * exposure.theme_beta
                * theme.expected_return
            ) * exposure.delta
            scenario_pnl_return += float(probability) * float(
                exposure.scenario_exposures.get(scenario_id, 0.0)
            )
        abs_diff = abs(factor_model_return - scenario_pnl_return)
        if abs_diff <= self.config.divergence_warning_threshold:
            return None
        return (
            f"{exposure.underlying}: factor model expected return "
            f"{factor_model_return:.1%} diverges from scenario P&L implied "
            f"{scenario_pnl_return:.1%} by {abs_diff:.1%}"
        )

    def _per_scenario_mean(
        self,
        returns: np.ndarray,
        sampled_scenarios: np.ndarray,
        scenario_ids: list[str],
    ) -> dict[str, float]:
        means: dict[str, float] = {}
        for scenario_id in scenario_ids:
            mask = sampled_scenarios == scenario_id
            if np.any(mask):
                means[scenario_id] = float(np.mean(returns[mask]))
        return means

    def _ticker_stat(
        self,
        exposures: list[TradeExposure],
        matrix: np.ndarray,
        fn,
    ) -> dict[str, float]:
        return {
            exposure.underlying: float(fn(matrix[:, idx]))
            for idx, exposure in enumerate(exposures)
        }

    def _ticker_percentile(
        self,
        exposures: list[TradeExposure],
        matrix: np.ndarray,
        percentile: float,
    ) -> dict[str, float]:
        return {
            exposure.underlying: float(np.percentile(matrix[:, idx], percentile))
            for idx, exposure in enumerate(exposures)
        }

    def _ticker_prob_loss(
        self,
        exposures: list[TradeExposure],
        trade_return_matrix: np.ndarray,
    ) -> dict[str, float]:
        return {
            exposure.underlying: float(np.mean(trade_return_matrix[:, idx] < 0))
            for idx, exposure in enumerate(exposures)
        }

    def _ticker_scenario_extreme(
        self,
        exposures: list[TradeExposure],
        trade_return_matrix: np.ndarray,
        sampled_scenarios: np.ndarray,
        scenario_ids: list[str],
        *,
        worst: bool,
    ) -> dict[str, str]:
        results: dict[str, str] = {}
        for idx, exposure in enumerate(exposures):
            means = self._per_scenario_mean(
                trade_return_matrix[:, idx],
                sampled_scenarios,
                scenario_ids,
            )
            results[exposure.underlying] = (
                min(means, key=means.get) if worst else max(means, key=means.get)
            )
        return results

    def _ticker_tail_contribution(
        self,
        exposures: list[TradeExposure],
        contribution_matrix: np.ndarray,
        tail_mask: np.ndarray,
    ) -> dict[str, float]:
        return {
            exposure.underlying: float(np.mean(contribution_matrix[tail_mask, idx]))
            for idx, exposure in enumerate(exposures)
        }

    def _theme_concentration(
        self,
        exposures: list[TradeExposure],
    ) -> dict[str, float]:
        concentration: dict[str, float] = {}
        for exposure in exposures:
            concentration[exposure.theme] = (
                concentration.get(exposure.theme, 0.0) + exposure.position_size_pct
            )
        return concentration

    def _assumption_confidence(
        self,
        exposures: list[TradeExposure],
    ) -> str:
        exposure_confidences = {exposure.overall_confidence for exposure in exposures}
        if "low" in exposure_confidences:
            return "low"
        if self.config.assumption_source_label == "manual_estimate":
            return "low"
        if exposure_confidences == {"high"}:
            return "high"
        return "medium"

    @staticmethod
    def _worst_tail_mask(
        returns: np.ndarray,
        *,
        percentile: float,
    ) -> np.ndarray:
        cutoff = np.percentile(returns, percentile)
        mask = returns <= cutoff
        if np.any(mask):
            return mask
        fallback = np.zeros(len(returns), dtype=bool)
        fallback[int(np.argmin(returns))] = True
        return fallback
