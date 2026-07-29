# Behavioral Scenario Rebase Survey

Date: 2026-07-29

Scope: read-only survey of narrative scenario taxonomy references across the Helix agent pipeline. This document maps where the five narrative macro scenarios are referenced, how tightly each reference is coupled, and what the implied rebase work is before switching the live pipeline to the six behavioral scenarios emitted by the frozen BVAR ensemble.

Narrative scenario ids surveyed:

- `reopening_soft_landing`
- `sticky_late_cycle_ai`
- `oil_inflation_tail`
- `late_cycle_risk_off`
- `ai_capex_rollover`

Behavioral scenario ids targeted:

- `expansion_disinflation`
- `late_cycle_expansion`
- `inflation_shock`
- `stagflation`
- `growth_scare_no_credit`
- `credit_led_recession`

## Executive Summary

Targeted search found 46 active source/config/data findings plus generated historical artifacts and test fixtures. Primary coupling breakdown for the findings below:

- `HARDCODED`: 15 findings. Narrative ids are embedded in logic, labels, probability floors, scenario impact maps, or exposure matrices.
- `CONFIG_READ`: 6 findings. Code reads `current_scenarios.yaml`, `current_regime.yaml`, or narrative-keyed return assumptions without hardcoding every id.
- `ABSTRACTED`: 11 findings. Code consumes generic scenario ids/probabilities and should mostly work if fed behavioral ids, though some schema caps block six scenarios.
- `TRANSLATION`: 5 findings. Code explicitly converts narrative probabilities to behavioral probabilities. These are temporary bridge points and mostly become deletion candidates.
- `STORED_FIELD`: 9 findings. Scenario ids are persisted on priorities, trade outcomes, exposure objects, current-regime handoffs, or generated macro artifacts.

Verdict: this is a surgical rebase, not a mechanical source swap. There is one reasonably clean live-cycle probability-source hook in `run_research_cycle.py`, but scenario identity also flows through the current scenario set, theme exposure matrix, current-regime handoff, existing-position compatibility logic, Monte Carlo return assumptions, reporting labels, frontend labels, and stored provenance fields. The clean path is to introduce a behavioral scenario source/adapter first, then repoint consumers in dependency order, then retire the narrative forecast and translation bridge.

## Per-Stage Findings

