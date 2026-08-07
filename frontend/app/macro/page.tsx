'use client';

import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useAuthFetcher } from '../../lib/api';
import AuthRequired from '@/components/AuthRequired';
import { M } from '../lib/researchOsTheme';

// ═══════════════════════════════════════════════════════════════════
// Macro & Regime
//
// Merges the old "Market overview" + "Macro insights" into one page.
//   1. Market pulse + current regime (five layer scores)
//   2. Dominant scenario banner
//   3. Scenario distribution (two-source behavioral mixture)
//   4. Analogue fan chart (directional macro-state matched episodes)
//   5. Positioning read + key tensions
//   6. Indicator explorer — all model inputs, filterable by layer
//   7. Market narrative (SPY) — snapshot, dominant themes, inefficiency map,
//      watchpoints — pulled from the same narrative endpoint the /narrative
//      page uses, with the ticker fixed to SPY.
//
// ── Wiring ──
// FORECAST_ENDPOINT returns the two_source_v1 macro_forecast JSON. Missing or
// stale artifacts render explicit panel errors rather than falling back.
// The narrative section reuses NARRATIVE_ENDPOINT(ticker) exactly as the
// /narrative page does.
// ═══════════════════════════════════════════════════════════════════

const FORECAST_ENDPOINT = '/api/macro/forecast/latest';
const FAN_ENDPOINT = '/api/macro/analogue-fan/latest';
const SCENARIO_META_ENDPOINT = '/api/macro/scenario-meta';
const LAYER_DETAIL_ENDPOINT = '/api/macro/layers/detail';
const REGIME_ENDPOINT = '/api/market/regime';
const REGIME_HISTORY_ENDPOINT = '/api/market/regime/history';
const INDICATOR_HISTORY_ENDPOINT = '/api/macro/indicator-history';
const NARRATIVE_TICKER = 'SPY';
const NARRATIVE_ENDPOINT = (ticker: string) => `/api/narrative/latest?ticker=${ticker}`;
const COMPONENT_HISTORY_ENDPOINT = (layerId: string, componentId: string, window: ComponentHistoryWindow) =>
  `/api/macro/layers/${encodeURIComponent(layerId)}/components/${encodeURIComponent(componentId)}/history?window=${window}`;

type AnyRecord = Record<string, unknown>;
type ScenarioMeta = { display_name: string; short_description: string };
type ScenarioMetaMap = Record<string, ScenarioMeta>;
type ScenarioMixtureRow = {
  bvar_soft?: number;
  analogue_implied?: number;
  final?: number;
  delta?: number;
  mixed_pre_floor?: number;
  floor_applied?: boolean;
};
type TopMatch = {
  neighbor_quarter: string;
  distance?: number;
  kernel_weight: number;
  resolved: boolean;
  recession_bound: boolean | null;
  onset_lag_quarters: number | null;
};
type ConditionalTiming = {
  elapsed_quarters: number;
  spent_mass: number;
  remaining_mass: number;
  conditional_share: number;
  share_shrunk: number;
  formula: string;
};
type WindowState = {
  quarter: string;
  state: string;
  share?: number | null;
  share_raw?: number | null;
  conditioned_share?: number | null;
  elapsed_quarters?: number | null;
  spent_mass?: number | null;
  remaining_mass?: number | null;
  no_timing_evidence?: boolean;
  timing_low_n?: boolean;
  top_matches?: TopMatch[];
  conditional_timing?: ConditionalTiming;
  onset_lag_distribution?: { conditional_timing?: ConditionalTiming; effective_n?: number; low_n?: boolean };
};
type AnalogueEvidenceReport = {
  query_date?: string;
  current_state?: string;
  spot_share?: number | null;
  trailing_max?: number | null;
  trailing_max_unconditioned?: number | null;
  trailing_max_conditioned?: number | null;
  s_used?: number | null;
  s_source?: string;
  binding_quarter?: string | null;
  stress_advisory?: boolean;
  kernel_weight_sum?: number | null;
  window_states?: WindowState[];
  trailing_max_onset_lag_distribution?: { conditional_timing?: ConditionalTiming; effective_n?: number; low_n?: boolean };
};
type MixtureReport = {
  alpha?: number;
  alpha_effective?: number;
  s?: number | null;
  s_source?: string;
  stress_advisory?: boolean;
  bvar_soft?: Record<string, number>;
  analogue_implied?: Record<string, number>;
  per_scenario?: Record<string, ScenarioMixtureRow>;
  membership_groups?: { recession?: string[]; non_recession?: string[] };
  evidence?: AnalogueEvidenceReport;
};
type MacroForecastPayload = AnyRecord & {
  asof_date?: string;
  horizon?: string;
  probability_mode?: string;
  forecast_interpretation?: AnyRecord;
  scenario_probabilities?: Record<string, number>;
  mixture_report?: MixtureReport;
  input_signals?: AnyRecord[];
  bvar_provenance?: AnyRecord;
};
type FanVariable = {
  variable: string;
  percentiles: Record<'p10' | 'p25' | 'p50' | 'p75' | 'p90', number[]>;
  effective_n: number[];
  median_recession_bound?: Array<number | null>;
  median_benign?: Array<number | null>;
  query_anchor_value: number;
  subset_notes?: Record<string, string>;
  units_note?: string;
};
type AnalogueFanPayload = {
  query_date: string;
  horizon_quarters: number;
  metadata?: { match_count?: number; match_kernel_weight_sum?: number; units_note?: string };
  variables: Record<string, FanVariable>;
};
type HistoryPoint = { date: string; value: number };
type IndicatorHistorySeries = {
  column: string;
  source: string;
  points: HistoryPoint[];
};
type IndicatorHistoryMap = Record<string, IndicatorHistorySeries>;
type LayerComponentDetail = {
  component_id: string;
  display_name: string;
  current_value: number | null;
  units_note: string | null;
  component_score: number | null;
  weight: number | null;
  weight_basis?: string | null;
  contribution: number | null;
  delta_1w: number | null;
  delta_1w_reason?: string | null;
  delta_1m: number | null;
  delta_1m_reason?: string | null;
  change_contribution_1m: number | null;
  history_available: boolean;
  history_source?: string | null;
  scored?: boolean;
  unscored_reason?: string | null;
};
type MacroLayerDetail = {
  layer_id: string;
  display_name: string;
  score: number | null;
  direction_label: string;
  status: string;
  delta_1m: number | null;
  delta_1m_reason?: string | null;
  components: LayerComponentDetail[];
};
type MacroLayersDetailPayload = {
  asof: string | null;
  history?: {
    start_date?: string | null;
    end_date?: string | null;
    source_counts?: Record<string, number>;
    warnings?: string[];
  };
  layers: MacroLayerDetail[];
};
type ComponentHistoryWindow = '90d' | '1y';
type ComponentHistoryPoint = { date: string; value: number; component_score?: number | null };
type LayerScoreHistoryPoint = { date: string; score: number | null };
type ComponentHistoryPayload = {
  layer_id: string;
  component_id: string;
  display_name: string;
  window: ComponentHistoryWindow;
  history_source?: string | null;
  series: ComponentHistoryPoint[];
  layer_score_series: LayerScoreHistoryPoint[];
  warnings?: string[];
};
type RegimeHistoryPayload = {
  snapshots?: Array<{
    date?: string;
    score_total?: number | null;
  }>;
  n?: number;
};

// ─────────────────────────────────────────────────────────────
// Generic safe accessors (mirrors the narrative page conventions)
// ─────────────────────────────────────────────────────────────
function safeObj(v: unknown): AnyRecord { return v && typeof v === 'object' ? (v as AnyRecord) : {}; }
function safeArray<X>(v: unknown): X[] { return Array.isArray(v) ? (v as X[]) : []; }
function safeStr(v: unknown, fallback = ''): string { return typeof v === 'string' ? v : fallback; }
function safeNum(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function truncate(s: string, max = 200): string {
  if (!s || s.length <= max) return s;
  return s.slice(0, max).trimEnd() + '…';
}
function firstNonEmpty(...vals: unknown[]): string {
  for (const v of vals) if (typeof v === 'string' && v.trim()) return v.trim();
  return '';
}
function titleCase(value: string): string {
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase());
}
function computeYDomain(values: Array<number | null | undefined>, padFraction = 0.05): [number, number] {
  const finite = values.filter((value): value is number => Number.isFinite(value));
  if (!finite.length) return [0, 1];
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const span = max - min;
  const magnitude = Math.max(Math.abs(min), Math.abs(max), 1);
  const minPad = Math.max(0.01, magnitude * 0.005);
  const pad = Math.max(span * padFraction, minPad);
  return [min - pad, max + pad];
}
function filterHistoryWindow(points: HistoryPoint[], days: number): HistoryPoint[] {
  const dated = points
    .map((point) => {
      const timestamp = new Date(`${point.date}T00:00:00`).getTime();
      return Number.isFinite(timestamp) ? { ...point, timestamp } : null;
    })
    .filter((point): point is HistoryPoint & { timestamp: number } => point !== null)
    .sort((a, b) => a.timestamp - b.timestamp);
  if (!dated.length) return [];
  const lastTimestamp = dated[dated.length - 1].timestamp;
  const cutoff = lastTimestamp - days * 24 * 60 * 60 * 1000;
  return dated
    .filter((point) => point.timestamp >= cutoff)
    .map((point) => ({ date: point.date, value: point.value }));
}
const pct1 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`);
const signedPct1 = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(1)}%`;
};
function errorMessage(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string') return error;
  return 'Forecast unavailable. Generate it with PYTHONPATH=backend python3 -m src.agent_system.forecasting.macro_forecast_runner --allow-stale-bvar.';
}

function normalizeIndicatorHistory(raw: unknown): IndicatorHistoryMap {
  const payload = safeObj(raw);
  const rawSeries = safeObj(payload.series);
  const out: IndicatorHistoryMap = {};

  for (const [column, value] of Object.entries(rawSeries)) {
    const series = safeObj(value);
    const points = safeArray<AnyRecord>(series.points)
      .map((point) => {
        const date = safeStr(point.date);
        const numeric = safeNum(point.value);
        return date && numeric !== null ? { date, value: numeric } : null;
      })
      .filter((point): point is HistoryPoint => point !== null);

    if (points.length) {
      out[column] = {
        column: safeStr(series.column, column),
        source: safeStr(series.source, 'unknown'),
        points,
      };
    }
  }

  return out;
}

