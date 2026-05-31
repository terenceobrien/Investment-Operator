# Thematic Agent Contract v2

This document is the behavioral contract for the thematic agent that translates a `ResearchPriority` into a structured `ThematicMap` or `ClarificationRequest`. It exists separately from code comments because prompts, tests, and future harnesses should all reference the same contract. This is the second agent contract in the Helix agent system, following the structure established by the macro agent contract; subsequent agent contracts should use the same auditable pattern. This contract is longer than the macro agent's because `ThematicMap` and `Candidate` carry more fields, each with specific behavioral disciplines.

## Inputs

`priority` is the full `ResearchPriority` produced by the macro agent. The thematic agent reads all of it: `theme`, `rationale`, `edge_hypothesis`, `sub_questions`, and `supporting_evidence`. Critically, the agent does not modify or reframe the priority; it embeds the priority as-is in the returned `ThematicMap.source_priority`. Its value-add is the candidate set and `mapping_logic`, not a revised priority.

`regime_state` is the current structured `RegimeState`. The thematic agent uses regime context for its own grounding when assessing candidate fit, consensus views, and potential variant views.

`candidate_universe` is an optional explicit constraint on which tickers may be selected. In the v1 implementation it will generally be `None`; the parameter is reserved for future use if empirical evaluation supports a constrained universe.

`enable_clarification` controls whether the agent may return a `ClarificationRequest`. When false, the agent must produce a `ThematicMap` regardless of priority quality so the test harness can compare outputs without interruption.

The input deliberately does not include portfolio state because Workflow 2 is portfolio-agnostic. It also excludes prior thematic maps because each call is fresh, and it supplies no actual current consensus dataset: the agent operates on priors qualified by regime context and upstream evidence, subject to Rule TA-4.

## Outputs

The agent returns either a `ThematicMap` or a `ClarificationRequest`, never both. It must never return partial objects, mixed prose plus schema fragments, or a schema object with missing required fields. A `ThematicMap` embeds the full source priority in `source_priority`, not merely a storage identifier, so the candidate mapping remains traceable to the exact upstream thesis.

## Rules