### 1. Macro Forecast

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/forecasting/macro_forecast_runner.py`, `DEFAULT_SCENARIO_PRIORS`, approx. lines 49-55 | Hardcoded priors for the five narrative ids. | `HARDCODED` | Delete/retire with v0 narrative forecast or replace with behavioral source if this runner survives as a shell. | Highest-risk v0 dependency. Any direct behavioral replacement must not leave these priors reachable as fallback. |
| `backend/src/agent_system/forecasting/macro_forecast_runner.py`, `default_scenario_set()`, approx. lines 144-234 | Builds five narrative `Scenario` objects with labels, probabilities, descriptions, implications, catalysts. | `HARDCODED` | Delete/retire or replace with behavioral scenario adapter sourced from `behavioral_scenarios.yaml`. | Current CLI can still fall back to this via `--default-scenarios`; must be disabled or behaviorally rebased. |
| `backend/src/agent_system/forecasting/macro_forecast_runner.py`, `run_macro_forecast()` and helpers, approx. lines 285-594 | Uses scenario set probabilities, ranks themes/sectors/factors, builds interpretation, probability shifters, and narrative-specific tensions. Direct branches for `sticky_late_cycle_ai`, `reopening_soft_landing`, `oil_inflation_tail`, `late_cycle_risk_off`, and `ai_capex_rollover`. | `HARDCODED` | Delete/retire v0 narrative engine. If reused for reporting, rewrite labels/shifters from behavioral metadata. | This is the old forecast's central logic. Repointing downstream without retiring this leaves two competing scenario systems. |
| `backend/src/agent_system/forecasting/input_signals.py`, approx. lines 453-1948 | Layer summaries, raw components, driver signals, falsifiers, and reconciliation logic assign `ScenarioImpact` entries to narrative ids. | `HARDCODED` | Delete/retire with v0 forecast, or fully rewrite impacts for behavioral ids if deterministic input-signal probability engine remains. | Very wide rewrite if kept. This is not just labels; it encodes old scenario semantics. |
| `backend/src/agent_system/forecasting/historical_calibration.py`, approx. lines 23-29 and 212-327 | Labels and maps historical analogue states to narrative ids. Special logic for `ai_capex_rollover` and `late_cycle_risk_off`. | `HARDCODED` | Retire as v0 narrative calibration, or replace with behavioral validation/calibration harness. | BVAR classifier/validation now owns behavioral history. Keeping this can reintroduce narrative probabilities. |
| `backend/src/agent_system/forecasting/scenario_probability_engine.py`, `update_scenario_probabilities()`, approx. line 280 | Generic Bayesian update from priors and `MacroInputSignal.scenario_impacts`; floors are passed via config/default schema. | `ABSTRACTED` | No change if retired. If reused, feed behavioral priors/impacts/floors only. | Engine itself is generic, but all active inputs and default floors around it are narrative. |
| `backend/src/agent_system/schemas/macro_forecast.py`, `ScenarioProbabilityConfig`, approx. lines 72-85 | Default `scenario_probability_floors` are keyed to narrative ids. | `HARDCODED` | Repoint floors to behavioral ids or remove if v0 probability engine retires. | Silent fallback risk: a behavioral forecast with no explicit config could still inherit narrative floors. |
| `backend/src/agent_system/diagnostics/input_matrix.py`, approx. lines 679-692 | Diagnostic probability update uses `DEFAULT_SCENARIO_PRIORS`. | `HARDCODED` | Rewrite or retire v0 diagnostic. | Diagnostic only, but can confuse operator validation if left narrative. |
| `backend/src/agent_system/diagnostics/input_ingestion_audit.py`, approx. lines 805-818 | Diagnostic probability update uses `DEFAULT_SCENARIO_PRIORS`. | `HARDCODED` | Rewrite or retire v0 diagnostic. | Diagnostic only. |
| `backend/src/agent_system/reporting/macro_forecast_docx.py`, approx. lines 162-205 and 1782-1790 | Renders scenario probabilities generically but labels the five narrative ids in `_scenario_name()`. | `HARDCODED` | Repoint label lookup to behavioral metadata. | Report may display raw behavioral ids or stale narrative labels otherwise. |
| `frontend/app/macro/page.tsx`, approx. lines 196-208 and embedded sample near line 1536 | `SCENARIO_LABELS`, `SCENARIO_DESC`, and offline sample are narrative-keyed. Normalizer reads probabilities generically. | `HARDCODED` | Repoint labels/descriptions/sample to behavioral metadata or endpoint payload. | UI can render unknown ids but labels/descriptions become wrong or missing. |
| Generated macro forecast artifacts under `backend/data/agent_system/reports/macro_forecasts/` and `data/agent_system/reports/macro_forecasts/` | Stored macro forecast JSON/YAML/docx outputs contain narrative probabilities and current-regime handoffs. | `STORED_FIELD` | Preserve as historical v0 artifacts with taxonomy marker; do not feed them into v1 without translation. | Historical rows/reports should remain readable, but "latest" pointers must not point at narrative artifacts after cutover. |

### 2. Theme / Sector / Factor Mapping

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/forecasting/theme_exposure_matrix.py`, `SCENARIO_THEME_EXPOSURES`, approx. lines 32-103 | Theme exposure matrix keyed by the five narrative ids. | `HARDCODED` | Rewrite/repoint to behavioral scenario metadata and returns in `behavioral_scenarios.yaml` or calibrated behavioral CSVs. | Drives `rank_themes()`, best/worst scenario provenance, theme support, and current-regime seed priorities. |
| `backend/src/agent_system/forecasting/theme_exposure_matrix.py`, `_scenario_label()` and `rank_themes()`, approx. lines 130-300 | Labels narrative ids and computes theme support by scenario probabilities. | `HARDCODED` | Repoint labels to behavioral metadata and exposure lookup to behavioral keys. | If behavioral ids are passed before rewrite, exposure lookups return zero and theme ranking loses signal. |
| `backend/src/agent_system/services/scenario_compatibility.py`, approx. lines 6 and 30-80 | Builds scenario compatibility from `SCENARIO_THEME_EXPOSURES`. | `HARDCODED` | Rewrite compatibility against behavioral exposure/correlation source. | Existing-position filter will treat unknown behavioral ids as low/no compatibility unless updated. |
| `data/reference/priority_theme_map.json`, line 8 | Maps one priority label directly to `oil_inflation_tail` even though this file is described as a theme-id map. | `HARDCODED` | Rewrite this mapping to a real theme id or behavioral exposure tag. | Small but sharp footgun: a narrative scenario id can masquerade as a theme id in downstream calibration. |
| `data/reference/scenario_return_assumptions.json`, lines 8-134 | Legacy JSON return assumptions keyed by the five narrative ids. | `CONFIG_READ` | Delete/archive after behavioral returns are active everywhere. | If calibrated CSVs are absent, `ScenarioAssumptionsLoader` can fall back to this narrative file. |
| `data/reference/scenario_market_returns.csv` and `data/reference/scenario_theme_returns.csv` | These CSVs are already keyed by behavioral ids. | `ABSTRACTED` | Prefer these explicitly or regenerate from `behavioral_scenarios.yaml`. | Good rebase anchor, but make sure no consumer silently falls back to the narrative JSON. |
| `backend/src/agent_system/services/scenario_assumptions_loader.py`, approx. lines 23-193 | Generic loader; default JSON path is narrative, but `prefer_calibrated_csv=True` means behavioral CSVs win when present. | `ABSTRACTED` | Make behavioral source explicit; remove legacy JSON fallback after cutover. | Monte Carlo is mostly behavioral-ready if this loader always resolves behavioral ids. |

