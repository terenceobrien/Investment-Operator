"""LLM-backed scenario generation."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from src.agent_system.agents.macro_agent_prompts import render_regime_context
from src.agent_system.llm.client import StructuredOutputError, parse_structured
from src.agent_system.llm.config import SCENARIO_AGENT_MODEL
from src.agent_system.scenarios.types import ScenarioSet
from src.agent_system.schemas.regime import RegimeState


class ScenarioGenerationError(Exception):
    """Raised after scenario generation exhausts validation retries."""


SYSTEM_PROMPT = """You are the scenario generation module for a structured \
investment research system. Produce a compact ScenarioSet of macro-scoped \
forward scenarios that future portfolio reasoning can use.

Rules:
1. Produce 3-5 scenarios, not more.
2. Probabilities must sum to roughly 1.0.
3. Scenarios must span genuinely distinct uncertainty branches. Do not create \
five versions of "soft landing".
4. At least one scenario must be a meaningful adverse tail risk: the path where \
things go badly wrong for portfolios.
5. factor_implications must be an object with exactly five required fields: \
rates, equities, dollar, credit, and commodities. Each field is short prose \
describing that factor's directional implication in the scenario.
6. Use short stable scenario ids such as base_case, inflation_tail, risk_off.
7. Keep descriptions specific enough that a human can score trades against them.

Few-shot example 1: rate uncertainty set.
{
  "horizon_months": 6,
  "scenarios": [
    {
      "id": "sticky_inflation_hold",
      "label": "Sticky inflation keeps the Fed on hold",
      "probability": 0.40,
      "description": "Inflation cools too slowly for cuts. Growth avoids recession, but real rates stay restrictive and equity leadership remains narrow.",
      "factor_implications": {
        "rates": "Front end stays elevated; 10y holds 4.3-4.7%",
        "equities": "Quality growth holds up; small caps lag",
        "dollar": "Dollar firm versus low-yielders",
        "credit": "Spreads remain contained but do not tighten much",
        "commodities": "Oil range-bound; gold supported by real-rate uncertainty"
      }
    },
    {
      "id": "dovish_disinflation",
      "label": "Disinflation unlocks a dovish pivot",
      "probability": 0.35,
      "description": "Inflation prints soften and the Fed validates cuts. Breadth improves as rate-sensitive cyclicals and profitable duration assets re-rate.",
      "factor_implications": {
        "rates": "2y falls sharply; 10y drifts 3.6-4.0%",
        "equities": "Equal weight and rate-sensitive quality outperform",
        "dollar": "Dollar weakens",
        "credit": "Spreads grind tighter",
        "commodities": "Gold benefits; oil depends on growth"
      }
    },
    {
      "id": "hard_landing",
      "label": "Growth breaks before cuts help",
      "probability": 0.25,
      "description": "Labor and consumption weaken abruptly. The Fed pivots too late, credit spreads widen, and equity downside overwhelms lower-rate support.",
      "factor_implications": {
        "rates": "Curve bull-steepens; front end rallies",
        "equities": "Broad equities fall; defensives outperform",
        "dollar": "Dollar rallies on risk aversion",
        "credit": "HY spreads widen materially",
        "commodities": "Oil falls; gold mixed but supported by safety demand"
      }
    }
  ]
}

Few-shot example 2: geopolitical/commodity uncertainty set.
{
  "horizon_months": 6,
  "scenarios": [
    {
      "id": "oil_shock_persists",
      "label": "Oil shock persists and inflation risk returns",
      "probability": 0.30,
      "description": "Shipping disruption or supply discipline keeps oil elevated long enough to reprice inflation expectations and Fed-cut odds.",
      "factor_implications": {
        "rates": "Breakevens rise; nominal yields resist falling",
        "equities": "Energy and defense outperform; consumers lag",
        "dollar": "Dollar firm on inflation/risk mix",
        "credit": "Consumer cyclicals and weak balance sheets widen",
        "commodities": "Oil and refined products stay bid"
      }
    },
    {
      "id": "reopening_relief",
      "label": "Geopolitical de-escalation removes the oil premium",
      "probability": 0.45,
      "description": "Reopening or de-escalation headlines normalize shipping, compress oil risk premium, and ease inflation pressure without damaging AI capex.",
      "factor_implications": {
        "rates": "Cut odds rise; yields drift lower",
        "equities": "Broad risk improves; crowded oil hedges fade",
        "dollar": "Dollar softens modestly",
        "credit": "Spreads stay tight",
        "commodities": "Oil falls; industrial metals depend on growth"
      }
    },
    {
      "id": "correlation_shock",
      "label": "Oil and rates trigger a cross-asset correlation shock",
      "probability": 0.25,
      "description": "Oil stays high while rates back up and narrow equity leadership finally cracks, forcing credit and equity volatility higher together.",
      "factor_implications": {
        "rates": "Real yields rise; curve volatility increases",
        "equities": "Mega-cap leadership stalls and beta sells off",
        "dollar": "Dollar rallies",
        "credit": "HY spreads widen from tight levels",
        "commodities": "Oil remains high; gold catches safety bid"
      }
    }
  ]
}
"""


def _user_prompt(
    *,
    regime: RegimeState,
    horizon_months: int,
    n_scenarios: int,
    feedback: str | None = None,
) -> str:
    prompt = (
        f"Generate {n_scenarios} scenarios for a {horizon_months}-month horizon.\n"
        f"Set regime_id_basis to: {regime.regime_id}\n"
        f"Set generated_at to the current UTC timestamp: {datetime.now(timezone.utc).isoformat()}\n\n"
        "# Regime context\n"
        f"{render_regime_context(regime)}\n"
    )
    if feedback:
        prompt += (
            "\nYour previous scenario output failed validation. Fix the next "
            f"response. Validation error:\n{feedback}\n"
        )
    return prompt


async def propose_scenarios(
    regime: RegimeState,
    horizon_months: int = 6,
    n_scenarios: int = 4,
) -> ScenarioSet:
    """
    Call the LLM to propose a ScenarioSet given the current regime context.

    Retries up to two times when structured output validation fails.
    """
    if not (3 <= n_scenarios <= 5):
        raise ValueError("n_scenarios must be between 3 and 5")

    feedback = None
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            return parse_structured(
                system=SYSTEM_PROMPT,
                user=_user_prompt(
                    regime=regime,
                    horizon_months=horizon_months,
                    n_scenarios=n_scenarios,
                    feedback=feedback,
                ),
                model=SCENARIO_AGENT_MODEL,
                response_schema=ScenarioSet,
                purpose="scenario generation propose_scenarios",
                temperature=0.3,
                max_retries=0,
            )
        except (StructuredOutputError, ValidationError, ValueError) as exc:
            last_error = exc
            feedback = str(exc)

    raise ScenarioGenerationError(
        f"Failed to generate valid ScenarioSet after 3 attempts: {last_error}"
    )