function compactHistoryKey(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

const HISTORY_COLUMN_BY_LABEL: Record<string, string[]> = {
  [compactHistoryKey('Monetary layer')]: ['layer_monetary'],
  [compactHistoryKey('Credit layer health')]: ['layer_credit'],
  [compactHistoryKey('Volatility layer summary')]: ['layer_volatility'],
  [compactHistoryKey('Breadth and participation')]: ['layer_breadth'],
  [compactHistoryKey('Positioning and hedging')]: ['layer_positioning'],
  [compactHistoryKey('Net liquidity z-score')]: ['net_liquidity_z'],
  [compactHistoryKey('NFCI inverted')]: ['nfci_inverted'],
  [compactHistoryKey('M2 growth YoY')]: ['m2_growth_yoy'],
  [compactHistoryKey('Hy Spread Level')]: ['hy_spread_level'],
  [compactHistoryKey('Hy Spread Z')]: ['hy_spread_z'],
  [compactHistoryKey('Hy Spread Chg 4W')]: ['hy_spread_chg_4w'],
  [compactHistoryKey('Ig Spread Level')]: ['ig_spread_level'],
  [compactHistoryKey('Ig Spread Z')]: ['ig_spread_z'],
  [compactHistoryKey('Baa Spread Level')]: ['baa_spread_level'],
  [compactHistoryKey('Baa Spread Z')]: ['baa_spread_z'],
  [compactHistoryKey('Aaa Spread Level')]: ['aaa_spread_level'],
  [compactHistoryKey('Aaa Spread Z')]: ['aaa_spread_z'],
  [compactHistoryKey('Hyg Tlt Ratio Z')]: ['hyg_tlt_ratio_z'],
  [compactHistoryKey('Vix Level')]: ['vix_level'],
  [compactHistoryKey('Vix Z 20D')]: ['vix_z_20d'],
  [compactHistoryKey('Vix Term Slope')]: ['vix_term_slope'],
  [compactHistoryKey('Vix Change Pct 1D')]: ['vix_change_pct_1d'],
  [compactHistoryKey('Vvix Level')]: ['vvix_level'],
  [compactHistoryKey('Vvix Z')]: ['vvix_z'],
  [compactHistoryKey('Skew Index')]: ['skew_level'],
  [compactHistoryKey('Pct Above 200D')]: ['pct_above_200d'],
  [compactHistoryKey('Sectors Green')]: ['sectors_green'],
  [compactHistoryKey('Rsp Vs Spy Z')]: ['rsp_vs_spy_z'],
  [compactHistoryKey('RSP minus SPY participation proxy')]: ['rsp_minus_spy', 'rsp_vs_spy_z'],
  [compactHistoryKey('New Highs Minus Lows Z')]: ['new_highs_minus_lows_z'],
  [compactHistoryKey('Market tape sector dispersion')]: ['dispersion'],
  [compactHistoryKey('Cot Net Large Spec Z')]: ['cot_net_large_spec_z'],
  [compactHistoryKey('Aaii Bull Minus Bear')]: ['aaii_bull_minus_bear'],
  [compactHistoryKey('SPY return')]: ['ret_SPY_21d', 'ret_SPY_5d', 'ret_SPY_1d'],
  [compactHistoryKey('QQQ return')]: ['ret_QQQ_21d', 'ret_QQQ_5d', 'ret_QQQ_1d'],
  [compactHistoryKey('IWM return')]: ['ret_IWM_21d', 'ret_IWM_5d', 'ret_IWM_1d'],
  [compactHistoryKey('TLT return')]: ['ret_TLT_21d', 'ret_TLT_5d', 'ret_TLT_1d'],
  [compactHistoryKey('HYG return')]: ['ret_HYG_21d', 'ret_HYG_5d', 'ret_HYG_1d'],
  [compactHistoryKey('GLD return')]: ['ret_GLD_21d', 'ret_GLD_5d', 'ret_GLD_1d'],
  [compactHistoryKey('USO return')]: ['ret_USO_21d', 'ret_USO_5d', 'ret_USO_1d'],
  [compactHistoryKey('BTC return')]: ['ret_BTC-USD_21d', 'ret_BTC-USD_5d', 'ret_BTC-USD_1d'],
  [compactHistoryKey('RSP return')]: ['ret_RSP_21d', 'ret_RSP_5d', 'ret_RSP_1d'],
  [compactHistoryKey('HYG minus TLT risk-on proxy')]: ['hyg_tlt_ratio_z'],
  [compactHistoryKey('Spy Clv')]: ['spy_clv'],
  [compactHistoryKey('Spy Range Pct')]: ['spy_range_pct'],
  [compactHistoryKey('Spy Vol Z 20D')]: ['spy_vol_z_20d'],
  [compactHistoryKey('Volume Confirmation')]: ['volume_confirmation', 'spy_vol_z_20d'],
};

function snakeHistoryKey(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function historyCandidatesForSignal(signal: {
  label: string;
  name: string;
  role: string;
  parentLayer: string;
}): string[] {
  const candidates: string[] = [];
  const add = (items: string[] | undefined) => {
    for (const item of items ?? []) {
      if (item && !candidates.includes(item)) candidates.push(item);
    }
  };

  if (signal.role === 'layer_summary' && signal.parentLayer) {
    add([`layer_${signal.parentLayer}`]);
  }
  add(HISTORY_COLUMN_BY_LABEL[compactHistoryKey(signal.label)]);
  add(HISTORY_COLUMN_BY_LABEL[compactHistoryKey(signal.name)]);
  add([snakeHistoryKey(signal.label), snakeHistoryKey(signal.name)]);

  return candidates;
}

function resolveHistoryForSignal(
  history: IndicatorHistoryMap,
  signal: { label: string; name: string; role: string; parentLayer: string },
): IndicatorHistorySeries | null {
  for (const column of historyCandidatesForSignal(signal)) {
    const series = history[column];
    if (series?.points?.length) return series;
  }
  return null;
}

const LAYER_NAMES: Record<string, string> = {
  monetary: 'Monetary & Liquidity',
  credit: 'Credit & Stress',
  volatility: 'Volatility Structure',
  breadth: 'Breadth & Participation',
  positioning: 'Positioning & Sentiment',
  commodities: 'Commodities',
  earnings: 'Earnings',
};
const REGIME_LAYER_KEYS = ['monetary', 'credit', 'volatility', 'breadth', 'positioning'] as const;

function signalColor(sig: string): string {
  return sig === 'bullish' ? M.pos : sig === 'bearish' ? M.neg : M.warn;
}

// ─────────────────────────────────────────────────────────────
// Forecast normalization — walk the deep macro_forecast JSON into a
// flat shape the components render from. This is deliberately defensive:
// every field is optional so a partial payload still renders.
// ─────────────────────────────────────────────────────────────
function normalizeForecast(
  raw: MacroForecastPayload | null | undefined,
  history: IndicatorHistoryMap = {},
  scenarioMeta: ScenarioMetaMap = {},
  unavailableMessage: string | null = null,
) {
  const payload = safeObj(raw);
  const available = Boolean(raw) && !unavailableMessage;
  const fi = safeObj(payload.forecast_interpretation);
  const sp = safeObj(payload.scenario_probabilities) as Record<string, unknown>;
  const mixture = (payload.mixture_report ?? {}) as MixtureReport;
  const perScenario = mixture.per_scenario ?? {};
  const bvarSoft = mixture.bvar_soft ?? {};
  const analogueImplied = mixture.analogue_implied ?? {};
  const recessionGroup = new Set(mixture.membership_groups?.recession ?? []);

  const scenarios = Object.keys(sp)
    .map((id) => {
      const row = perScenario[id] ?? {};
      const blended = safeNum(sp[id]) ?? safeNum(row.final);
      const bvar = safeNum(row.bvar_soft) ?? safeNum(bvarSoft[id]);
      const analogue = safeNum(row.analogue_implied) ?? safeNum(analogueImplied[id]);
      const delta = safeNum(row.delta) ?? (bvar === null || blended === null ? null : blended - bvar);
      const meta = scenarioMeta[id];
      return {
        id,
        label: meta?.display_name ?? titleCase(id),
        desc: meta?.short_description ?? '',
        blended,
        bvar,
        analogue,
        delta,
        isRecession: recessionGroup.has(id),
      };
    })
    .sort((a, b) => (b.blended ?? Number.NEGATIVE_INFINITY) - (a.blended ?? Number.NEGATIVE_INFINITY));

  // Five layer summaries from input_signals where role === layer_summary
  const signals = safeArray<AnyRecord>(payload.input_signals);
  const layers = signals
    .filter((s) => safeStr(s.role) === 'layer_summary')
    .map((s) => ({
      layer: safeStr(s.parent_layer),
      name: LAYER_NAMES[safeStr(s.parent_layer)] ?? safeStr(s.parent_layer),
      score: safeNum(s.current_value),
      signal: safeStr(s.signal),
      trend: safeStr(s.trend),
    }));

  // Indicators — every input signal, grouped by category
  const indicators = signals.map((s) => {
    const cv = s.current_value;
    const label = safeStr(s.label) || safeStr(s.name);
    const name = safeStr(s.name);
    const role = safeStr(s.role);
    const parentLayer = safeStr(s.parent_layer);
    const historySeries = resolveHistoryForSignal(history, { label, name, role, parentLayer });
    return {
      label,
      cat: safeStr(s.category),
      layer: LAYER_NAMES[safeStr(s.category)] ?? safeStr(s.category),
      val: typeof cv === 'number' ? cv : safeStr(cv),
      signal: safeStr(s.signal),
      trend: safeStr(s.trend),
      conf: safeNum(s.confidence),
      role,
      unit: safeStr(s.unit),
      historyKey: historySeries?.column ?? '',
      historySource: historySeries?.source ?? '',
      history: historySeries?.points ?? [],
    };
  });

  const topScenario = scenarios[0];
  const layerScores = layers.map((l) => l.score).filter((score): score is number => score !== null);
  const composite = layerScores.length
    ? (layerScores.reduce((a, score) => a + score, 0) / layerScores.length) * 10
    : null;

  return {
    available,
    unavailableMessage,
    asof: safeStr(payload.asof_date),
    horizon: safeStr(payload.horizon),
    probMode: safeStr(payload.probability_mode),
    headline: safeStr(fi.headline),
    regimeRead: safeStr(fi.regime_read),
    summary: safeStr(fi.summary),
    confLevel: safeStr(fi.confidence_level),
    confRationale: safeStr(fi.confidence_rationale),
    dominantLabel: topScenario?.label ?? '',
    dominantProb: topScenario?.blended ?? null,
    preferred: safeArray<string>(fi.preferred_exposures),
    avoid: safeArray<string>(fi.exposures_to_avoid),
    tensions: safeArray<string>(fi.key_tensions),
    scenarios,
    mixture,
    evidence: mixture.evidence ?? null,
    layers,
    indicators,
    composite,
  };
}
type Forecast = ReturnType<typeof normalizeForecast>;
type ForecastDataState = {
  forecast: Forecast;
  isLoading: boolean;
  errorMessage: string | null;
};
const ForecastDataContext = createContext<ForecastDataState | null>(null);
function useForecastData(): ForecastDataState {
  const value = useContext(ForecastDataContext);
  if (!value) {
    throw new Error('ForecastDataContext missing');
  }
  return value;
}

type LiveRegimeLayer = {
  key: string;
  name: string;
  score: number | null;
  status: string;
};
type LiveRegime = {
  scoreTotal: number | null;
  layers: LiveRegimeLayer[];
  environment: string;
  confidence: number | null;
  asof: string;
  vixLevel: number | null;
};

function normalizeRegime(raw: unknown): LiveRegime | null {
  const regime = safeObj(raw);
  if (!Object.keys(regime).length) return null;

  const scoreComponents = safeObj(regime.score_components);
  const statuses = safeObj(regime.layer_statuses);

  const layers: LiveRegimeLayer[] = REGIME_LAYER_KEYS.map((key) => {
    const flatScore = safeNum(regime[`layer_${key}`]);
    const fallbackScore = safeNum(scoreComponents[key]);
    return {
      key,
      name: LAYER_NAMES[key],
      score: flatScore ?? fallbackScore,
      status: safeStr(statuses[key], 'neutral') || 'neutral',
    };
  });

  const layerScores = layers.map((layer) => layer.score).filter((score): score is number => score !== null);
  const inferredScoreTotal = layerScores.length
    ? (layerScores.reduce((sum, score) => sum + score, 0) / layerScores.length) * 10
    : null;
  const scoreTotal = safeNum(regime.score_total) ?? inferredScoreTotal;
  const hasLiveSignal =
    scoreTotal !== null ||
    layers.some((layer) => layer.score !== null) ||
    Boolean(safeStr(regime.environment)) ||
    Boolean(safeStr(regime.asof_date));
  if (!hasLiveSignal) return null;

  return {
    scoreTotal,
    layers,
    environment: safeStr(regime.environment),
    confidence: safeNum(regime.confidence),
    asof: safeStr(regime.asof_date),
    vixLevel: safeNum(regime.vix_level),
  };
}

function normalizeRegimeScoreHistory(raw: unknown): HistoryPoint[] {
  const payload = safeObj(raw);
  return safeArray<AnyRecord>(payload.snapshots)
    .map((snapshot) => {
      const date = safeStr(snapshot.date);
      const value = safeNum(snapshot.score_total);
      return date && value !== null ? { date, value } : null;
    })
    .filter((point): point is HistoryPoint => point !== null)
    .sort((a, b) => a.date.localeCompare(b.date));
}

// ─────────────────────────────────────────────────────────────
// Narrative extraction (SPY) — reads the same synthesis `result`
// object the /narrative page consumes.
// ─────────────────────────────────────────────────────────────
function parsePrefixedText(text: string): Record<string, string> {
  const prefixes = ['REALITY', 'STORY', 'PRICE', 'TIMEFRAME', 'GAP', 'ARCHETYPE', 'FALSIFIER'];
  const out: Record<string, string> = {};
  for (const p of prefixes) {
    const others = prefixes.filter((x) => x !== p).join('|');
    const re = new RegExp(`${p}[:\\s]+([\\s\\S]*?)(?=${others}|$)`, 'i');
    const m = text.match(re);
    if (m?.[1]?.trim()) out[p] = m[1].trim();
  }
  return out;
}

function extractSnapshot(data: AnyRecord) {
  const snap = (data.executive_snapshot ?? null) as AnyRecord | null;
  const fullSummary = safeStr(data.one_paragraph_summary);
  const isMissing = (v: string) => !v || /^not specified$/i.test(v) || /^mixed\s*\/\s*unclear$/i.test(v);
  if (snap) {
    const eb = (snap.executive_bullets ?? {}) as AnyRecord;
    const bullets = [
      { label: 'Reality', text: safeStr(eb.reality) },
      { label: 'Story', text: safeStr(eb.story) },
      { label: 'Price', text: safeStr(eb.price) },
    ];
    if (bullets.every((b) => !b.text) && fullSummary) {
      const s = fullSummary.split(/(?<=[.!?])\s+/).map((x) => x.trim()).filter(Boolean);
      if (s[0]) bullets[0].text = s[0];
      if (s[1]) bullets[1].text = s[1];
      if (s[2]) bullets[2].text = s.slice(2).join(' ');
    }
    return {
      regimeTone: isMissing(safeStr(snap.regime_tone)) ? '' : safeStr(snap.regime_tone),
      primaryGap: isMissing(safeStr(snap.primary_gap)) ? '' : safeStr(snap.primary_gap),
      primaryArchetype: isMissing(safeStr(snap.primary_archetype)) ? '' : safeStr(snap.primary_archetype),
      priceConfirmation: isMissing(safeStr(snap.price_confirmation)) ? '' : safeStr(snap.price_confirmation),
      confidence: safeNum(snap.confidence),
      bullets: bullets.filter((b) => b.text),
      fullSummary,
    };
  }
  // Minimal fallback for older snapshots.
  const bullets: { label: string; text: string }[] = [];
  if (fullSummary) {
    const s = fullSummary.split(/(?<=[.!?])\s+/).map((x) => x.trim()).filter(Boolean);
    if (s[0]) bullets.push({ label: 'Reality', text: s[0] });
    if (s[1]) bullets.push({ label: 'Story', text: s[1] });
    if (s[2]) bullets.push({ label: 'Price', text: s.slice(2).join(' ') });
  }
  return { regimeTone: '', primaryGap: '', primaryArchetype: '', priceConfirmation: '', confidence: null, bullets, fullSummary };
}

function normalizeThemes(data: AnyRecord) {
  return safeArray<AnyRecord>(data.dominant_narratives).map((n) => {
    const whyNow = safeStr(n.why_now);
    const parsed = parsePrefixedText(whyNow);
    const catalysts = safeArray<string>(n.key_catalysts);
    const wouldChange = safeArray<string>(n.what_would_change);
    return {
      title: safeStr(n.title),
      stance: safeStr(n.stance),
      confidence: safeNum(n.confidence),
      thesis: parsed.STORY ? '' : truncate(whyNow, 160),
      reality: parsed.REALITY || firstNonEmpty(...catalysts.slice(0, 1)),
      story: parsed.STORY || (parsed.REALITY ? '' : truncate(whyNow, 140)),
      price: parsed.PRICE || safeStr(n.price_action),
      gap: parsed.GAP || safeStr(n.gap),
      falsifier: parsed.FALSIFIER || wouldChange[0] || '',
      allFalsifiers: wouldChange,
    };
  });
}
type NarrTheme = ReturnType<typeof normalizeThemes>[0];

function extractInefficiency(data: AnyRecord, themes: NarrTheme[]) {
  const explicit = safeArray<AnyRecord>(data.inefficiency_map);
  if (explicit.length) {
    return explicit
      .map((r) => ({
        subject: safeStr(r.subject),
        gap: safeStr(r.gap),
        archetype: safeStr(r.archetype),
        confidence: safeNum(r.confidence),
        underlyingGapType: safeStr(r.underlying_gap_type),
      }))
      .filter((r) => r.subject && (r.gap || r.archetype));
  }
  return themes
    .map((t) => ({ subject: t.title, gap: t.gap, archetype: '', confidence: t.confidence, underlyingGapType: '' }))
    .filter((r) => r.subject && r.gap);
}

function extractWatchpoints(data: AnyRecord, themes: NarrTheme[]): string[] {
  const fromUnknowns = safeArray<string>(data.unknowns).filter(Boolean);
  const fromCounter = safeArray<string>(data.counter_narratives).filter(Boolean);
  const fromThemes = themes.flatMap((t) => [t.falsifier, ...t.allFalsifiers.slice(1)]).filter(Boolean);
  const seen = new Set<string>();
  const all = [...fromUnknowns, ...fromCounter, ...fromThemes].filter((s) => {
    const k = s.slice(0, 60).toLowerCase();
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return all.slice(0, 5);
}

const STANCE_COLOR: Record<string, string> = {
  bullish: M.pos, bearish: M.neg, neutral: M.warn, cautious: M.warn, mixed: M.warn,
};
const ROLE_ORDER: Record<string, number> = { layer_summary: 0, composite: 1, regime_driver: 2, scenario_falsifier: 3, raw_component: 4 };
const CATEGORY_ORDER = ['Monetary & Liquidity', 'Credit & Stress', 'Volatility Structure', 'Breadth & Participation', 'Positioning & Sentiment', 'Commodities', 'Earnings'];
type Indicator = Forecast['indicators'][number];

// ─────────────────────────────────────────────────────────────
// Dark-card Research OS primitives
// ─────────────────────────────────────────────────────────────
function Panel({ title, meta, children, prominent }: { title?: string; meta?: string; children: React.ReactNode; prominent?: boolean }) {
  return (
    <section style={{
      background: prominent ? '#0A1E36' : M.card,
      border: `1px solid ${prominent ? M.line2 : M.line}`,
      borderRadius: '16px',
      overflow: 'hidden',
      boxShadow: M.shadow,
    }}>
      <div style={{ padding: '18px' }}>
        {title ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', marginBottom: '12px' }}>
            <span style={{ fontFamily: M.mono, fontSize: '10.5px', letterSpacing: '0.18em', textTransform: 'uppercase', color: M.inkFaint, fontWeight: 600 }}>{title}</span>
            {meta ? <span style={{ fontFamily: M.mono, fontSize: '10.5px', letterSpacing: '0.08em', color: M.inkFaint }}>{meta}</span> : null}
          </div>
        ) : null}
        {children}
      </div>
    </section>
  );
}
function Chip({ label, color }: { label: string; color?: string }) {
  const isAccent = color === M.accent || color === M.accentBright;
  return (
    <span style={{
      display: 'inline-block',
      padding: '4px 10px',
      borderRadius: '999px',
      fontFamily: M.mono,
      fontSize: '10.5px',
      fontWeight: 600,
      letterSpacing: '0.04em',
      background: isAccent ? M.accentSoft : color ? `${color}22` : M.cardElev,
      color: isAccent ? M.accentBright : color ?? M.inkDim,
      border: `1px solid ${isAccent ? M.accent : color ? `${color}4D` : M.line2}`,
      textTransform: 'uppercase',
    }}>{label}</span>
  );
}
function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div style={{ fontFamily: M.mono, fontSize: '12px', letterSpacing: '0.2em', color: M.canvasInkFaint, marginBottom: '10px' }}>{children}</div>;
}
function MutedLabel({ children }: { children: React.ReactNode }) {
  return <div style={{ fontFamily: M.mono, fontSize: '10px', letterSpacing: '0.14em', textTransform: 'uppercase', color: M.inkFaint, fontWeight: 600, marginBottom: '10px' }}>{children}</div>;
}
const labelStyleSmall: React.CSSProperties = {
  fontFamily: M.mono,
  fontSize: 10,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: M.inkFaint,
  fontWeight: 600,
};
function ValueText({ value, size = 32, color = M.ink }: { value: string; size?: number; color?: string }) {
  return <span style={{ fontFamily: M.mono, fontSize: `${size}px`, fontWeight: 500, letterSpacing: '0', color }}>{value}</span>;
}
function SignalDot({ signal }: { signal: string }) {
  return <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: signalColor(signal), boxShadow: `0 0 0 3px ${signalColor(signal)}24`, flexShrink: 0 }} />;
}
function formatIndicatorValue(v: string | number): string {
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 1 });
    if (Math.abs(v) >= 100) return v.toFixed(1);
    return v.toFixed(2).replace(/\.00$/, '');
  }
  return truncate(String(v), 72);
}