### 3. Research Priority Generation

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/forecasting/research_agenda_builder.py`, approx. lines 20-30 | `_scenario_label()` maps narrative ids to labels. | `HARDCODED` | Repoint to behavioral scenario metadata. | Presentation and evidence text otherwise stay narrative. |
| `backend/src/agent_system/forecasting/research_agenda_builder.py`, approx. lines 78-160 | Priority templates and research agenda wording refer to old macro stories, especially AI capex rollover and late-cycle risk-off. | `HARDCODED` | Rewrite templates around behavioral scenarios and current-condition tilts. | This is where behavioral probabilities become actual research themes; likely needs human investment-content review. |
| `backend/src/agent_system/forecasting/research_agenda_builder.py`, approx. lines 177-232 | Writes `source_scenario_ids=list(theme.best_scenarios[:3])` into priority recommendations. | `STORED_FIELD` | Keep field but add taxonomy marker or migrate active rows. | Existing-position filter and outcome provenance depend on these ids. |
| `backend/src/agent_system/forecasting/current_regime_export.py`, approx. lines 268-338 | Converts macro forecast/theme rankings into `CurrentRegimeHandoff`, including `source_scenario_ids` and `scenario_probabilities`. | `STORED_FIELD` | Replace with behavioral current-condition export or repoint to behavioral scenario metadata. | This handoff is read by the live regime adapter and is a major cross-stage boundary. |
| `backend/src/agent_system/config/current_regime.yaml` | Active curated handoff contains narrative probabilities and seed priorities with narrative `source_scenario_ids`. | `CONFIG_READ` | Migrate or replace with `current_conditions.yaml` plus ensemble probabilities. | Live cycle can consume this file today; leaving it narrative creates taxonomy mismatch after probability source flips. |
| `backend/src/agent_system/adapters/regime.py`, approx. lines 89-142 and 174-187 | Reads `current_regime.yaml` and generically builds scenario probabilities. | `CONFIG_READ` | Repoint file/source; logic can mostly stay if the payload uses behavioral ids. | Generic adapter is useful, but source file and semantics must change together. |
| `backend/src/agent_system/schemas/current_regime.py`, approx. lines 19-44 | `CurrentRegimeSeedResearchPriority.source_scenario_ids` and `CurrentRegimeHandoff.scenario_probabilities`. | `STORED_FIELD` | Add taxonomy marker or versioned schema before behavioral/historical coexist. | Without marker, historical narrative and future behavioral ids are indistinguishable. |
| `backend/src/agent_system/schemas/regime.py`, approx. lines 272-279 and 393-405 | `ResearchPriority.source_scenario_ids`, `RegimeState.scenario_probabilities`, and `scenario_probability_source`. | `STORED_FIELD` | Preserve fields but add taxonomy/source marker and update producers. | Domain objects will carry behavioral ids after cutover, while old rows carry narrative ids. |

### 4. Conviction Gate Scenario Scoring

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/scenarios/types.py`, approx. lines 10-16 | `DEFAULT_SCENARIO_PRIORS` hardcoded to narrative ids. | `HARDCODED` | Delete/rebase defaults. | Used as fallback in cycle and scenario metrics; dangerous if behavioral probabilities are missing. |
| `backend/src/agent_system/scenarios/types.py`, approx. lines 86-95 | `ScenarioSet.scenarios` is capped at max length 5. | `ABSTRACTED` | Expand cap to six or remove cap. | Hard blocker for six behavioral scenarios even though the type is otherwise generic. |
| `backend/src/agent_system/scenarios/types.py`, approx. lines 178-257 | Weight resolution falls back to `DEFAULT_SCENARIO_PRIORS` when ids match narrative defaults. | `HARDCODED` | Remove narrative fallback, require explicit behavioral probabilities, or provide behavioral defaults from ensemble/source. | Prevents silent old-prior fallback. |
| `backend/src/agent_system/scenarios/scorer.py`, approx. lines 24-28 and 139-188 | LLM score batch caps `scenario_scores` at max length 5; scoring/order validation is generic. | `ABSTRACTED` | Expand cap to six and feed behavioral `ScenarioSet`. | Conviction gate can work after schema cap and scenario set source are changed. |
| `backend/src/agent_system/scenarios/loader.py`, approx. lines 22-83 | Reads `data/agent_system/scenarios/current_scenarios.yaml` and proposed/archive variants. | `CONFIG_READ` | Repoint loader or create a behavioral scenario-set adapter. | This is separate from `current_regime.yaml`; both must move. |
| `data/agent_system/scenarios/current_scenarios.yaml`, lines 5-148 | Active scenario set contains the five narrative scenarios and probabilities. | `CONFIG_READ` | Replace with behavioral equivalent or retire in favor of `behavioral_scenarios.yaml` plus ensemble probabilities. | Any code using `load_current_scenarios()` still sees narrative ids until this changes. |
| `backend/src/agent_system/scenarios/__main__.py`, approx. lines 77-150 | CLI shows/diffs/promotes current/proposed scenarios and scores a trade against current scenarios. | `CONFIG_READ` | Repoint CLI semantics to behavioral scenario sets or deprecate. | Operator tooling can mutate the wrong taxonomy if not updated. |
| `backend/src/agent_system/orchestration/run_research_cycle.py`, approx. lines 829-866 | Loads `load_current_scenarios()` and passes macro scenario probabilities into `score_trade_against_scenarios()`. | `CONFIG_READ` | Source scenario set and probabilities from the same behavioral provider. | Key dependency: probabilities and scenario set ids must match before conviction scoring. |

