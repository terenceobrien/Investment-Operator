"""Smoke test: confirm the XLSX regime config loads and drives scoring."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

for env_path in [REPO_ROOT / ".env", REPO_ROOT / ".env.local", BACKEND_ROOT / ".env"]:
    if env_path.exists():
        load_dotenv(env_path, override=env_path == BACKEND_ROOT / ".env")

from src.state.config_loader import ENV_PARAMS, REGIME_PARAMS, WEIGHTS


def main() -> int:
    print(f"\nLoaded {len(list(REGIME_PARAMS.keys()))} regime_layers params")
    print(f"Loaded {len(list(ENV_PARAMS.keys()))} classify_environment params")
    print(f"Loaded {len(list(WEIGHTS.keys()))} composite_weights params")

    print("\n--- Credit anchor (should be tightened) ---")
    print(
        "  hy_spread_level scale: "
        f"[{REGIME_PARAMS['credit.hy_spread_level.scale_lo']}, "
        f"{REGIME_PARAMS['credit.hy_spread_level.scale_hi']}]"
    )
    print("  expected: [280, 700]")

    print("\n--- Risk-off headline thresholds (should be loosened) ---")
    print(
        f"  credit_threshold:     {ENV_PARAMS['env.risk_off_headline.credit_threshold']} "
        "(was 3.5)"
    )
    print(
        f"  composite_threshold:  {ENV_PARAMS['env.risk_off_headline.composite_threshold']} "
        "(was 38)"
    )
    print(
        f"  volatility_threshold: {ENV_PARAMS['env.risk_off_headline.volatility_threshold']} "
        "(was 4)"
    )

    print("\n--- AAII thresholds ---")
    print(
        f"  panic:    {REGIME_PARAMS['positioning.aaii_bull_minus_bear.panic_threshold']} "
        "(expected -28)"
    )
    print(
        f"  euphoria: {REGIME_PARAMS['positioning.aaii_bull_minus_bear.euphoria_threshold']} "
        "(expected 37)"
    )

    print("\n--- Default horizon weights ---")
    for layer in ["monetary", "credit", "volatility", "breadth", "positioning"]:
        print(f"  {layer:<12} {WEIGHTS[f'weights.default.{layer}']}")

    print("\n--- End-to-end: build a live regime state ---")
    from src.state.regime_state import build_regime_state

    state = build_regime_state(save=False)
    print(f"  environment: {state.environment}")
    print(f"  composite:   {state.score_total}")
    print(f"  layer credit score: {state.layer_credit}")

    print("\nConfig loader verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