// ─────────────────────────────────────────────────────────────
// Section 1: Market pulse + current regime
// ─────────────────────────────────────────────────────────────
function appendHistoryPoint(points: HistoryPoint[], point: HistoryPoint | null): HistoryPoint[] {
  if (!point) return points;
  const next = points.slice();
  const existingIndex = next.findIndex((item) => item.date === point.date);
  if (existingIndex >= 0) next[existingIndex] = point;
  else next.push(point);
  return next.sort((a, b) => a.date.localeCompare(b.date));
}

function MarketRegimePanel({
  f,
  regime,
  scoreHistory,
  scoreHistorySource,
  layerDetail,
  layerError,
  layerLoading,
  fetcher,
}: {
  f: Forecast;
  regime: LiveRegime | null;
  scoreHistory: HistoryPoint[];
  scoreHistorySource: string;
  layerDetail?: MacroLayersDetailPayload;
  layerError?: Error;
  layerLoading: boolean;
  fetcher: (url: string) => Promise<unknown>;
}) {
  const { isLoading, errorMessage } = useForecastData();
  const [expanded, setExpanded] = useState(false);
  const forecastUnavailable = !f.available;
  const composite = regime?.scoreTotal ?? f.composite;
  const runnerUp = forecastUnavailable ? undefined : f.scenarios[1];
  const probabilityGap = runnerUp && f.dominantProb !== null && runnerUp.blended !== null ? f.dominantProb - runnerUp.blended : null;
  const topBvar = forecastUnavailable ? undefined : f.scenarios
    .filter((scenario) => scenario.bvar !== null && scenario.bvar !== undefined)
    .sort((a, b) => (b.bvar ?? Number.NEGATIVE_INFINITY) - (a.bvar ?? Number.NEGATIVE_INFINITY))[0];
  const pulseLabel =
    regime?.environment ||
    (forecastUnavailable
      ? 'Forecast unavailable'
      : f.confLevel === 'high' ? 'Constructive, high conviction' : f.confLevel === 'low' ? 'Constructive, selective' : 'Mixed, watchful');
  const unavailableLabel = isLoading ? 'forecast loading' : errorMessage ? 'forecast unavailable' : 'forecast unavailable';
  const pulseMeta = regime ? `Regime · ${regime.asof || '—'}` : `Forecast fallback · ${f.asof || '—'}`;
  const chartPoints = appendHistoryPoint(
    scoreHistory,
    regime?.scoreTotal !== null && regime?.scoreTotal !== undefined && regime?.asof
      ? { date: regime.asof, value: regime.scoreTotal }
      : null,
  );
  useEffect(() => {
    if (process.env.NODE_ENV === 'production') return;
    if (scoreHistorySource === 'unavailable') return;
    if (chartPoints.length > 0 && chartPoints.length < 30) {
      console.warn('[macro] Regime score history rendered with fewer than 30 points', {
        pointCount: chartPoints.length,
        source: scoreHistorySource,
      });
    }
  }, [chartPoints.length, scoreHistorySource]);
  const heading = regime?.environment || (f.available ? f.dominantLabel : 'forecast unavailable');
  const layers = regime
    ? regime.layers
    : f.layers.map((l) => ({
        key: l.layer,
        name: l.name,
        score: l.score,
        status: l.signal || l.trend || 'neutral',
      }));
  return (
    <Panel title="Market pulse" meta={`${pulseMeta} · ${heading}`} prominent>
      <div className="macro-merged-pulse-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.9fr) 1px minmax(330px, 0.82fr)', gap: 18, alignItems: 'stretch' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '230px minmax(0, 1fr)', gap: 24, alignItems: 'start' }} className="macro-top-card-grid">
          <div>
            <h2 style={{ fontFamily: M.serif, fontSize: '27px', fontWeight: 500, color: M.ink, margin: 0, lineHeight: 1.03 }}>
              {pulseLabel}
            </h2>
            <div style={{ marginTop: 10 }}>
              <Chip label={forecastUnavailable ? unavailableLabel : `${pct1(f.dominantProb)} probability`} color={forecastUnavailable ? M.inkFaint : M.accent} />
            </div>
            {composite !== null ? (
              <div style={{ margin: '13px 0 2px' }}>
                <ValueText value={composite.toFixed(1)} size={38} />
                <div style={{ fontFamily: M.mono, fontSize: '10px', fontWeight: 600, letterSpacing: '0.14em', color: M.inkFaint, textTransform: 'uppercase', marginTop: 2 }}>composite regime score</div>
              </div>
            ) : null}
            <div style={{ color: M.pos, fontFamily: M.mono, fontSize: 12, marginTop: 10 }}>
              {regime?.confidence !== null && regime?.confidence !== undefined ? `${regime.confidence.toFixed(2)} confidence` : regime?.vixLevel !== null && regime?.vixLevel !== undefined ? `VIX ${regime.vixLevel.toFixed(1)}` : f.confLevel || '—'}
            </div>
            <div style={{ color: M.inkFaint, fontSize: 11.5, marginTop: 3 }}>current read</div>
            <a href="/how-it-works" style={{ display: 'inline-flex', gap: 8, alignItems: 'center', color: M.accentBright, textDecoration: 'none', fontSize: 12.5, marginTop: 9 }}>View methodology →</a>
          </div>
          <div>
            <div style={{ fontFamily: M.mono, fontSize: 10.5, letterSpacing: '0.12em', color: M.inkFaint, marginBottom: 5 }}>Regime score (90D)</div>
            <HistoryLineChart
              points={chartPoints}
              color={M.accentBright}
              height={205}
              yLabel="score"
            />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, marginTop: 10 }} className="macro-stat-list">
              <MiniStat label="Dominant" value={forecastUnavailable ? 'forecast unavailable' : f.dominantLabel || '—'} sub={forecastUnavailable ? 'unavailable' : pct1(f.dominantProb)} color={forecastUnavailable ? M.inkFaint : M.accentBright} />
              <MiniStat label="Runner-up" value={runnerUp?.label ?? '—'} sub={runnerUp ? pct1(runnerUp.blended) : '—'} />
              <MiniStat label="Gap" value={probabilityGap === null ? '—' : pct1(probabilityGap)} sub="dominant spread" color={probabilityGap !== null && probabilityGap > 0.08 ? M.pos : M.warn} />
              <MiniStat label="BVAR" value={topBvar?.label ?? '—'} sub={topBvar?.bvar !== null && topBvar?.bvar !== undefined ? pct1(topBvar.bvar) : '—'} />
            </div>
          </div>
        </div>
        <div className="macro-merged-separator" style={{ background: M.line, minHeight: 1 }} />
        <div>
          <div style={{ ...labelStyleSmall, marginBottom: 12 }}>Current regime read</div>
          <RegimeLayerRows layers={layers} />
        </div>
      </div>
      <div style={{ borderTop: `1px solid ${M.line}`, marginTop: 14, paddingTop: 10, display: 'flex', justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          style={{ border: 0, background: 'transparent', color: M.accentBright, cursor: 'pointer', fontFamily: M.sans, fontSize: 12.5, padding: 0 }}
        >
          {expanded ? 'Hide factor detail' : 'View factor detail'} →
        </button>
      </div>
      {expanded ? (
        <FactorDetailSection
          layerDetail={layerDetail}
          layerError={layerError}
          layerLoading={layerLoading}
          fetcher={fetcher}
        />
      ) : null}
    </Panel>
  );
}