### 5. Existing-Position Filter and Cross-Hypothesis Logic

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/services/existing_position_filter.py`, approx. lines 129-139 and 195-200 | Compares candidate `source_scenario_ids` to held-record priority scenarios using `scenarios_compatible()`. | `STORED_FIELD` | Migrate compatibility logic and handle historical narrative ids. | A behavioral candidate compared with narrative historical holdings needs cross-taxonomy policy. |
| `backend/src/agent_system/services/scenario_compatibility.py`, approx. lines 6 and 30-80 | Compatibility matrix is derived from the narrative theme exposure matrix. | `HARDCODED` | Replace with behavioral compatibility/correlation source. | Without this, behavioral ids likely score as unrelated and duplicate-position filtering weakens. |
| `backend/src/agent_system/services/held_position_registry.py`, approx. lines 56-89 | Loads held records from trade outcomes and stores `priority_scenarios`. | `STORED_FIELD` | Add taxonomy marker or back-map historical rows during comparison. | Historical rows can be left as-is only if comparison logic knows their taxonomy. |
| `backend/src/agent_system/services/trade_outcome_builder.py`, approx. line 119 | Writes `originating_priority_scenarios` from `source_scenario_ids`. | `STORED_FIELD` | Continue writing ids, but add taxonomy metadata. | Stored trade outcomes become mixed-taxonomy after cutover. |
| `backend/src/agent_system/services/shadow_outcome_builder.py`, approx. lines 80-82 | Writes rejected/shadow outcome scenario provenance from `source_scenario_ids`. | `STORED_FIELD` | Continue writing ids with taxonomy metadata. | Same mixed-taxonomy concern as accepted outcomes. |
| `backend/src/agent_system/schemas/trade_outcome.py`, approx. line 85 | `originating_priority_scenarios: list[str]`. | `STORED_FIELD` | Add optional `scenario_taxonomy` or version field. | Historical provenance is ambiguous without external date-based inference. |
| `backend/src/agent_system/services/exposure_enrichment.py`, approx. lines 224-255 | Builds scenario exposure maps and scenario-weighted metrics keyed by scenario ids. | `STORED_FIELD` | No logic rewrite if fed behavioral `TradeScenarioAnalysis`; add taxonomy marker in stored output if persisted. | Exposure fields will mix narrative and behavioral ids across old/new outcomes. |

### 6. Portfolio Construction

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/agents/portfolio_agent.py`, approx. lines 27-40 and 193-230 | Stores and uses `scenario_weights_used`, expected returns, and scenario analysis generically. | `ABSTRACTED` | Mostly no-change after conviction gate feeds behavioral `TradeScenarioAnalysis`. | Needs six behavioral weights and assumptions upstream. |
| `backend/src/agent_system/orchestration/run_research_cycle.py`, approx. lines 884-891 | Passes `scenario_set=scenario_set` into `construct_portfolio()`. | `CONFIG_READ` | Ensure `scenario_set` is behavioral before this point. | Portfolio construction inherits the scenario taxonomy from conviction scoring. |