**Rule TA-1 (Candidates must be directly implied by the priority's thesis).** A candidate must be tradeable on the SPECIFIC THESIS the priority articulated, not just sector-adjacent to its theme. If a priority's edge_hypothesis explicitly excludes a category (e.g., "the mispricing is not in upstream crude beta"), candidates in that excluded category are wrong selections. The agent must read the priority's thesis, not just its topic. This rule is structurally enforced via the thematic_fit field — see TA-3.

**Rule TA-2 (Variant_strength is preliminary, not validated).** At this stage, the agent does not have current sell-side data, positioning data, or detailed operating metrics. variant_strength reflects how clearly consensus can be identified and how distinct the potential variant view appears, given regime context and priors. Final variant validation happens at the single-name fundamental agent (Phase 2.3). The thematic agent is identifying WHICH candidates are worth deeper investigation, not validating that the edge holds.

**Rule TA-3 (Each candidate requires substantive thematic_fit, consensus_view, and (typically) potential_variant_view).** Every candidate must populate thematic_fit (specific tie to the priority — not generic "this is energy"), consensus_view (what the market thinks), and potential_variant_view (where consensus might be wrong). If the agent genuinely cannot articulate a variant view, leave that field empty AND set variant_strength=UNCLEAR. The empty-variant + UNCLEAR pairing is honest; vacuous-variant + non-UNCLEAR is a failure.

**Rule TA-4 (Consensus claims require grounding).** When asserting what consensus believes about a candidate, that claim must be (a) supported by the regime narrative, (b) drawn from the priority's existing supporting_evidence, or (c) explicitly qualified as a prior the agent cannot verify ("our prior is that consensus...", "consensus appears to be..."). The agent must NOT assert specific consensus views as fact without grounding. This rule mirrors macro agent MA-13 and is a permanent discipline — even with future data integration, the thematic agent will be making informed-prior judgments, not verified observations.

**Rule TA-5 (Selection logic must be auditable).** The agent must populate (a) mapping_logic with prose explaining the high-level selection rationale, (b) excluded with at least 2-3 ExclusionRecord entries naming candidates considered and rejected with specific reasons, and (c) universe_considered with a rough count of candidates evaluated before narrowing. This structurally enforces that the agent considered alternatives rather than just listing what came to mind.

**Rule TA-6 (Cover the priority's sub_questions).** The candidate set should collectively enable the priority's sub_questions to be answered. If a sub_question targets a specific segment (e.g., "which tanker companies have highest spot-rate exposure?"), the candidate set should include candidates from that segment. This prevents the thematic agent from drifting from the priority's framing.

**Rule TA-7 (Regime alignment is metadata, not a filter).** Candidates can be regime-aligned, regime-contrarian, or regime-neutral. The agent must not filter out regime-contrarian candidates just because they cut against the regime stance. If the priority itself is contrarian, the candidates will be too. The agent's job is to surface candidates that fit the priority's thesis, regardless of how that thesis relates to the regime.

**Rule TA-8 (No duplication within the candidate set).** Two candidates expressing the same thesis with different tickers should not both appear unless there is a meaningful difference in how each captures the thesis (e.g., FRO and STNG both capture tanker exposure but different ship types). The agent picks the cleanest expression of each distinct thesis-angle.

**Rule TA-9 (Variable candidate count: 5-15, agent decides).** The agent produces between 5 and 15 candidates per ThematicMap. Below 5 is pointlessly thin; above 15 invites universe-dumping. Within that range, the agent chooses based on how many distinct thesis-angles the priority actually supports. Separately, each candidate gets a priority_rank from 1-15 within the map — see TA-18 and TA-20.

**Rule TA-10 (Schema validity is non-negotiable).** Output must pass full Pydantic validation. One retry on ValidationError with feedback appended; ThematicAgentValidationError raised after retry exhausted. Silently producing invalid data is forbidden.

**Rule TA-11 (No invented tickers).** The agent must only use real tickers that actually trade. No hallucinated symbols, no rumored or pre-IPO names. If uncertain about a ticker, the agent must either skip that candidate or explicitly qualify the entry. This is the thematic agent's equivalent of the broader "no fabrication" discipline.

**Rule TA-12 (Clarification only when priority is genuinely insufficient).** The agent returns ClarificationRequest only when the priority's thesis is so abstract that no concrete candidate set is identifiable. Most priorities are researchable; the macro agent already produced the priority based on a confirmed input. Lazy clarification is a failure of the discipline. When uncertain, the agent narrows.

**Rule TA-13 (Theme tags must be populated and meaningful).** Each candidate's theme_tags list must contain 1-3 specific tags. Tags should match vocabulary used by the regime overlay where possible (energy, ai_power, long_duration, defense, etc.) so downstream portfolio constraint checks can use them. Generic tags like "stocks" or "equity" are forbidden.

**Rule TA-14 (Fit strength reflects real tie to the priority).** fit_strength is the agent's numerical (0-1) estimate of how directly the candidate maps to the priority's specific thesis. It must reflect actual fit, not be inflated to justify inclusion. Candidates with genuine fit_strength below approximately 0.4 probably do not belong in the candidate set — they should be exclusions instead. The 0.4 threshold is a soft guideline, not a hard rule, but agents producing many sub-0.4 candidates are likely padding the map.

**Rule TA-15 (Fit strength and variant strength are independent dimensions).** The agent must not let high fit_strength inflate variant_strength or vice versa. A candidate can have strong fit to the priority (fit_strength=0.8) while having an unclear variant view (variant_strength=UNCLEAR). The two answer different questions: fit_strength = "does this candidate match the priority?", variant_strength = "is there an articulable variant view yet?". The schema separates them; the agent must respect that separation.

**Rule TA-16 (Research depth recommendation must be calibrated).** Each candidate's recommended_research_depth (SHALLOW/STANDARD/DEEP) should reflect how much downstream investigation is warranted. DEEP is for top-rank candidates with strong variant views and meaningful catalysts. STANDARD is the default for clear candidates with moderate variant views. SHALLOW is for candidates with moderate fit and unclear variant views — where the question is whether to even investigate further. Defaulting everything to STANDARD is a failure of calibration.

**Rule TA-17 (Per-candidate catalysts should add information).** When the catalysts field on a candidate is populated, the entries should be name-specific events that matter for THIS candidate (e.g., "Q2 earnings on 2026-07-25," "FERC ruling expected Q3," "Capacity market auction Q4"). The regime-level macro catalysts (FOMC, CPI, PCE) are already in regime forward_context — duplicating them at the candidate level adds no information. Per-candidate catalysts should be name-specific or thematic-segment-specific to the candidate.

**Rule TA-18 (priority_rank within the map must be calibrated).** Each candidate receives a priority_rank from 1-15. Rank 1 is the most important candidate to investigate; rank 15 is meaningful but lower priority. Rank should reflect the combination of fit_strength, variant_strength, and catalyst clarity. Flat rankings (everything rank 1, everything rank 5) signal the agent didn't differentiate. The map should have a meaningful distribution of ranks across candidates.

**Rule TA-19 (Forward context must be engaged where relevant).** When evaluating candidates, the agent must engage with the regime's forward context (Fed path, inflation expectations, upcoming catalysts) where they materially affect the candidate's variant view. This rule applies in TWO specific cases that the agent must handle explicitly:

Case A — Direct contradiction: A candidate whose variant view requires conditions the forward path contradicts (e.g., long IWM when the Fed path shows hold-dominant pricing) must address that tension explicitly in potential_variant_view, and variant_strength should reflect the added uncertainty. Alternatively, the candidate should be excluded with the tension as the named reason.

Case B — Long-duration single-sector candidates: If any candidate is a long-duration single name (software, biotech, unprofitable growth, REITs, long-duration bonds) and the forward Fed path is restrictive (>=50% hold probability at the next FOMC), the candidate's variant view must explicitly address how the candidate holds up if the macro headwind persists. A variant view that argues for upside without acknowledging the duration/rate-sensitivity risk fails this rule.

Candidates that ignore the forward context when it's directly relevant fail TA-19.

**Rule TA-20 (priority_rank must be unique within the map).** Each candidate in a ThematicMap must have a unique priority_rank value. The rank range is 1 to 15 (allowing maps with up to 15 candidates to each get a distinct rank). The agent must NOT bucket multiple candidates at rank=10 or any other rank. If a map has 11 candidates, they receive ranks 1 through 11; if 15 candidates, ranks 1 through 15. Schema validation does not currently enforce uniqueness — this is a prompt-level discipline.

## Failure modes

- TA-A: Sector-adjacent but thesis-irrelevant candidates (priority explicitly excluded a category but candidates from it appear).

- TA-B: Generic consensus claims with no grounding or hedging.

- TA-C: Empty or vacuous potential_variant_view paired with non-UNCLEAR variant_strength (the empty+UNCLEAR pairing is acceptable).

- TA-D: Missing or vague mapping_logic that doesn't explain selection.

- TA-E: Hallucinated tickers (symbols that don't actually trade).

- TA-F: Over-uniform variant_strength ratings (everything STRONG or everything UNCLEAR across a candidate set).

- TA-G: Candidate set doesn't address the priority's sub_questions.

- TA-H: Inventing consensus (asserting specific consensus views as fact without grounding or hedging).

- TA-I: Universe-dumping (15 candidates where most are weak fits; fewer well-chosen candidates would have been better).

- TA-J: Insufficient or absent ExclusionRecord entries (no evidence that alternatives were considered).

- TA-K: Inflated fit_strength (>0.6) where the candidate genuinely doesn't fit the priority's specific thesis well.

- TA-L: Coupled fit_strength and variant_strength (the two move together when they should be independent).

- TA-M: All candidates rated STANDARD research depth (no differentiation).

- TA-N: Duplicated regime catalysts at the candidate level (adds no information).

- TA-O: Flat priority_rank distribution across candidates (no differentiation in importance).

- TA-P: Forward-context ignorance — candidate's variant view depends on conditions the forward Fed path or upcoming catalysts contradict, without acknowledging the tension. The agent treats the priority in isolation rather than engaging with the broader regime forward view. (Caught by TA-19; checkable both in human review and via pattern-matching for variant views that imply specific Fed path assumptions.)

- TA-Q: Rank collision — two or more candidates assigned the same priority_rank value. Typically appears as multiple candidates at rank=10 when the map has 11+ candidates. (Caught by TA-20; checkable structurally by counting distinct rank values vs candidate count.)

- TA-R: Generic catalysts — catalysts field populated but entries duplicate regime-level macros (FOMC, CPI, PCE, OPEC+) rather than candidate-specific events. The catalyst should be the kind of event that the fundamental agent would want to research for THIS specific candidate: earnings dates, contract awards, capacity auctions, regulatory rulings, dividend announcements, specific drug approvals, product launches, refinancing maturity dates. (Caught by TA-17; checkable by examining whether catalyst names overlap with regime forward_context.upcoming_catalysts entries.)

## Versioning

This contract is v2. Material rule semantics changed in TA-19 because Case B is new; TA-20 and failure modes TA-Q/TA-R are additions. Future material changes to rule semantics require bumping the contract version. The version should be referenced in commit messages whenever the contract changes. Contract version and prompt version are tracked separately; see `thematic_agent_prompts.py` constants.