function MiniStat({ label, value, sub, color = M.ink }: { label: string; value: string; sub: string; color?: string }) {
  return (
    <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 10, padding: '9px 10px', minWidth: 0 }}>
      <div style={{ ...labelStyleSmall, marginBottom: 5 }}>{label}</div>
      <div style={{ color, fontFamily: M.serif, fontSize: 15.5, lineHeight: 1.05, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</div>
      <div style={{ color: M.inkFaint, fontFamily: M.mono, fontSize: 10.5, marginTop: 5 }}>{sub}</div>
    </div>
  );
}

function RegimeLayerRows({ layers }: { layers: LiveRegimeLayer[] }) {
  return (
    <>
      {layers.map((l) => {
        const score = l.score;
        const status = l.status || 'neutral';
        return (
        <div key={l.key} style={{ marginBottom: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', marginBottom: '7px' }}>
            <span style={{ fontFamily: M.sans, fontSize: '13px', fontWeight: 600, color: M.ink }}>{l.name}</span>
            <span style={{ fontFamily: M.mono, fontSize: '11.5px', color: signalColor(status) }}>{score === null ? '—' : score.toFixed(1)}&nbsp;&nbsp;{titleCase(status)}</span>
          </div>
          <div style={{ height: '5px', background: M.well, borderRadius: '999px', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${score === null ? 0 : Math.min(100, score * 10)}%`, background: signalColor(status), borderRadius: '999px' }} />
          </div>
        </div>
        );
      })}
    </>
  );
}

function scoreNumber(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined ? '—' : v.toFixed(digits);
}
function signedScore(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toFixed(digits)}`;
}
function deltaColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return M.inkFaint;
  return v >= 0 ? M.pos : M.neg;
}
function valueWithUnits(value: number | null | undefined, units: string | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const suffix = units && !/score|z-score|ratio|index/i.test(units) ? ` ${units}` : '';
  return `${formatAxisNumber(value)}${suffix}`;
}
function defaultLayerId(layers: MacroLayerDetail[]): string | null {
  if (!layers.length) return null;
  const withDelta = layers.filter((layer) => layer.delta_1m !== null && layer.delta_1m !== undefined);
  const candidates = withDelta.length ? withDelta : layers;
  return candidates
    .slice()
    .sort((a, b) => Math.abs(b.delta_1m ?? 0) - Math.abs(a.delta_1m ?? 0))[0]?.layer_id ?? null;
}
function MiniSparkline({ points, color = M.accentBright }: { points: HistoryPoint[]; color?: string }) {
  const data = points.filter((point) => Number.isFinite(point.value)).slice(-60);
  if (data.length < 2) return <span style={{ color: M.inkFaint }}>no stored history</span>;
  const values = data.map((point) => point.value);
  const [min, max] = computeYDomain(values, 0.06);
  const width = 106;
  const height = 30;
  const x = (index: number) => (index / Math.max(1, data.length - 1)) * (width - 4) + 2;
  const y = (value: number) => 3 + (1 - (value - min) / (max - min)) * (height - 6);
  const path = data.map((point, index) => `${x(index)},${y(point.value)}`).join(' L');
  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 30, display: 'block' }}>
      <path d={`M${path}`} fill="none" stroke={color} strokeWidth={1.4} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function ComponentSparkline({
  layerId,
  component,
  fetcher,
}: {
  layerId: string;
  component: LayerComponentDetail;
  fetcher: (url: string) => Promise<unknown>;
}) {
  const typedFetcher = (url: string) => fetcher(url) as Promise<ComponentHistoryPayload>;
  const { data, error, isLoading } = useSWR<ComponentHistoryPayload>(
    component.history_available ? COMPONENT_HISTORY_ENDPOINT(layerId, component.component_id, '90d') : null,
    typedFetcher,
    { revalidateOnFocus: false },
  );
  if (!component.history_available) return <span style={{ color: M.inkFaint }}>no stored history</span>;
  if (isLoading) return <span style={{ color: M.inkFaint }}>loading</span>;
  if (error) return <span style={{ color: M.neg }}>history error</span>;
  const points = (data?.series ?? []).map((point) => ({ date: point.date, value: point.value }));
  return <MiniSparkline points={points} color={deltaColor(component.change_contribution_1m)} />;
}
type ComponentChartRow = {
  date: string;
  value: number;
  componentScore: number | null;
  layerScore: number | null;
};
function normalizeComponentChartRows(history: ComponentHistoryPayload | undefined): ComponentChartRow[] {
  const layerByDate = new Map(
    (history?.layer_score_series ?? [])
      .filter((point) => point.score !== null && point.score !== undefined)
      .map((point) => [point.date, point.score]),
  );
  return (history?.series ?? []).map((point) => ({
    date: point.date,
    value: point.value,
    componentScore: point.component_score ?? null,
    layerScore: layerByDate.get(point.date) ?? null,
  }));
}
function ComponentHistoryTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ payload?: ComponentChartRow }>; label?: string }) {
  const row = payload?.find((item) => item.payload)?.payload;
  if (!active || !row) return null;
  return (
    <div style={{ background: M.cardElev, border: `1px solid ${M.line2}`, borderRadius: 8, padding: '9px 10px', color: M.ink, fontFamily: M.mono, fontSize: 10.5 }}>
      <div style={{ color: M.inkFaint, marginBottom: 5 }}>{label}</div>
      <div>value {formatAxisNumber(row.value)}</div>
      <div>score {scoreNumber(row.componentScore)}</div>
      <div style={{ color: M.inkFaint }}>layer {scoreNumber(row.layerScore)}</div>
    </div>
  );
}
function ComponentHistoryChart({
  layerId,
  component,
  fetcher,
}: {
  layerId: string;
  component: LayerComponentDetail | null;
  fetcher: (url: string) => Promise<unknown>;
}) {
  const [windowValue, setWindowValue] = useState<ComponentHistoryWindow>('90d');
  const [showLayer, setShowLayer] = useState(true);
  const typedFetcher = (url: string) => fetcher(url) as Promise<ComponentHistoryPayload>;
  const { data, error, isLoading } = useSWR<ComponentHistoryPayload>(
    component?.history_available ? COMPONENT_HISTORY_ENDPOINT(layerId, component.component_id, windowValue) : null,
    typedFetcher,
    { revalidateOnFocus: false },
  );

  if (!component) return <EmptyMini message="Select a component to inspect its history." />;
  if (!component.history_available) return <EmptyMini message="No stored history exists for this component in the indicator-history cache." />;
  if (isLoading) return <EmptyMini message="Loading component history." />;
  if (error) return <ErrorMini message={error.message} />;

  const rows = normalizeComponentChartRows(data);
  if (rows.length < 2) return <EmptyMini message="Component history is too sparse to chart." />;
  const valueDomain = computeYDomain(rows.map((row) => row.value));
  const layerDomain = computeYDomain(rows.map((row) => row.layerScore));
  return (
    <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <div style={labelStyleSmall}>Component history</div>
          <h3 style={{ margin: '6px 0 0', fontFamily: M.serif, fontSize: 19, fontWeight: 500, color: M.ink }}>{component.display_name}</h3>
        </div>
        <div style={{ display: 'flex', gap: 7, alignItems: 'center', flexWrap: 'wrap' }}>
          {(['90d', '1y'] as ComponentHistoryWindow[]).map((item) => (
            <button key={item} type="button" onClick={() => setWindowValue(item)} style={{
              background: windowValue === item ? M.accentSoft : M.cardElev,
              color: windowValue === item ? M.accentBright : M.inkDim,
              border: `1px solid ${windowValue === item ? M.accent : M.line2}`,
              borderRadius: 8,
              padding: '6px 9px',
              fontFamily: M.mono,
              fontSize: 10,
              cursor: 'pointer',
            }}>{item}</button>
          ))}
          <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center', color: M.inkDim, fontFamily: M.sans, fontSize: 11.5 }}>
            <input type="checkbox" checked={showLayer} onChange={(event) => setShowLayer(event.target.checked)} />
            layer overlay
          </label>
        </div>
      </div>
      <div style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: showLayer ? 34 : 12, bottom: 6, left: 0 }}>
            <CartesianGrid stroke={M.line2} strokeDasharray="3 3" opacity={0.55} />
            <XAxis dataKey="date" tick={{ fill: M.inkFaint, fontFamily: M.mono, fontSize: 10 }} axisLine={{ stroke: M.line2 }} tickLine={{ stroke: M.line2 }} />
            <YAxis yAxisId="left" domain={valueDomain} tickFormatter={(value) => formatAxisNumber(Number(value))} tick={{ fill: M.inkFaint, fontFamily: M.mono, fontSize: 10 }} axisLine={{ stroke: M.line2 }} tickLine={{ stroke: M.line2 }} width={48} />
            {showLayer ? <YAxis yAxisId="right" orientation="right" domain={layerDomain} tickFormatter={(value) => formatAxisNumber(Number(value))} tick={{ fill: M.inkFaint, fontFamily: M.mono, fontSize: 10 }} axisLine={{ stroke: M.line2 }} tickLine={{ stroke: M.line2 }} width={34} /> : null}
            <Tooltip content={<ComponentHistoryTooltip />} />
            <Line yAxisId="left" type="monotone" dataKey="value" stroke={M.accentBright} strokeWidth={2} dot={false} isAnimationActive={false} />
            {showLayer ? <Line yAxisId="right" type="monotone" dataKey="layerScore" stroke={M.warn} strokeWidth={1.7} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} /> : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontFamily: M.sans, fontSize: 11.5, color: M.inkDim, marginTop: 8 }}>
        <LegendSwatch color={M.accentBright} label={`${component.display_name} value`} />
        {showLayer ? <LegendSwatch color={M.warn} label="parent layer score" /> : null}
      </div>
    </div>
  );
}
function FactorDetailSection({
  layerDetail,
  layerError,
  layerLoading,
  fetcher,
}: {
  layerDetail?: MacroLayersDetailPayload;
  layerError?: Error;
  layerLoading: boolean;
  fetcher: (url: string) => Promise<unknown>;
}) {
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null);
  const [selectedComponentId, setSelectedComponentId] = useState<string | null>(null);

  if (layerLoading) return <div style={{ marginTop: 14 }}><EmptyMini message="Loading factor detail." /></div>;
  if (layerError) return <div style={{ marginTop: 14 }}><ErrorMini message={layerError.message} /></div>;
  const layers = layerDetail?.layers ?? [];
  if (!layers.length) return <div style={{ marginTop: 14 }}><ErrorMini message="Macro layer detail unavailable. Refresh the latest regime snapshot and forecast artifacts." /></div>;

  const fallbackLayerId = defaultLayerId(layers);
  const activeLayerId = selectedLayerId && layers.some((layer) => layer.layer_id === selectedLayerId) ? selectedLayerId : fallbackLayerId;
  const activeLayer = layers.find((layer) => layer.layer_id === activeLayerId) ?? layers[0];
  const primaryDriver = activeLayer.components.find((component) => component.change_contribution_1m !== null) ?? activeLayer.components[0] ?? null;
  const activeComponent = activeLayer.components.find((component) => component.component_id === selectedComponentId) ?? primaryDriver;
  const warnings = layerDetail?.history?.warnings ?? [];

  return (
    <div style={{ borderTop: `1px solid ${M.line}`, marginTop: 14, paddingTop: 14 }}>
      {warnings.length ? (
        <div style={{ background: M.dangerWell, border: `1px solid ${M.warn}55`, color: M.warn, borderRadius: 10, padding: '8px 10px', fontFamily: M.sans, fontSize: 11.5, lineHeight: 1.4, marginBottom: 10 }}>
          History source warning: {truncate(warnings.join(' · '), 240)}
        </div>
      ) : null}
      <div className="macro-factor-grid" style={{ display: 'grid', gridTemplateColumns: '260px minmax(0, 1fr)', gap: 14, alignItems: 'start' }}>
        <div style={{ background: M.cardElev, border: `1px solid ${M.line}`, borderRadius: 12, padding: 10 }}>
          <div style={{ ...labelStyleSmall, padding: '2px 4px 9px' }}>Layer selector</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {layers.map((layer) => {
              const active = layer.layer_id === activeLayer.layer_id;
              return (
                <button key={layer.layer_id} type="button" onClick={() => { setSelectedLayerId(layer.layer_id); setSelectedComponentId(null); }} style={railRowStyle(active)}>
                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{layer.display_name}</span>
                    <span style={{ display: 'block', marginTop: 4, color: deltaColor(layer.delta_1m), fontFamily: M.mono, fontSize: 10 }}>1M {signedScore(layer.delta_1m)}</span>
                  </span>
                  <span style={{ fontFamily: M.mono, color: signalColor(layer.status || 'neutral') }}>{scoreNumber(layer.score, 1)}</span>
                </button>
              );
            })}
          </div>
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-end', marginBottom: 10 }}>
            <div>
              <div style={labelStyleSmall}>Component attribution</div>
              <h3 style={{ margin: '6px 0 0', fontFamily: M.serif, fontSize: 21, fontWeight: 500, color: M.ink }}>{activeLayer.display_name}</h3>
            </div>
            <div style={{ fontFamily: M.mono, color: deltaColor(activeLayer.delta_1m), fontSize: 12 }}>1M layer {signedScore(activeLayer.delta_1m)}</div>
          </div>
          <div style={{ overflowX: 'auto', border: `1px solid ${M.line}`, borderRadius: 12 }}>
            <div style={{ minWidth: 900 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(190px, 1.45fr) 105px 72px 72px 92px 82px 116px 132px', gap: 8, padding: '9px 10px', background: M.cardElev, borderBottom: `1px solid ${M.line}`, ...labelStyleSmall }}>
                <span>component</span><span>value</span><span>score</span><span>weight</span><span>contrib</span><span>1M delta</span><span>1M attribution</span><span>history</span>
              </div>
              {activeLayer.components.map((component, index) => {
                const selected = activeComponent?.component_id === component.component_id;
                const driver = primaryDriver?.component_id === component.component_id && component.change_contribution_1m !== null;
                return (
                  <button
                    key={component.component_id}
                    type="button"
                    onClick={() => setSelectedComponentId(component.component_id)}
                    style={{
                      width: '100%',
                      display: 'grid',
                      gridTemplateColumns: 'minmax(190px, 1.45fr) 105px 72px 72px 92px 82px 116px 132px',
                      gap: 8,
                      padding: '10px',
                      border: 0,
                      borderBottom: index === activeLayer.components.length - 1 ? 0 : `1px solid ${M.line}`,
                      background: selected ? M.accentSoft : M.well,
                      color: M.inkDim,
                      textAlign: 'left',
                      alignItems: 'center',
                      cursor: 'pointer',
                    }}
                  >
                    <span style={{ color: M.ink, fontFamily: M.sans, fontSize: 12.5, fontWeight: 600, minWidth: 0 }}>
                      {component.display_name}
                      {driver ? <span style={{ marginLeft: 7 }}><Chip label="primary driver" color={M.accentBright} /></span> : null}
                      {!component.scored && component.unscored_reason ? <span style={{ display: 'block', color: M.inkFaint, fontSize: 10.5, fontWeight: 400, marginTop: 3 }}>{component.unscored_reason}</span> : null}
                    </span>
                    <span style={{ fontFamily: M.mono, fontSize: 11.5 }}>{valueWithUnits(component.current_value, component.units_note)}</span>
                    <span style={{ fontFamily: M.mono, fontSize: 11.5 }}>{scoreNumber(component.component_score)}</span>
                    <span style={{ fontFamily: M.mono, fontSize: 11.5 }}>{component.weight === null ? '—' : `${(component.weight * 100).toFixed(0)}%`}</span>
                    <span style={{ fontFamily: M.mono, fontSize: 11.5 }}>{scoreNumber(component.contribution)}</span>
                    <span style={{ fontFamily: M.mono, fontSize: 11.5, color: deltaColor(component.delta_1m) }}>{signedScore(component.delta_1m)}</span>
                    <span style={{ fontFamily: M.mono, fontSize: 11.5, color: deltaColor(component.change_contribution_1m) }}>{signedScore(component.change_contribution_1m)}</span>
                    <span style={{ fontFamily: M.mono, fontSize: 10.5 }}>
                      <ComponentSparkline layerId={activeLayer.layer_id} component={component} fetcher={fetcher} />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            <ComponentHistoryChart layerId={activeLayer.layer_id} component={activeComponent} fetcher={fetcher} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Scenario distribution
// ─────────────────────────────────────────────────────────────
function ScenarioCards({ f }: { f: Forecast }) {
  if (!f.available) {
    return <Panel title="Scenario explorer" meta="forecast unavailable"><ErrorMini message={f.unavailableMessage ?? 'Forecast unavailable.'} /></Panel>;
  }
  const alpha = f.mixture.alpha ?? null;
  const bvarWeight = alpha === null ? null : 1 - alpha;
  const analogueWeight = alpha;
  const evidence = f.evidence;
  const sUsed = evidence?.s_used ?? f.mixture.s ?? null;
  const bindingQuarter = evidence?.binding_quarter ?? null;
  return (
    <Panel title="Scenario explorer" meta="Behavioral two-source posterior">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ fontFamily: M.mono, fontSize: 11, letterSpacing: '0.08em', color: M.inkDim }}>
          Two-source blend ({pct1(bvarWeight)} BVAR / {pct1(analogueWeight)} analogue)
          <span style={{ color: M.inkFaint }}> · s_used {pct1(sUsed)} · binding {bindingQuarter || '—'}</span>
        </div>
        {f.mixture.stress_advisory ? <Chip label="Stress advisory" color={M.warn} /> : null}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(150px, 1fr))', gap: '10px' }} className="scenario-card-grid">
        {f.scenarios.map((s, i) => {
          const top = s.isRecession ? M.warn : i === 0 ? M.accentBright : s.blended !== null && s.blended >= 0.15 ? M.pos : M.inkFaint;
          const deltaColor = s.delta === null || s.delta === undefined ? M.inkFaint : s.delta >= 0 ? M.pos : M.neg;
          return (
            <div key={s.id} style={{ background: M.well, border: `1px solid ${M.line}`, borderTop: `3px solid ${top}`, borderRadius: '10px', padding: '13px 12px', minWidth: 0 }}>
              <ValueText value={pct1(s.blended)} size={20} color={top} />
              <h3 style={{ fontFamily: M.serif, fontSize: '16px', fontWeight: 500, color: M.ink, margin: '8px 0 7px', lineHeight: 1.12 }}>{s.label}</h3>
              <p style={{ margin: '0 0 12px', fontFamily: M.sans, fontSize: '11px', color: M.inkDim, lineHeight: 1.42, minHeight: '64px' }}>{s.desc}</p>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', fontFamily: M.mono, fontSize: '10px', color: M.inkFaint, borderTop: `1px solid ${M.line}`, paddingTop: '8px' }}>
                <span>bvar {pct1(s.bvar)}</span><span>analogue {pct1(s.analogue)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: M.mono, fontSize: '10px', color: M.inkFaint, paddingTop: '5px', gap: 8 }}>
                <span>delta</span><span style={{ color: deltaColor }}>{signedPct1(s.delta)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 4: Analogue fan + evidence panels
// ─────────────────────────────────────────────────────────────
const FAN_VARIABLE_ORDER = ['credit_spread', 'curve_slope', 'activity', 'lur', 'core_pce', 'fed_funds', 'ten_year', 'nfci'];
const FAN_VARIABLE_LABELS: Record<string, string> = {
  activity: 'Activity',
  lur: 'Unemployment',
  core_pce: 'Core PCE',
  credit_spread: 'Credit spread',
  fed_funds: 'Fed funds',
  ten_year: '10Y Treasury',
  nfci: 'NFCI',
  curve_slope: 'Curve slope',
};
type FanChartPoint = {
  quarter: string;
  p10p90: [number, number];
  p25p75: [number, number];
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  recession: number | null;
  benign: number | null;
  anchor: number;
  effectiveN: number;
};

function addQuarters(period: string, offset: number): string {
  const match = /^(\d{4})Q([1-4])$/.exec(period);
  if (!match) return offset ? `${period}+${offset}` : period;
  const year = Number(match[1]);
  const quarter = Number(match[2]) - 1;
  const total = year * 4 + quarter + offset;
  return `${Math.floor(total / 4)}Q${(total % 4) + 1}`;
}

function fanRows(fan: AnalogueFanPayload, variableKey: string): FanChartPoint[] {
  const variable = fan.variables[variableKey];
  if (!variable) return [];
  const horizon = variable.percentiles.p50.length;
  return Array.from({ length: horizon }, (_, index) => {
    const p10 = variable.percentiles.p10[index];
    const p25 = variable.percentiles.p25[index];
    const p50 = variable.percentiles.p50[index];
    const p75 = variable.percentiles.p75[index];
    const p90 = variable.percentiles.p90[index];
    return {
      quarter: addQuarters(fan.query_date, index + 1),
      p10p90: [p10, p90],
      p25p75: [p25, p75],
      p10,
      p25,
      p50,
      p75,
      p90,
      recession: variable.median_recession_bound?.[index] ?? null,
      benign: variable.median_benign?.[index] ?? null,
      anchor: variable.query_anchor_value,
      effectiveN: variable.effective_n[index] ?? 0,
    };
  });
}

function FanTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ payload?: FanChartPoint }>; label?: string }) {
  const point = payload?.find((item) => item.payload)?.payload;
  if (!active || !point) return null;
  return (
    <div style={{ background: M.cardElev, border: `1px solid ${M.line2}`, borderRadius: 8, padding: '9px 10px', color: M.ink, fontFamily: M.mono, fontSize: 10.5 }}>
      <div style={{ color: M.inkFaint, marginBottom: 5 }}>{label}</div>
      <div>p10 {formatAxisNumber(point.p10)} · p50 {formatAxisNumber(point.p50)} · p90 {formatAxisNumber(point.p90)}</div>
      <div>p25 {formatAxisNumber(point.p25)} · p75 {formatAxisNumber(point.p75)}</div>
      <div>recession {point.recession === null ? '—' : formatAxisNumber(point.recession)} · benign {point.benign === null ? '—' : formatAxisNumber(point.benign)}</div>
      <div style={{ color: M.inkFaint }}>n_eff {point.effectiveN.toFixed(1)}</div>
    </div>
  );
}

function AnalogueFanPanel({ fan, error, isLoading }: { fan?: AnalogueFanPayload; error?: Error; isLoading: boolean }) {
  const variableKeys = useMemo(() => {
    const keys = Object.keys(fan?.variables ?? {});
    return FAN_VARIABLE_ORDER.filter((key) => keys.includes(key)).concat(keys.filter((key) => !FAN_VARIABLE_ORDER.includes(key)));
  }, [fan]);
  const [selectedKey, setSelectedKey] = useState('credit_spread');
  const selected = variableKeys.includes(selectedKey) ? selectedKey : variableKeys[0] ?? 'credit_spread';

  if (isLoading) return <Panel title="Analogue Fans — matched-episode forward paths" meta="loading"><EmptyMini message="Loading analogue fan artifact." /></Panel>;
  if (error) return <Panel title="Analogue Fans — matched-episode forward paths" meta="artifact error"><ErrorMini message={error.message} /></Panel>;
  if (!fan || !variableKeys.length) return <Panel title="Analogue Fans — matched-episode forward paths" meta="artifact missing"><ErrorMini message="Analogue fan artifact missing. Regenerate with PYTHONPATH=backend python3 -m src.agent_system.forecasting.macro_forecast_runner --allow-stale-bvar." /></Panel>;

  const variable = fan.variables[selected];
  const rows = fanRows(fan, selected);
  const fanDomain = computeYDomain(rows.flatMap((row) => [
    row.p10,
    row.p25,
    row.p50,
    row.p75,
    row.p90,
    row.recession,
    row.benign,
    row.anchor,
  ]));
  const h1Eff = variable?.effective_n?.[0] ?? fan.metadata?.match_kernel_weight_sum ?? null;
  const recNote = variable?.subset_notes?.recession_bound;
  const benignNote = variable?.subset_notes?.benign;
  return (
    <Panel title="Analogue Fans — matched-episode forward paths" meta={`${fan.query_date} · n_eff ${h1Eff === null ? '—' : h1Eff.toFixed(1)}`}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'nowrap', overflowX: 'auto', paddingBottom: 2, marginBottom: 10 }}>
        {variableKeys.map((key) => (
          <button
            key={key}
            onClick={() => setSelectedKey(key)}
            style={{
              background: selected === key ? M.accentSoft : M.well,
              color: selected === key ? M.accentBright : M.inkDim,
              border: `1px solid ${selected === key ? M.accent : M.line}`,
              borderRadius: 8,
              padding: '5px 8px',
              fontFamily: M.mono,
              fontSize: 10,
              cursor: 'pointer',
              flexShrink: 0,
            }}
          >
            {FAN_VARIABLE_LABELS[key] ?? titleCase(key)}
          </button>
        ))}
      </div>
      <div style={{ height: 320, background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, padding: '8px 4px 2px' }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 10, right: 14, bottom: 8, left: 0 }}>
            <CartesianGrid stroke={M.line2} strokeDasharray="3 3" opacity={0.55} />
            <XAxis dataKey="quarter" tick={{ fill: M.inkFaint, fontFamily: M.mono, fontSize: 10 }} axisLine={{ stroke: M.line2 }} tickLine={{ stroke: M.line2 }} />
            <YAxis domain={fanDomain} tickFormatter={(value) => formatAxisNumber(Number(value))} tick={{ fill: M.inkFaint, fontFamily: M.mono, fontSize: 10 }} axisLine={{ stroke: M.line2 }} tickLine={{ stroke: M.line2 }} width={42} />
            <Tooltip content={<FanTooltip />} />
            <Area type="monotone" dataKey="p10p90" stroke="none" fill={M.accent} fillOpacity={0.18} isAnimationActive={false} />
            <Area type="monotone" dataKey="p25p75" stroke="none" fill={M.accent} fillOpacity={0.34} isAnimationActive={false} />
            <Line type="monotone" dataKey="p50" stroke={M.accentBright} strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="recession" stroke={M.warn} strokeWidth={1.8} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
            <Line type="monotone" dataKey="benign" stroke={M.pos} strokeWidth={1.8} strokeDasharray="5 4" dot={false} connectNulls isAnimationActive={false} />
            <Line type="monotone" dataKey="anchor" stroke={M.inkFaint} strokeWidth={1.1} strokeDasharray="2 5" dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontFamily: M.sans, fontSize: 11.5, color: M.inkDim, marginTop: 9 }}>
        <LegendSwatch color={`${M.accent}2E`} label="p10–p90" />
        <LegendSwatch color={`${M.accent}57`} label="p25–p75" />
        <LegendSwatch color={M.accentBright} label="p50" />
        <LegendSwatch color={M.warn} label={recNote && recNote !== 'ok' ? `recession skipped: ${recNote}` : 'recession analogues'} />
        <LegendSwatch color={M.pos} label={benignNote && benignNote !== 'ok' ? `benign skipped: ${benignNote}` : 'benign analogues'} />
      </div>
    </Panel>
  );
}

function ErrorMini({ message }: { message: string }) {
  return <div style={{ minHeight: 130, display: 'grid', placeItems: 'center', color: M.neg, fontSize: 12, lineHeight: 1.45, background: M.dangerWell, border: `1px solid ${M.neg}55`, borderRadius: 12, padding: 14, textAlign: 'center' }}>{message}</div>;
}

function matchTag(match: TopMatch): { label: string; color: string } {
  if (!match.resolved) return { label: 'unresolved', color: M.inkFaint };
  if (match.recession_bound) return { label: match.onset_lag_quarters === null ? 'rec' : `rec · lag ${match.onset_lag_quarters}`, color: M.warn };
  return { label: 'benign', color: M.pos };
}

function AnalogueEvidencePanel({ f, error, isLoading }: { f: Forecast; error?: Error; isLoading: boolean }) {
  if (isLoading) return <Panel title="Analogue evidence" meta="loading"><EmptyMini message="Loading forecast evidence." /></Panel>;
  if (error) return <Panel title="Analogue evidence" meta="forecast error"><ErrorMini message={error.message} /></Panel>;
  const evidence = f.evidence;
  if (!evidence) return <Panel title="Analogue evidence" meta="missing"><ErrorMini message="Mixture report evidence missing. Regenerate with PYTHONPATH=backend python3 -m src.agent_system.forecasting.macro_forecast_runner --allow-stale-bvar." /></Panel>;

  const states = evidence.window_states ?? [];
  const binding = states.find((state) => state.quarter === evidence.binding_quarter) ?? states[states.length - 1];
  const timing = binding?.conditional_timing ?? binding?.onset_lag_distribution?.conditional_timing ?? evidence.trailing_max_onset_lag_distribution?.conditional_timing;
  const spent = timing?.spent_mass ?? binding?.spent_mass ?? 0;
  const remaining = timing?.remaining_mass ?? binding?.remaining_mass ?? 0;
  const conditionalShare = timing?.conditional_share ?? binding?.conditioned_share ?? evidence.s_used ?? null;
  const topMatches = (binding?.top_matches ?? []).slice(0, 5);
  return (
    <Panel title="Analogue evidence" meta="survival-conditioned">
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}>
        <div style={{ gridColumn: '1 / -1', background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, padding: 12 }}>
          <div style={{ ...labelStyleSmall, marginBottom: 4 }}>analogue recession evidence</div>
          <ValueText value={pct1(evidence.s_used ?? evidence.trailing_max)} size={30} color={M.warn} />
          <div style={{ fontFamily: M.mono, fontSize: 10.5, color: M.inkFaint, marginTop: 6 }}>
            binding {evidence.binding_quarter || '—'} · spot {pct1(evidence.spot_share)} · unconditioned max {pct1(evidence.trailing_max_unconditioned)}
          </div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(68px, 1fr))', gap: 6, marginTop: 9 }}>
        {states.map((state) => {
          const active = state.quarter === evidence.binding_quarter;
          const color = state.state === 'scored' ? M.pos : state.state === 'unprecedented_state' ? M.warn : M.inkFaint;
          return (
            <div key={state.quarter} style={{ background: active ? M.accentSoft : M.well, border: `1px solid ${active ? M.accent : M.line}`, borderRadius: 8, padding: '7px 6px', minWidth: 0 }}>
              <div style={{ fontFamily: M.mono, fontSize: 9.5, color: M.inkFaint }}>{state.quarter}</div>
              <div style={{ fontFamily: M.mono, fontSize: 12, color, marginTop: 3 }}>● {pct1(state.conditioned_share ?? state.share)}</div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 10, background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, padding: 11 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontFamily: M.mono, fontSize: 10.5, color: M.inkFaint, marginBottom: 8 }}>
          <span>timing · elapsed {timing?.elapsed_quarters ?? binding?.elapsed_quarters ?? '—'}Q</span>
          <span>conditional {pct1(conditionalShare)}</span>
        </div>
        <div style={{ height: 10, display: 'flex', overflow: 'hidden', borderRadius: 999, border: `1px solid ${M.line2}`, background: M.cardElev }}>
          <div style={{ width: `${Math.max(0, Math.min(1, spent)) * 100}%`, background: M.warn }} />
          <div style={{ width: `${Math.max(0, Math.min(1, remaining)) * 100}%`, background: M.accentBright }} />
        </div>
        <p style={{ margin: '8px 0 10px', color: M.inkDim, fontFamily: M.sans, fontSize: 11.5, lineHeight: 1.45 }}>
          {(spent * 100).toFixed(1)}% of matched-recession onsets occurred within the elapsed {timing?.elapsed_quarters ?? binding?.elapsed_quarters ?? '—'} quarters; conditioned remaining-window probability {pct1(conditionalShare)}.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {topMatches.map((match) => {
            const tag = matchTag(match);
            return (
              <div key={`${match.neighbor_quarter}-${match.kernel_weight}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', fontFamily: M.mono, fontSize: 10.5, color: M.inkDim }}>
                <span>{match.neighbor_quarter}</span>
                <span style={{ color: M.inkFaint }}>w={match.kernel_weight.toFixed(2)}</span>
                <span style={{ color: tag.color }}>{tag.label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </Panel>
  );
}

function EmptyMini({ message }: { message: string }) {
  return <div style={{ minHeight: 130, display: 'grid', placeItems: 'center', color: M.inkFaint, fontSize: 12, background: M.well, border: `1px solid ${M.line}`, borderRadius: 12 }}>{message}</div>;
}
function LegendSwatch({ color, label }: { color: string; label: string }) {
  return <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><span style={{ width: '12px', height: '12px', borderRadius: '3px', background: color, border: `1px solid ${M.line2}` }} />{label}</span>;
}

// ─────────────────────────────────────────────────────────────
// Indicator explorer
// ─────────────────────────────────────────────────────────────
function indicatorKey(ind: Indicator): string {
  return `${ind.layer}::${ind.role}::${ind.label}`;
}
function sortIndicators(items: Indicator[]): Indicator[] {
  return items.slice().sort((a, b) => (ROLE_ORDER[a.role] ?? 9) - (ROLE_ORDER[b.role] ?? 9) || a.label.localeCompare(b.label));
}
function IndicatorExplorer({ f }: { f: Forecast }) {
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedIndicatorKey, setSelectedIndicatorKey] = useState<string | null>(null);

  const categories = useMemo(() => {
    const map = new Map<string, Indicator[]>();
    for (const ind of f.indicators) {
      const key = ind.layer || 'Other';
      map.set(key, [...(map.get(key) ?? []), ind]);
    }
    const ordered = [
      ...CATEGORY_ORDER.filter((name) => map.has(name)),
      ...Array.from(map.keys()).filter((name) => !CATEGORY_ORDER.includes(name)).sort(),
    ];
    return ordered.map((name) => {
      const items = sortIndicators(map.get(name) ?? []);
      const summary = items.find((item) => item.role === 'layer_summary');
      return { name, count: items.length, signal: summary?.signal ?? items[0]?.signal ?? 'neutral', items };
    });
  }, [f.indicators]);

  const activeCategoryName = selectedCategory ?? categories[0]?.name ?? null;
  const category = categories.find((c) => c.name === activeCategoryName) ?? null;
  const categoryItems = category?.items ?? [];
  const selectedIndicator = categoryItems.find((ind) => indicatorKey(ind) === selectedIndicatorKey) ?? categoryItems[0] ?? null;

  const selectCategory = (name: string, items: Indicator[]) => {
    setSelectedCategory(name);
    setSelectedIndicatorKey(items[0] ? indicatorKey(items[0]) : null);
  };

  return (
    <section style={{ background: M.card, border: `1px solid ${M.line}`, borderRadius: 16, boxShadow: M.shadow, overflow: 'hidden' }}>
      <div className="macro-indicator-shell" style={{ display: 'grid', gridTemplateColumns: '250px minmax(0, 1fr) 380px', minHeight: 342 }}>
        <div className="macro-indicator-rail" style={{ borderRight: `1px solid ${M.line}`, background: M.cardElev, padding: '14px 10px' }}>
          <div style={{ ...labelStyleSmall, padding: '0 10px 10px' }}>Macro indicators explorer</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {categories.map((cat) => {
              const active = cat.name === category?.name;
              return (
                <button key={cat.name} type="button" onClick={() => selectCategory(cat.name, cat.items)} style={railRowStyle(active)}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 9, minWidth: 0 }}>
                    <SignalDot signal={cat.signal} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cat.name}</span>
                  </span>
                  <span style={{ fontFamily: M.mono, color: M.inkDim }}>{cat.count}</span>
                </button>
              );
            })}
          </div>
        </div>
        <div style={{ padding: '18px 22px', borderRight: `1px solid ${M.line}` }}>
          {selectedIndicator ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, alignItems: 'start', marginBottom: 6 }}>
                <div>
                  <div style={labelStyleSmall}>Selected indicator</div>
                  <h3 style={{ margin: '8px 0 0', fontFamily: M.serif, fontSize: 20, fontWeight: 500, color: M.ink, lineHeight: 1.05 }}>{selectedIndicator.label}</h3>
                </div>
                <select
                  value={indicatorKey(selectedIndicator)}
                  onChange={(event) => setSelectedIndicatorKey(event.target.value)}
                  style={{ maxWidth: 230, background: M.well, border: `1px solid ${M.line2}`, color: M.inkDim, borderRadius: 9, padding: '7px 9px', fontSize: 11.5, outline: 'none' }}
                >
                  {categoryItems.map((ind) => <option key={indicatorKey(ind)} value={indicatorKey(ind)}>{ind.label}</option>)}
                </select>
              </div>
              <HistoryLineChart points={selectedIndicator.history} color={signalColor(selectedIndicator.signal)} height={220} yLabel={selectedIndicator.unit || 'value'} />
            </>
          ) : <EmptyMini message="Select an indicator category." />}
        </div>
        <div style={{ padding: '28px 24px 18px' }}>
          {selectedIndicator ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12, borderBottom: `1px solid ${M.line}`, paddingBottom: 18 }} className="indicator-stat-grid">
                <IndicatorStat label="Signal" value={titleCase(selectedIndicator.signal || 'neutral')} color={signalColor(selectedIndicator.signal)} />
                <IndicatorStat label="Trend (3M)" value={titleCase(selectedIndicator.trend || '—')} color={selectedIndicator.trend === 'improving' ? M.pos : selectedIndicator.trend === 'deteriorating' ? M.neg : M.warn} />
                <IndicatorStat label="Confidence" value={selectedIndicator.conf === null ? '—' : selectedIndicator.conf >= 0.75 ? 'High' : selectedIndicator.conf >= 0.5 ? 'Medium' : 'Low'} />
                <IndicatorStat label="Value" value={formatIndicatorValue(selectedIndicator.val)} />
              </div>
              <div style={{ marginTop: 17 }}>
                <MutedLabel>Interpretation</MutedLabel>
                <p style={{ margin: 0, color: M.inkDim, fontSize: 12.5, lineHeight: 1.55 }}>
                  {selectedIndicator.label} is {selectedIndicator.signal || 'neutral'} with a {selectedIndicator.trend || 'stable'} trend in {selectedIndicator.layer || selectedIndicator.cat || 'the macro model'}.
                </p>
              </div>
              <div style={{ marginTop: 18, textAlign: 'right' }}>
                <span style={{ color: M.accentBright, fontSize: 12.5 }}>View indicator detail →</span>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}
function railRowStyle(active: boolean): React.CSSProperties {
  return {
    width: '100%',
    border: `1px solid ${active ? M.accent : 'transparent'}`,
    borderLeft: `3px solid ${active ? M.accent : 'transparent'}`,
    background: active ? M.cardElev : 'transparent',
    color: active ? M.ink : M.inkDim,
    borderRadius: '10px',
    padding: '10px 10px',
    fontFamily: M.sans,
    fontSize: '12.5px',
    fontWeight: 600,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '10px',
    textAlign: 'left',
    cursor: 'pointer',
    boxShadow: active ? `0 0 0 1px ${M.accent}33` : undefined,
  };
}
function IndicatorStat({ label, value, color = M.ink }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ ...labelStyleSmall, marginBottom: 8 }}>{label}</div>
      <div style={{ color, fontFamily: label === 'Value' ? M.mono : M.sans, fontSize: label === 'Value' ? 15 : 13, fontWeight: 600, lineHeight: 1.35 }}>{value}</div>
    </div>
  );
}
function formatAxisNumber(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1000) return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (abs >= 100) return value.toFixed(0);
  if (abs >= 10) return value.toFixed(1);
  return value.toFixed(2).replace(/\.00$/, '');
}
function formatAxisDate(date: string): string {
  const parsed = new Date(`${date}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return date.slice(5) || date;
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
function HistoryLineChart({
  points,
  color,
  height = 150,
  yLabel,
}: {
  points?: HistoryPoint[];
  color: string;
  height?: number;
  yLabel?: string;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const data = (points ?? [])
    .filter((point) => point.date && Number.isFinite(point.value))
    .slice(-180);
  const W = 640;
  const H = height;
  const padL = 54;
  const padR = 18;
  const padT = 16;
  const padB = 34;
  if (data.length < 2) {
    return (
      <div style={{ height, marginTop: 14, background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, display: 'grid', placeItems: 'center', color: M.inkFaint, fontFamily: M.sans, fontSize: 12 }}>
        No historical series mapped for this indicator.
      </div>
    );
  }
  const values = data.map((point) => point.value);
  const [mn, mx] = computeYDomain(values, 0.08);
  const x = (index: number) => padL + (index / Math.max(1, data.length - 1)) * (W - padL - padR);
  const y = (value: number) => padT + (1 - (value - mn) / (mx - mn)) * (H - padT - padB);
  const path = data.map((point, index) => `${x(index)},${y(point.value)}`).join(' L');
  const yTicks = [mn, (mn + mx) / 2, mx];
  const xTickIndexes = Array.from(
    new Set([0, Math.floor((data.length - 1) / 2), data.length - 1]),
  );
  const last = data[data.length - 1];
  const activeIndex = hoverIndex === null ? null : Math.max(0, Math.min(data.length - 1, hoverIndex));
  const activePoint = activeIndex === null ? null : data[activeIndex];
  const activeX = activeIndex === null ? null : x(activeIndex);
  const activeY = activePoint ? y(activePoint.value) : null;
  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * W;
    const pct = (svgX - padL) / Math.max(1, W - padL - padR);
    const index = Math.round(Math.max(0, Math.min(1, pct)) * (data.length - 1));
    setHoverIndex(index);
  };
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      onPointerMove={handlePointerMove}
      onPointerLeave={() => setHoverIndex(null)}
      style={{ width: '100%', height, marginTop: 8, background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, cursor: 'crosshair', touchAction: 'none' }}
    >
      <rect x={0} y={0} width={W} height={H} fill="transparent" />
      {yTicks.map((tick) => (
        <g key={tick}>
          <line x1={padL} x2={W - padR} y1={y(tick)} y2={y(tick)} stroke={M.line2} strokeWidth={0.8} opacity={0.55} />
          <text x={padL - 9} y={y(tick) + 4} textAnchor="end" fill={M.inkFaint} fontSize={10} fontFamily={M.mono}>{formatAxisNumber(tick)}</text>
        </g>
      ))}
      {mn < 0 && mx > 0 ? <line x1={padL} x2={W - padR} y1={y(0)} y2={y(0)} stroke={M.inkFaint} strokeWidth={0.8} strokeDasharray="4 4" opacity={0.75} /> : null}
      <line x1={padL} x2={padL} y1={padT} y2={H - padB} stroke={M.line2} strokeWidth={0.9} />
      <line x1={padL} x2={W - padR} y1={H - padB} y2={H - padB} stroke={M.line2} strokeWidth={0.9} />
      <path d={`M${path}`} fill="none" stroke={color} strokeWidth={1.45} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={x(data.length - 1)} cy={y(last.value)} r={2.6} fill={color} />
      {activePoint && activeX !== null && activeY !== null ? (
        <g pointerEvents="none">
          <line x1={activeX} x2={activeX} y1={padT} y2={H - padB} stroke={color} strokeWidth={0.9} opacity={0.72} strokeDasharray="3 3" />
          <circle cx={activeX} cy={activeY} r={4} fill={M.well} stroke={color} strokeWidth={1.5} />
          <g transform={`translate(${Math.min(W - 152, Math.max(padL + 8, activeX + 9))}, ${Math.max(padT + 5, activeY - 38)})`}>
            <rect width={138} height={34} rx={7} fill={M.cardElev} stroke={M.line2} />
            <text x={9} y={13} fill={M.inkFaint} fontSize={9.5} fontFamily={M.mono}>{activePoint.date}</text>
            <text x={9} y={27} fill={color} fontSize={12} fontFamily={M.mono}>{formatAxisNumber(activePoint.value)}</text>
          </g>
        </g>
      ) : null}
      {xTickIndexes.map((index) => (
        <g key={index}>
          <line x1={x(index)} x2={x(index)} y1={H - padB} y2={H - padB + 4} stroke={M.line2} />
          <text x={x(index)} y={H - 11} textAnchor="middle" fill={M.inkFaint} fontSize={10} fontFamily={M.mono}>{formatAxisDate(data[index].date)}</text>
        </g>
      ))}
      {yLabel ? (
        <text x={padL} y={11} fill={M.inkFaint} fontSize={9.5} fontFamily={M.mono} letterSpacing={1}>{truncate(yLabel, 28)}</text>
      ) : null}
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 7: Market narrative (SPY)
// ─────────────────────────────────────────────────────────────
type NarrativeTab = 'narrative' | 'themes' | 'inefficiencies' | 'tensions' | 'positioning';
const NARRATIVE_TABS: { key: NarrativeTab; label: string }[] = [
  { key: 'narrative', label: 'Narrative' },
  { key: 'themes', label: 'Themes' },
  { key: 'inefficiencies', label: 'Inefficiencies' },
  { key: 'tensions', label: 'Tensions' },
  { key: 'positioning', label: 'Positioning' },
];

function NarrativeSection({ result, f }: { result: AnyRecord | null; f: Forecast }) {
  const [active, setActive] = useState<NarrativeTab>('narrative');
  const [expanded, setExpanded] = useState(false);
  const snap = result ? extractSnapshot(result) : { bullets: [], regimeTone: '', primaryGap: '', primaryArchetype: '', priceConfirmation: '', confidence: null, fullSummary: '' };
  const themes = result ? normalizeThemes(result) : [];
  const inefficiency = result ? extractInefficiency(result, themes) : [];
  const watch = result ? extractWatchpoints(result, themes) : [];

  const narrativeRows = snap.bullets.length
    ? snap.bullets
    : !f.available
      ? [{ label: 'Forecast', text: f.unavailableMessage || 'Forecast unavailable.' }]
    : [
        { label: 'Reality', text: f.regimeRead || f.headline },
        { label: 'Story', text: f.summary },
        { label: 'Price', text: f.confRationale },
      ].filter((row) => row.text);

  const renderNarrative = () => (
    <div style={{ display: 'grid', gridTemplateColumns: '1.15fr 0.95fr 0.85fr', gap: 18 }} className="macro-narrative-grid">
      <div>
        {narrativeRows.slice(0, 3).map((row) => (
          <div key={row.label} style={{ display: 'grid', gridTemplateColumns: '70px minmax(0, 1fr)', gap: 12, marginBottom: 9 }}>
            <span style={{ fontFamily: M.mono, fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase', color: row.label === 'Reality' ? M.pos : row.label === 'Story' ? M.accentBright : M.inkFaint, fontWeight: 600 }}>{row.label}</span>
            <p style={{ margin: 0, color: M.inkDim, fontSize: 12.5, lineHeight: 1.45 }}>{truncate(row.text, 150)}</p>
          </div>
        ))}
      </div>
      <div style={{ borderLeft: `1px solid ${M.line}`, paddingLeft: 18 }}>
        <ChipCloud label="Preferred" color={M.pos} items={f.available ? f.preferred : ['forecast unavailable']} />
        <div style={{ height: 10 }} />
        <ChipCloud label="Avoid" color={M.neg} items={f.available ? f.avoid : ['forecast unavailable']} />
      </div>
      <div style={{ borderLeft: `1px solid ${M.line}`, paddingLeft: 18 }}>
        <MutedLabel>Key tensions</MutedLabel>
        {(f.available ? f.tensions : ['forecast unavailable']).slice(0, 4).map((item, index) => (
          <div key={`${item}-${index}`} style={{ display: 'grid', gridTemplateColumns: '24px minmax(0, 1fr)', gap: 8, color: M.inkDim, fontSize: 12, lineHeight: 1.35, marginBottom: 6 }}>
            <span style={{ fontFamily: M.mono, color: M.accentBright }}>0{index + 1}</span>
            <span>{truncate(item, 88)}</span>
          </div>
        ))}
      </div>
    </div>
  );

  const renderThemes = () => themes.length ? (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10 }} className="macro-narrative-grid">
      {themes.slice(0, expanded ? 6 : 3).map((theme, index) => <ThemeCard key={`${theme.title}-${index}`} theme={theme} />)}
    </div>
  ) : <EmptyMini message={result ? 'No dominant themes identified.' : 'No cached SPY narrative read available yet.'} />;

  const renderInefficiencies = () => inefficiency.length ? (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10 }} className="macro-narrative-grid">
      {inefficiency.slice(0, expanded ? 6 : 3).map((row, index) => (
        <div key={`${row.subject}-${index}`} style={{ background: M.well, border: `1px solid ${M.line}`, borderLeft: `3px solid ${M.warn}`, borderRadius: 12, padding: 13 }}>
          <div style={{ fontFamily: M.serif, fontSize: 16, color: M.ink, lineHeight: 1.15 }}>{row.subject}</div>
          <div style={{ marginTop: 8, color: M.inkDim, fontSize: 12, lineHeight: 1.45 }}>{truncate(row.gap || row.archetype, 150)}</div>
        </div>
      ))}
    </div>
  ) : <EmptyMini message="No explicit inefficiency classifications in this run." />;

  const renderTensions = () => (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 10 }} className="macro-narrative-grid">
      {(f.tensions.length ? f.tensions : watch).slice(0, expanded ? 8 : 4).map((item, index) => (
        <div key={`${item}-${index}`} style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, padding: 13 }}>
          <div style={{ fontFamily: M.mono, fontSize: 10, color: M.accentBright, marginBottom: 8 }}>0{index + 1}</div>
          <div style={{ color: M.inkDim, fontSize: 12.5, lineHeight: 1.45 }}>{item}</div>
        </div>
      ))}
    </div>
  );

  const renderPositioning = () => (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }} className="macro-narrative-grid">
      <ChipCloud label="Preferred" color={M.pos} items={f.available ? f.preferred : ['forecast unavailable']} />
      <ChipCloud label="Avoid" color={M.neg} items={f.available ? f.avoid : ['forecast unavailable']} />
    </div>
  );

  const renderActive = () => {
    if (active === 'themes') return renderThemes();
    if (active === 'inefficiencies') return renderInefficiencies();
    if (active === 'tensions') return renderTensions();
    if (active === 'positioning') return renderPositioning();
    return renderNarrative();
  };

  return (
    <section style={{ background: M.card, border: `1px solid ${M.line}`, borderRadius: 16, boxShadow: M.shadow, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, borderBottom: `1px solid ${M.line}`, padding: '0 14px' }}>
        {NARRATIVE_TABS.map((tab) => (
          <button key={tab.key} type="button" onClick={() => setActive(tab.key)} style={narrativeTabStyle(active === tab.key)}>
            {tab.label}
          </button>
        ))}
        <button type="button" onClick={() => setExpanded((value) => !value)} style={{ marginLeft: 'auto', border: 0, background: 'transparent', color: M.accentBright, fontFamily: M.sans, fontSize: 12.5, cursor: 'pointer' }}>
          {expanded ? 'Collapse view' : 'Expand all'} →
        </button>
      </div>
      <div style={{ padding: 16 }}>
        {expanded ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {renderNarrative()}
            {renderThemes()}
            {renderInefficiencies()}
            {renderTensions()}
          </div>
        ) : renderActive()}
      </div>
    </section>
  );
}

function narrativeTabStyle(active: boolean): React.CSSProperties {
  return {
    border: 0,
    borderBottom: `2px solid ${active ? M.accent : 'transparent'}`,
    background: active ? M.accentSoft : 'transparent',
    color: active ? M.ink : M.inkDim,
    padding: '11px 12px',
    fontFamily: M.sans,
    fontSize: 12.5,
    fontWeight: 600,
    cursor: 'pointer',
  };
}

function ChipCloud({ label, color, items }: { label: string; color: string; items: string[] }) {
  return (
    <div>
      <div style={{ ...labelStyleSmall, color }}>{label}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 7 }}>
        {(items.length ? items : ['—']).map((item) => <Chip key={item} label={item} color={color === M.pos || color === M.neg ? color : M.accentBright} />)}
      </div>
    </div>
  );
}
function ThemeCardRow({ label, color, value }: { label: string; color: string; value: string }) {
  return value ? (
    <div style={{ display: 'flex', gap: '10px', marginBottom: '7px' }}>
      <span style={{ fontFamily: M.mono, fontSize: '10px', letterSpacing: '0.1em', textTransform: 'uppercase', color, fontWeight: 600, width: '70px', flexShrink: 0, paddingTop: '3px' }}>{label}</span>
      <p style={{ margin: 0, fontFamily: M.sans, fontSize: '13px', color: M.inkDim, lineHeight: 1.55, flex: 1 }}>{value}</p>
    </div>
  ) : null;
}
function ThemeCard({ theme }: { theme: NarrTheme }) {
  const sc = STANCE_COLOR[theme.stance.toLowerCase()] ?? M.inkFaint;
  return (
    <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: '14px', padding: '16px 18px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', marginBottom: '11px' }}>
        <h3 style={{ fontFamily: M.serif, fontSize: '19px', fontWeight: 500, color: M.ink, lineHeight: 1.15, margin: 0 }}>{theme.title}</h3>
        <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
          {theme.stance ? <Chip label={theme.stance} color={sc} /> : null}
          {theme.confidence !== null ? <Chip label={`${theme.confidence}/100`} /> : null}
        </div>
      </div>
      {theme.thesis ? <p style={{ margin: '0 0 13px', fontFamily: M.sans, fontSize: '13px', color: M.inkDim, lineHeight: 1.55 }}>{theme.thesis}</p> : null}
      <ThemeCardRow label="Reality" color={M.pos} value={theme.reality} />
      <ThemeCardRow label="Story" color={M.accentBright} value={theme.story} />
      <ThemeCardRow label="Price" color={M.inkFaint} value={theme.price} />
      <ThemeCardRow label="Gap" color={M.warn} value={theme.gap} />
      <ThemeCardRow label="Falsifier" color={M.neg} value={theme.falsifier} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Page