### 7. Monte Carlo

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/services/scenario_translation.py`, approx. lines 12-86 | Defines narrative-to-behavioral mapping and wrapper translation. | `TRANSLATION` | Delete after all consumers are natively behavioral. | Current bridge hides mixed taxonomy. Keep only until macro forecast cutover is complete. |
| `backend/src/agent_system/orchestration/run_research_cycle.py`, `_run_monte_carlo()`, approx. lines 384-392 | Uses `DEFAULT_SCENARIO_PRIORS` fallback, then `translate_narrative_to_behavioral()` before Monte Carlo. | `TRANSLATION` | Remove translation and feed ensemble behavioral probabilities directly. Remove narrative fallback. | This is the existing MC boundary already in behavioral space; after rebase, translation becomes redundant. |
| `backend/src/agent_system/orchestration/run_monte_carlo_standalone.py`, approx. lines 14-36 and 130-160 | Imports narrative defaults/translator and translates latest macro forecast probabilities. | `TRANSLATION` | Repoint standalone CLI to behavioral macro source; remove narrative fallback. | Backfill/inspection tool can otherwise keep using old macro artifacts. |
| `backend/src/agent_system/services/monte_carlo_engine.py`, approx. lines 40-56, 168-185, and theme return paths | Samples scenario ids generically and looks up market/theme assumptions by scenario id. | `ABSTRACTED` | No core change if assumptions loader resolves behavioral ids. | Needs behavioral return assumptions to be complete for every ensemble scenario. |
| `backend/src/agent_system/forecasting/macro_forecast_comparison.py`, approx. lines 20-65 | Translates narrative forecast probabilities to behavioral for shadow comparison. | `TRANSLATION` | Delete after shadow period ends or keep only for historical comparison tooling. | Not live-consumed, but useful during transition. |
| `scripts/calibrate_scenario_returns.py`, approx. lines 30 and 237-240 | Imports `SCENARIO_TRANSLATION` to print legacy mapping; outputs are otherwise behavioral. | `TRANSLATION` | Remove legacy mapping print after narrative retirement. | Low risk; calibration outputs already appear behavioral-keyed. |
| `scripts/recalibrate_from_backfill.py`, approx. lines 73-147 | Generic calibration writer keyed by `mapped_scenario_id`. | `ABSTRACTED` | No change if backfill rows are behavioral. | If fed old analogue rows, it will reproduce narrative-keyed assumptions. |
| `scripts/backfill_analogues.py`, approx. lines 26-32 and 107-110 | Hardcoded narrative `SCENARIO_IDS` and uses old analogue mapping. | `HARDCODED` | Rewrite or retire. | Backfill-generated calibration rows can keep narrative taxonomy alive. |

### 8. Trade Outcome / Decision Log

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/services/trade_outcome_builder.py`, approx. line 119 | Persists originating priority scenario ids on outcomes. | `STORED_FIELD` | Add taxonomy metadata going forward; do not mutate old rows unless needed. | Historical outcome analysis and held-position registry consume these ids. |
| `backend/src/agent_system/services/shadow_outcome_builder.py`, approx. lines 80-82 | Persists scenario provenance for rejected/shadow outcomes. | `STORED_FIELD` | Same as accepted outcomes. | Mixed taxonomy in rejected-outcome history. |
| `backend/src/agent_system/services/held_position_registry.py`, approx. lines 56-89 | Reads outcome provenance into held-position records. | `STORED_FIELD` | Add taxonomy-aware comparison/back-map. | Existing-position filtering is the main live consumer of old stored ids. |
| `backend/src/agent_system/orchestration/run_research_cycle.py`, decision-log assembly near the cycle output path | Targeted search found no direct narrative id literal in decision-log fields. Scenario provenance reaches decisions through trade ideas, scenario analysis, and outcomes. | `ABSTRACTED` | No direct change, but keep taxonomy marker in objects that decisions embed. | Decision logs may indirectly contain scenario ids if full trade/priority payloads are serialized. |

