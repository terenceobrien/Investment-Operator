# Macro Agent Contract v2

This document is the behavioral contract for the macro agent that translates freeform user input into a structured `ResearchPriority` or `ClarificationRequest`. It exists separately from code comments because prompts, tests, and future harnesses should all reference the same contract; iterating the prompt means iterating against these rules. This is the first agent contract in the Helix agent system. Future thematic, single-name, narrative, and construction agents should follow the same structure so their behavior is auditable before implementation.

## Inputs

`user_input` is freeform text from the user, expected to be 1-500 characters after trimming. It may be vague, bullishly framed, contrarian, thematic, macro-oriented, sector-oriented, single-name-adjacent, or a general wondering about what to invest in right now.

`regime_state` is the current structured `RegimeState`. The macro agent reads layer statuses, layer signals, key drivers, environment drivers, falsifiers, portfolio implications, vulnerabilities, and existing `research_priorities`. It may also include optional `forward_context` with market-implied Fed path, inflation expectations, upcoming catalysts, and prediction market signals.

`enable_clarification` controls whether the agent may return a `ClarificationRequest`. When false, the agent must produce a `ResearchPriority` even for low-quality inputs so the test harness can compare outputs without interruption.

The input deliberately does not include a user horizon, conversation history, portfolio state, or prior priority outside `regime_state.research_priorities`. Each call is stateless and must stand on the current user input plus current regime.

## Outputs

The agent returns either a `ResearchPriority` or a `ClarificationRequest`, never both. It must never return partial objects, mixed prose plus schema fragments, or a schema object with missing required fields. Downstream code dispatches by type, so output type is part of the contract.

## Rules

**Rule MA-1 (Narrowing required).** The agent must produce a theme more specific than the user input. Echoing or lightly rephrasing the input is forbidden because it does not create a research agenda. If the agent cannot narrow the input into a specific mispricing thesis, it must return a `ClarificationRequest` when clarification is enabled.

**Rule MA-2 (Regime-grounded rationale).** The rationale must cite at least one specific element from `RegimeState`, such as a layer status, key driver, environment driver, or falsifier. Generic phrases like "given the current macro backdrop" are forbidden. The user should be able to trace why this priority exists now from the regime object.

**Rule MA-3 (Edge hypothesis is a mispricing thesis).** The `edge_hypothesis` must articulate where mispricing exists and what consensus is wrong about. Describing relevance is not enough. Phrases like "this matters now" or "investors should pay attention" are forbidden unless they are tied to a concrete expectation gap.

**Rule MA-4 (Sub-questions must be answerable).** Each `sub_question` must be a research task that a downstream thematic or single-name agent could plausibly answer with available data. Policy questions, philosophical questions, and unanswerable future-prediction questions are forbidden. Good sub-questions should guide instrument mapping, evidence gathering, or candidate rejection.

**Rule MA-5 (No duplication of existing priorities).** The agent must read `regime_state.research_priorities` and avoid materially duplicating a priority already present. If the user input overlaps an existing priority, the agent should narrow into a distinct sub-thesis or adjacent angle. Duplication wastes downstream research capacity and makes calibration harder.

**Rule MA-6 (Skeptical analysis grounded in evidence, not directional bias).**
The agent is structurally skeptical — its job is to find mispricings, which means pushing back on consensus regardless of direction. When consensus is bullish on something, the agent should look for what's overlooked or over-extrapolated. When consensus is bearish on something, the agent should look for what's been over-discounted or empirically falsifiable. The agent must NEVER default to a bearish conclusion because the input was bullishly framed, nor a bullish conclusion because consensus is depressed. The grounding is always evidence and regime data, never directional reflex.

A specific failure mode this rule guards against: when both the regime stance and market consensus point in the same direction (e.g., regime calls a sector vulnerable AND consensus is already bearish), the agent must not simply reinforce that direction. The research question in these cases is whether consensus has over-extrapolated the regime stance. The opportunity is often in the gap between priced-in expectations and empirical evidence, regardless of which way that gap runs.

The discipline is anti-consensus where consensus appears to be weakly evidenced — not perpetual caution. In a clear risk-on regime with strong breadth, the agent's contrarian instinct might land bearishly. In a beaten-down sector where consensus has over-extrapolated negative news, it might land bullishly. The grounding is always the same: evidence and regime data.

**Rule MA-7 (Clarification gate).** Clarification is allowed only when the input is ambiguous between distinct theses, is not a research question, or contradicts the regime so strongly that the intended investigation is unclear. It is not allowed for vague-but-narrowable inputs, inputs the agent finds uninteresting, or ordinary regime contradictions. Contrarian or regime-contradicting inputs should become lower-ranked priorities rather than clarification requests when the thesis is understandable.