// ═══════════════════════════════════════════════════════════════════
export default function MacroPage() {
  const authFetcher = useAuthFetcher();

  const { data: forecastRaw, error: forecastError, isLoading: forecastLoading } = useSWR<MacroForecastPayload>(
    authFetcher.isSignedIn ? FORECAST_ENDPOINT : null,
    authFetcher.fetcher,
    { revalidateOnFocus: false },
  );
  const { data: scenarioMetaRaw } = useSWR<ScenarioMetaMap>(
    authFetcher.isSignedIn ? SCENARIO_META_ENDPOINT : null,
    authFetcher.fetcher,
    { revalidateOnFocus: false },
  );
  const { data: fanRaw, error: fanError, isLoading: fanLoading } = useSWR<AnalogueFanPayload>(
    authFetcher.isSignedIn ? FAN_ENDPOINT : null,
    authFetcher.fetcher,
    { revalidateOnFocus: false },
  );
  const { data: layerDetailRaw, error: layerDetailError, isLoading: layerDetailLoading } = useSWR<MacroLayersDetailPayload, Error>(
    authFetcher.isSignedIn ? LAYER_DETAIL_ENDPOINT : null,
    authFetcher.fetcher,
    { revalidateOnFocus: false },
  );
  const { data: indicatorHistoryRaw } = useSWR<AnyRecord>(
    authFetcher.isSignedIn ? `${INDICATOR_HISTORY_ENDPOINT}?days=730` : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const indicatorHistory = useMemo<IndicatorHistoryMap>(
    () => normalizeIndicatorHistory(indicatorHistoryRaw),
    [indicatorHistoryRaw],
  );
  const forecastUnavailableMessage = forecastError
    ? errorMessage(forecastError)
    : forecastLoading
      ? 'Forecast loading.'
      : forecastRaw
        ? null
        : 'Forecast unavailable. Generate it with PYTHONPATH=backend python3 -m src.agent_system.forecasting.macro_forecast_runner --allow-stale-bvar.';
  const forecast = useMemo<Forecast>(
    () => normalizeForecast(forecastRaw, indicatorHistory, scenarioMetaRaw ?? {}, forecastUnavailableMessage),
    [forecastRaw, indicatorHistory, scenarioMetaRaw, forecastUnavailableMessage],
  );
  const forecastState = useMemo<ForecastDataState>(
    () => ({
      forecast,
      isLoading: forecastLoading,
      errorMessage: forecastUnavailableMessage,
    }),
    [forecast, forecastLoading, forecastUnavailableMessage],
  );
  const compositeScoreHistory = useMemo(
    () => indicatorHistory.score_total?.points ?? [],
    [indicatorHistory],
  );

  // Current daily regime read — only the top pulse/layer cards use this.
  const { data: regimeRaw } = useSWR<AnyRecord>(
    authFetcher.isSignedIn ? REGIME_ENDPOINT : null,
    authFetcher.fetcher,
    { refreshInterval: 300000, revalidateOnFocus: false, onError: () => null },
  );
  const regime = useMemo<LiveRegime | null>(
    () => normalizeRegime(regimeRaw),
    [regimeRaw],
  );
  const { data: regimeHistoryRaw } = useSWR<RegimeHistoryPayload>(
    authFetcher.isSignedIn ? `${REGIME_HISTORY_ENDPOINT}?days=90` : null,
    authFetcher.fetcher,
    { refreshInterval: 300000, revalidateOnFocus: false, onError: () => null },
  );
  const regimeScoreHistory = useMemo(
    () => {
      const indicatorScoreHistory = filterHistoryWindow(compositeScoreHistory, 90);
      if (indicatorScoreHistory.length) {
        return { points: indicatorScoreHistory, source: 'macro_indicator_history.score_total' };
      }
      const fromRegimeHistory = normalizeRegimeScoreHistory(regimeHistoryRaw);
      return {
        points: fromRegimeHistory,
        source: fromRegimeHistory.length ? 'market_regime_snapshots' : 'unavailable',
      };
    },
    [regimeHistoryRaw, compositeScoreHistory],
  );

  // SPY narrative — same endpoint the /narrative page uses.
  const { data: narrLatest } = useSWR<AnyRecord>(
    authFetcher.isSignedIn ? NARRATIVE_ENDPOINT(NARRATIVE_TICKER) : null,
    authFetcher.fetcher,
    { refreshInterval: (d) => (d?.status === 'generating' ? 5000 : 0), onError: () => null },
  );
  const narrResult = useMemo<AnyRecord | null>(() => {
    if (!narrLatest) return null;
    if (narrLatest.status === 'ready' && narrLatest.output) return narrLatest.output as AnyRecord;
    if (narrLatest.status === 'ready' && narrLatest.result) return narrLatest.result as AnyRecord;
    const lastCached = narrLatest.last_cached_result as AnyRecord | undefined;
    const cached = lastCached?.output ?? lastCached?.result;
    return (cached as AnyRecord) ?? null;
  }, [narrLatest]);

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  return (
    <ForecastDataContext.Provider value={forecastState}>
    <main style={{ background: M.canvas, minHeight: '100vh', color: M.canvasInk, fontFamily: M.sans }}>
      <div style={{ width: 'min(1460px, calc(100% - 44px))', margin: '0 auto', padding: '26px 0 46px', display: 'flex', flexDirection: 'column', gap: '9px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '18px', flexWrap: 'wrap', marginBottom: '4px' }}>
          <div>
            <Eyebrow>MACRO &amp; REGIME &gt; CURRENT READ</Eyebrow>
            <h1 style={{ fontFamily: M.serif, fontSize: '42px', fontWeight: 500, color: M.canvasInk, lineHeight: 1.02, margin: 0 }}>Macro Analysis</h1>
            <div style={{ fontFamily: M.sans, fontSize: '13px', color: M.canvasInkDim, lineHeight: 1.45, maxWidth: '960px', marginTop: 10 }}>
              {forecast.available ? forecast.regimeRead || forecast.headline : forecast.unavailableMessage}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <div style={{ fontFamily: M.mono, fontSize: '11.5px', letterSpacing: '0.08em', color: M.canvasInkFaint, padding: '8px 11px', border: `1px solid ${M.line2}`, borderRadius: '999px' }}>Regime · {regime?.asof || '—'}</div>
            <div style={{ fontFamily: M.mono, fontSize: '11.5px', letterSpacing: '0.08em', color: M.canvasInkFaint, padding: '8px 11px', border: `1px solid ${M.line2}`, borderRadius: '999px' }}>Forecast · {forecast.available ? forecast.asof || '—' : 'unavailable'}</div>
          </div>
        </div>

        {/* 1 — merged pulse + regime */}
        <MarketRegimePanel
          f={forecast}
          regime={regime}
          scoreHistory={regimeScoreHistory.points}
          scoreHistorySource={regimeScoreHistory.source}
          layerDetail={layerDetailRaw}
          layerError={layerDetailError}
          layerLoading={layerDetailLoading}
          fetcher={authFetcher.fetcher}
        />

        {/* 2 — scenario distribution */}
        <div>
          {forecastError ? <Panel title="Scenario explorer" meta="forecast error"><ErrorMini message={forecastError.message} /></Panel> : forecastLoading ? <Panel title="Scenario explorer" meta="loading"><EmptyMini message="Loading two-source forecast." /></Panel> : <ScenarioCards f={forecast} />}
        </div>

        {/* 3 — analogue fans + evidence */}
        <div className="macro-analogue-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.35fr) minmax(390px, 0.85fr)', gap: 10 }}>
          <AnalogueFanPanel fan={fanRaw} error={fanError} isLoading={fanLoading} />
          <AnalogueEvidencePanel f={forecast} error={forecastError} isLoading={forecastLoading} />
        </div>

        {/* 4 — compressed narrative */}
        <NarrativeSection result={narrResult} f={forecast} />

        {/* 5 — indicators */}
        <IndicatorExplorer f={forecast} />
      </div>

      {/* Responsive grid collapse */}
      <style>{`
        @media (max-width: 1280px) {
          .scenario-card-grid { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
        }
        @media (max-width: 980px) {
          .macro-top-grid, .macro-top-card-grid, .macro-merged-pulse-grid, .macro-factor-grid, .macro-analogue-grid, .macro-narrative-grid { grid-template-columns: 1fr !important; }
          .macro-merged-separator { height: 1px !important; min-height: 1px !important; }
          .helix-fan-grid { grid-template-columns: 1fr !important; }
          .macro-indicator-shell { grid-template-columns: 1fr !important; }
          .macro-indicator-rail { border-right: none !important; border-bottom: 1px solid ${M.line} !important; }
          .indicator-stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
        }
        @media (max-width: 720px) {
          .scenario-card-grid { grid-template-columns: 1fr !important; }
          .indicator-stat-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </main>
    </ForecastDataContext.Provider>
  );
}