### 9. Excel Sync / Reporting

| Location | Reference | Coupling | Action | Blast radius |
| --- | --- | --- | --- | --- |
| `backend/src/agent_system/services/excel_sync.py` and related `*excel*` files | Targeted grep for scenario ids and stored scenario fields found no direct narrative scenario identity references. | `ABSTRACTED` | No direct taxonomy rebase found. | If Excel exports whole trade outcomes or scenario analysis fields indirectly, taxonomy markers should still travel with those objects. |
| `backend/src/agent_system/reporting/macro_forecast_docx.py` | See Macro Forecast section: labels are hardcoded, tables generic. | `HARDCODED` | Repoint labels to behavioral metadata. | Human-facing report must not label behavioral ids with old narrative names. |
| `frontend/app/macro/page.tsx` | See Macro Forecast section: labels/sample hardcoded, fetch normalization generic. | `HARDCODED` | Repoint labels/sample to behavioral metadata or payload. | UI is a visible place where mixed taxonomies will confuse operators. |

## Deletion Candidates

These can retire only after behavioral replacements are in place and all consumers are repointed.

- `backend/src/agent_system/services/scenario_translation.py`
  - Safe deletion condition: live macro source emits behavioral probabilities; Monte Carlo no longer calls translation; shadow comparison either retires or keeps a separate historical-only translator.
- Narrative internals of `backend/src/agent_system/forecasting/macro_forecast_runner.py`
  - Safe deletion condition: ensemble forecast is the live macro source and any required interpretation/theme outputs have behavioral replacements.
- `backend/src/agent_system/forecasting/input_signals.py` narrative impact maps
  - Safe deletion condition: v0 deterministic macro probability engine is fully retired or impacts are rewritten to behavioral.
- `backend/src/agent_system/forecasting/historical_calibration.py` narrative analogue mapping
  - Safe deletion condition: BVAR/classifier validation and behavioral calibration artifacts are the historical calibration source.
- `data/agent_system/scenarios/current_scenarios.yaml` and `proposed_scenarios.yaml`
  - Safe deletion condition: `load_current_scenarios()` no longer feeds live scoring, or the loader has been redefined to source behavioral scenario metadata.
- `DEFAULT_SCENARIO_PRIORS` in `macro_forecast_runner.py` and `scenarios/types.py`
  - Safe deletion condition: every live path requires explicit behavioral probabilities or obtains them from ensemble output.
- `data/reference/scenario_return_assumptions.json`
  - Safe deletion condition: `ScenarioAssumptionsLoader` always resolves behavioral CSVs or behavioral YAML-derived assumptions.