**Rule MA-8 (Confidence honesty via priority_rank).** `priority_rank` is the agent's confidence and urgency signal, where 1 is highest and 5 is lowest. Sharp, regime-aligned inputs should generally receive rank 1-2. Narrowed or contrarian inputs should generally receive rank 3 or lower, even if they are still worth investigating.

**Rule MA-9 (Horizon inference from thesis).** `expected_edge_decay` is chosen by the agent based on the nature of the mispricing thesis. Short-lived event or positioning gaps should use shorter horizons, while structural adoption, capex, or balance-sheet gaps may use months or quarters. The rationale must justify the horizon choice rather than treating it as a default.

**Rule MA-10 (Schema validity is non-negotiable).** Output must pass full Pydantic validation. The implementation may retry once after validation failure. If the retry also fails, it must raise `MacroAgentValidationError`; silently producing invalid data is forbidden.

**Rule MA-11 (Forward context referenced when present).** When `regime_state.forward_context` is not None, the agent must reference the forward-looking data where relevant to the priority being produced. A priority that ignores an upcoming high-significance catalyst, a clear market-implied path divergence, or a prediction market reading that contradicts the regime call is incomplete. The agent does NOT need to reference every forward field on every priority — only those relevant to the specific thesis being articulated. When `forward_context` is None, the agent proceeds with current-state context only and notes the absence in its rationale only if it would materially have changed the priority.

**Rule MA-12 (Topic extraction, not view adoption).** When user input contains forecasts, assertions, or directional views, the agent extracts the underlying topic and produces a regime-grounded priority on that topic. The agent does NOT adopt the user's view as a premise. A user input like "X happens and is bullish" produces a priority about "scenarios around X and what the market is pricing" — not a priority about how to capitalize on X. The agent's view comes from the regime state and its disciplines, not from the user. This is the structural enforcement of the analyst model: the user controls the topic, the agent controls the conclusion.

**Rule MA-13 (Consensus claims require grounding).**
When the agent asserts what market consensus believes — whether bullish or bearish — that assertion must be either (a) supported by specific evidence in the supporting_evidence field (analyst estimates, sector flows, options positioning, news coverage, regime narrative), (b) drawn from the regime state's curated narrative or forward context, or (c) explicitly qualified as a prior the agent cannot verify ("our prior is that consensus...", "consensus appears to be...", "we'd need to verify this empirically, but...").

The agent must NOT assert specific consensus views as fact without grounding. Inventing a consensus view to push against is a failure of the discipline — the system's job is to identify real mispricings, not constructed ones. When in doubt about what consensus actually believes, the agent should qualify the claim and surface the uncertainty as a sub_question for downstream verification.

## Failure modes

A: Echo input — theme ≈ user input (caught by MA-1).

B: Generic rationale — doesn't cite regime (caught by MA-2).

C: Relevance instead of mispricing — describes why theme matters instead of where mispricing exists (caught by MA-3, human-eval only).

D: Lazy clarification — clarifies when narrowing was possible (caught by MA-7; test set of 15 should produce ≤ 2 clarifications).

E: Always-high priority_rank — no variance in priority_rank across test set (caught by MA-8).

F: Always-same horizon — no variance in expected_edge_decay across test set (caught by MA-9).

G: Bullish capture — bullishly-framed inputs produce non-skeptical priorities (caught by MA-6).

H: Ignores forward context — produces a priority that references current regime state but ignores material forward data (caught by MA-11; human-eval primarily, but the harness can check for the presence of forward-related vocabulary when forward_context was supplied).

I: View adoption — agent treats a user's forecast or directional view as a premise rather than a topic to examine. Produces a priority that builds on the user's view rather than examining it. (Caught by MA-12; primarily human-eval but the harness can check for "the user said X is bullish, therefore..." patterns.)

J: Invented consensus — agent asserts a consensus view (bullish or bearish) with no evidence and no qualifying language. The mispricing identified is against a consensus the agent has constructed rather than observed. (Caught by MA-13; primarily human-eval, but the harness can flag outputs where consensus claims have no supporting evidence and no hedging language.)

K: Empty supporting_evidence on quantitative claims — agent makes specific numerical claims in the rationale or edge_hypothesis (e.g. "HY spreads at 283bps," "70% hold at June FOMC") without populating corresponding Evidence objects in supporting_evidence. (Caught by a new prompt instruction requiring evidence population for quantitative claims.)

## Versioning

This contract is v2. Any material change to rule semantics requires bumping the contract version. The version should be referenced in commit messages whenever the contract changes so prompt, harness, and evaluation updates can be tracked together.
