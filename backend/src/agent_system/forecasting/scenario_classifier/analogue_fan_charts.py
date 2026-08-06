"""Matplotlib rendering for analogue fan diagnostics."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.agent_system.forecasting.scenario_classifier.analogue_fan import (
    FanResult,
)
from src.agent_system.forecasting.scenario_classifier.nber_dates import parse_quarter


class AnalogueFanChartError(RuntimeError):
    """Raised when fan chart rendering fails."""


def render_fan_charts(
    fan_result: FanResult | Mapping[str, Any],
    output_dir: str | Path,
) -> dict[str, str]:
    """Render one PNG per variable plus a 2x4 combined grid PNG."""

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        raise AnalogueFanChartError(f"matplotlib unavailable for fan charts: {exc}") from exc

    payload = fan_result.to_dict() if isinstance(fan_result, FanResult) else dict(fan_result)
    query = parse_quarter(payload["query_date"])
    horizon = int(payload["horizon_quarters"])
    quarters = [str(query + step) for step in range(1, horizon + 1)]
    x = np.arange(1, horizon + 1, dtype=float)
    variables = payload.get("variables")
    if not isinstance(variables, Mapping) or not variables:
        raise AnalogueFanChartError("fan result has no variables to render")

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for variable, result in variables.items():
        fig, ax = plt.subplots(figsize=(8.0, 4.8))
        _draw_variable(ax, str(variable), result, x, quarters)
        path = target / f"analogue_fan_{payload['query_date']}_{variable}.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths[str(variable)] = str(path)

    grid_path = target / f"analogue_fan_{payload['query_date']}_grid.png"
    fig, axes = plt.subplots(2, 4, figsize=(18.0, 8.5), sharex=False)
    flat_axes = list(axes.ravel())
    for ax, (variable, result) in zip(flat_axes, variables.items()):
        _draw_variable(ax, str(variable), result, x, quarters, compact=True)
    for ax in flat_axes[len(variables) :]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(grid_path, dpi=150)
    plt.close(fig)
    paths["combined_grid"] = str(grid_path)
    return paths


def _draw_variable(
    ax,
    variable: str,
    result: Mapping[str, Any],
    x: np.ndarray,
    quarters: list[str],
    *,
    compact: bool = False,
) -> None:
    percentiles = result.get("percentiles") or {}
    p10 = _path_array(percentiles.get("p10"))
    p25 = _path_array(percentiles.get("p25"))
    p50 = _path_array(percentiles.get("p50"))
    p75 = _path_array(percentiles.get("p75"))
    p90 = _path_array(percentiles.get("p90"))
    eff = _path_array(result.get("effective_n"))
    n_eff = eff[0] if len(eff) and np.isfinite(eff[0]) else np.nan

    ax.fill_between(x, p10, p90, color="#8bb7d8", alpha=0.28, label="p10-p90")
    ax.fill_between(x, p25, p75, color="#3e7fb1", alpha=0.32, label="p25-p75")
    ax.plot(x, p50, color="#12324a", linewidth=2.0, label="p50")
    recession = result.get("median_recession_bound")
    benign = result.get("median_benign")
    if recession is not None:
        ax.plot(x, _path_array(recession), color="#b33a3a", linestyle="--", linewidth=1.7, label="recession analogues")
    if benign is not None:
        ax.plot(x, _path_array(benign), color="#2f7d51", linestyle="--", linewidth=1.7, label="benign analogues")
    anchor = result.get("query_anchor_value")
    if anchor is not None:
        ax.axhline(float(anchor), color="#5f6368", linestyle=":", linewidth=1.1, label="query anchor")
    ax.set_title(f"{variable} — analogue fan (n_eff={n_eff:.2f})")
    ax.set_xticks(x)
    ax.set_xticklabels(quarters, rotation=45, ha="right", fontsize=8 if compact else 9)
    ax.grid(True, axis="y", alpha=0.25)
    if not compact:
        ax.legend(loc="best", fontsize=8)


def _path_array(values: Any) -> np.ndarray:
    if values is None:
        return np.asarray([], dtype=float)
    return np.asarray(
        [np.nan if value is None else float(value) for value in values],
        dtype=float,
    )