- `backend/src/agent_system/forecasting/current_regime_export.py` narrative-specific export pieces
  - Safe deletion condition: a behavioral current-regime/current-conditions export feeds the regime adapter and research agenda.
- Frontend/backend fixture samples containing narrative ids
  - Safe deletion condition: UI/reporting fixtures updated to behavioral ids.

## Stored-Data / Migration Concerns

Scenario ids are persisted or serialized in these places:

- `ResearchPriority.source_scenario_ids` in `backend/src/agent_system/schemas/regime.py`.
- `CurrentRegimeSeedResearchPriority.source_scenario_ids` and `CurrentRegimeHandoff.scenario_probabilities` in `backend/src/agent_system/schemas/current_regime.py`.
- `ResearchPriorityRecommendation.source_scenario_ids` in `backend/src/agent_system/schemas/macro_forecast.py`.
- `TradeOutcome.originating_priority_scenarios` in `backend/src/agent_system/schemas/trade_outcome.py`.
- `TradeScenarioAnalysis.scenario_scores` and `scenario_weights_used` via scenario scoring/exposure enrichment.
- Generated macro forecast JSON/YAML/docx artifacts in `backend/data/agent_system/reports/macro_forecasts/` and `data/agent_system/reports/macro_forecasts/`.
- Held-position registry records built from historical trade outcomes.

Migration recommendation:

1. Add a forward-looking taxonomy marker such as `scenario_taxonomy: "behavioral_v1"` or `scenario_id_namespace`.
2. Leave historical narrative rows intact as `narrative_v0`.
3. Add cross-taxonomy compatibility/back-map only where live comparison to old rows is required, especially existing-position filtering.
4. Avoid bulk rewriting historical rows unless a downstream report requires a single taxonomy; lineage preservation is more valuable than forced remapping.

## Return-Assumptions Question

Today there are two return-assumption sources with different taxonomy status.

Legacy narrative source:

- `data/reference/scenario_return_assumptions.json` is keyed by the five narrative ids and contains market/theme assumptions in the legacy JSON shape.
- `ScenarioAssumptionsLoader` still names this file as the default JSON fallback.

Behavioral-ready sources:

- `data/reference/scenario_market_returns.csv` and `data/reference/scenario_theme_returns.csv` are keyed by the six behavioral ids.
- `ScenarioAssumptionsLoader(prefer_calibrated_csv=True)` prefers these CSVs when both are present.
- `backend/src/agent_system/config/behavioral_scenarios.yaml` also contains `market_returns` and `theme_returns` inside each scenario block, but this shape is not the same as the legacy `ScenarioReturnAssumptions` JSON shape.

Consumers that must resolve behavioral returns:

- `backend/src/agent_system/services/monte_carlo_engine.py`: samples behavioral scenario ids and looks up market/theme returns.
- `backend/src/agent_system/services/scenario_assumptions_loader.py`: should stop falling back to narrative JSON after cutover.
- `backend/src/agent_system/orchestration/run_research_cycle.py`: `_run_monte_carlo()` should pass behavioral probabilities directly.
- `backend/src/agent_system/orchestration/run_monte_carlo_standalone.py`: should load behavioral forecast artifacts directly.
- `scripts/recalibrate_from_backfill.py` and `scripts/calibrate_scenario_returns.py`: should emit behavioral ids only.

Shape gap to resolve:

- The Monte Carlo loader expects a normalized assumptions object with market returns and theme return lookups by `scenario_id`.
- `behavioral_scenarios.yaml` stores richer scenario metadata and embedded returns but is not yet a direct `ScenarioAssumptions` payload.
- Rebase needs either a small adapter from `BehavioralScenario.market_returns/theme_returns` to `ScenarioAssumptionsLoader`'s runtime shape, or a generated behavioral assumptions file that replaces the legacy JSON.

## Ordering Constraints

Proposed safe rebase order:

1. Finalize behavioral scenario loader/source contract.
   - Use `backend/src/agent_system/forecasting/behavioral_scenarios_loader.py` and `backend/src/agent_system/config/behavioral_scenarios.yaml`.
   - Add a probability-bearing runtime wrapper sourced from ensemble output, not from the taxonomy YAML.
