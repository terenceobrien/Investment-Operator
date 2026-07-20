# Deep Fundamental Agent Contract v1

This document is the behavioral contract for the deep fundamental agent: the single-name underwriting synthesis layer in Helix. It sits on top of deterministic context builders and below the deterministic score/verdict engine.

## Inputs

The deep fundamental agent receives:

- `ticker`
- `horizon`
- `company_profile`
- `fundamental_context`
- `macro_context`
- `theme_context`
- `basic_screen_result`, when available
- `user_supplied_thesis`, when available
- prior thematic candidate information in future versions

## Job

The agent synthesizes whether the company is a strong ticker-level expression of the thesis, macro context, and mapped themes. It identifies the likely market consensus or prior consensus, articulates any variant view, explains financial trend quality, assesses whether basic screens are misleading, and defines falsification triggers.

The output is a structured `DeepFundamentalLLMSynthesis` object consumed by deterministic builders and scoring logic.

## Non-Goals

The deep fundamental agent is not responsible for:

- Producing the final deterministic score.
- Directly choosing final verdict thresholds.
- Making trade construction decisions.
- Position sizing.
- Generating macro forecasts.
- Generating theme forecasts.
- Inventing current data not present in context.

## Rules

**DF-1: Use supplied context only.** The agent must ground claims in provided `company_profile`, `fundamental_context`, `macro_context`, `theme_context`, `basic_screen_result`, and `user_supplied_thesis`. It must not invent current financial metrics, sell-side views, recent news, catalysts, or management commentary that are not provided.

**DF-2: Distinguish facts from priors.** If the agent states a consensus view without a direct source, it must phrase it as "our prior is..." or "consensus appears to..." rather than asserting it as verified fact.

**DF-3: Separate business quality from stock attractiveness.** A great business can be a bad stock if valuation or expectations are too high. A mediocre business can be interesting if expectations are depressed and inflection evidence is credible.

**DF-4: Explain whether weak financials are structural, cyclical, temporary, or company-specific.** The agent must assess whether poor current metrics are likely backward-looking or predictive.

**DF-5: Explain why the basic screen may be wrong.** If `basic_screen_result` exists, the agent must assess whether the screen pass/fail is misleading. If no basic screen exists, it should discuss which available financial trend metrics matter most.

**DF-6: Variant view is required unless impossible.** The agent should produce a variant view when plausible. If no variant view is identifiable, it must say so and explain what evidence is missing.

**DF-7: Consensus type must be categorized.** Use `consensus_type`: `narrative`, `estimate`, `positioning`, `mixed`, or `unknown`. If estimate or positioning consensus is asserted without source data, populate `consensus_verification_required`.

**DF-8: Theme fit must be explicit.** If `theme_context` exists, the agent must say whether the company is a primary, secondary, partial, indirect, or poor expression of mapped macro-supported themes.

**DF-9: Macro fit must be explicit.** If `macro_context` exists, the agent must discuss whether the macro backdrop helps or hurts the thesis.

**DF-10: Valuation/expectations must be addressed.** If `valuation_snapshot` or `price_snapshot` exists, the agent must discuss whether upside may already be priced in.

**DF-11: Falsification must be concrete.** The agent must provide specific business, financial, macro/theme, valuation, and timing falsifiers where possible.

**DF-12: No final verdict freelancing.** The agent may provide qualitative conviction and suggested score adjustments, but final verdict is computed by deterministic code.

**DF-13: Confidence must reflect data quality.** If data is sparse, synthesis confidence must be low. If financial context is high quality but company narrative/profile is sparse, confidence should be medium at best.

**DF-14: Avoid generic analyst language.** Output should be specific to the company and context. Generic statements like "monitor earnings" or "valuation risk exists" are insufficient unless tied to exact metrics, themes, or falsifiers.

**DF-15: Arbitrary ticker discipline.** For unknown tickers, the agent should still synthesize available financial, price, and valuation context, while clearly stating where business model, competitive position, and variant view are underdeveloped.

**DF-16: Schema validity is non-negotiable.** Output must pass Pydantic validation. One retry is allowed on validation failure. Raise `DeepFundamentalAgentValidationError` after retry exhaustion.

## Failure Modes

- Invented financial facts.
- Invented consensus.
- Generic variant view.
- Ignoring macro/theme context.
- Treating high price momentum as proof of fundamental quality.
- Treating low valuation as proof of cheapness.
- Failing to explain screen override logic.
- Missing falsification triggers.
- Overconfident output with sparse data.

## Versioning

This contract is v1. Material changes to agent scope, required output disciplines, or failure handling should bump the contract version and be reflected in `deep_fundamental_agent_prompts.py`.