2. Update scenario schemas and caps.
   - Expand `ScenarioSet.scenarios` max length from 5 to 6.
   - Expand `_ScenarioScoreBatch.scenario_scores` max length from 5 to 6.
   - Remove or behaviorally replace `DEFAULT_SCENARIO_PRIORS`.
3. Introduce a single macro scenario source service.
   - Return `(taxonomy, probabilities, scenario_set, interpretation/current_conditions)`.
   - Support `macro_forecast_source: ensemble | narrative` during transition.
4. Repoint the live cycle probability source.
   - In `run_research_cycle.py`, replace direct narrative forecast probability extraction with the source service.
   - Ensure the scenario set ids and probability ids are the same before conviction scoring.
5. Repoint theme/sector/factor mapping.
   - Replace `SCENARIO_THEME_EXPOSURES` with behavioral metadata/returns.
   - Update `scenario_compatibility.py`.
   - Fix `priority_theme_map.json` line 8 so a narrative scenario id is not used as a theme id.
6. Repoint current-regime/current-conditions handoff.
   - Replace narrative `current_regime.yaml` consumption or migrate it to behavioral ids.
   - Update `current_regime_export.py` or retire it.
7. Remove Monte Carlo translation.
   - Feed behavioral probabilities directly.
   - Make behavioral return assumptions explicit and remove narrative JSON fallback.
8. Add stored-field taxonomy markers.
   - Priorities, trade outcomes, scenario analyses, exposure enrichment, current-regime handoffs.
   - Implement cross-taxonomy handling for existing-position filter.
9. Update reporting/frontend labels and fixtures.
   - Macro page labels/sample.
   - Macro forecast docx labels.
   - Any user-facing historical report needs taxonomy-aware labeling.
10. Update tests and delete v0 narrative-only modules.
   - Tests with hardcoded narrative ids are numerous and should move after runtime behavior is settled.

## Reversibility Hook

The cleanest live probability-source hook is in `backend/src/agent_system/orchestration/run_research_cycle.py`, approx. lines 421-436:

- The cycle loads the latest narrative macro forecast.
- `_scenario_probabilities_from_macro_forecast(narrative_forecast)` extracts probabilities.
- The result is stored as `macro_scenario_probabilities`.

This is where a reversible `macro_forecast_source: ensemble | narrative` switch should live.

However, a source switch at this point alone is not sufficient. The same cycle later calls `load_current_scenarios()` for the scenario set, and the current-regime adapter can still read `current_regime.yaml`. If probabilities switch to behavioral while `scenario_set` remains narrative, conviction scoring will fail or score against mismatched ids. Standalone consumers also read macro forecast artifacts independently:

- `/macro` frontend endpoint/latest forecast file.
- Macro forecast docx reporting.
- Deep fundamental macro context adapter.
- Standalone Monte Carlo CLI.
- Current-regime handoff/adapter.

Recommended reversibility structure:

- Add one macro scenario source service that returns the active taxonomy, probabilities, scenario metadata, and current-condition interpretation.
- Make `run_research_cycle.py`, macro API/reporting, and standalone tools call that service.
- Keep the narrative path behind the same interface until shadow-mode evaluation is complete.

With that interface, the flip is reversible. Without it, the source is effectively read in multiple places and the rebase becomes harder to roll back safely.

## Test and Fixture Blast Radius

Tests and fixtures with direct narrative ids include:

- `backend/src/agent_system/tests/test_macro_forecast.py`
- `backend/src/agent_system/tests/test_historical_calibration.py`
- `backend/src/agent_system/tests/test_scenarios.py`
- `backend/src/agent_system/tests/test_exposure_enrichment.py`
- `backend/src/agent_system/tests/test_adapter_regime.py`
- `backend/src/agent_system/tests/test_macro_forecast_docx.py`
- `backend/src/agent_system/tests/test_current_regime_export.py`
- `backend/src/agent_system/fixtures/macro_forecast_sample.json`

These are not live pipeline dependencies, but they will be a large test-update wave after the runtime rebase. The safest approach is to preserve narrative-v0 tests for retired modules until deletion, and add new behavioral-v1 tests for the new source/adapter path.

