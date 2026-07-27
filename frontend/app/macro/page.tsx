'use client';

import { useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';
import { useAuthFetcher } from '../../lib/api';
import AuthRequired from '@/components/AuthRequired';
import { M } from '../lib/researchOsTheme';

// ═══════════════════════════════════════════════════════════════════
// Macro & Regime
//
// Merges the old "Market overview" + "Macro insights" into one page.
//   1. Market pulse + current regime (five layer scores)
//   2. Dominant scenario banner
//   3. Scenario distribution (blended / deterministic / historical)
//   4. Forward-return fan chart (analogue-weighted; swap in FRB/US paths later)
//   5. Positioning read + key tensions
//   6. Indicator explorer — all model inputs, filterable by layer
//   7. Market narrative (SPY) — snapshot, dominant themes, inefficiency map,
//      watchpoints — pulled from the same narrative endpoint the /narrative
//      page uses, with the ticker fixed to SPY.
//
// ── Wiring ──
// FORECAST_ENDPOINT is the one place to point this at your real API. It should
// return the macro_forecast JSON shape (the file you exported). Until that
// endpoint exists the page renders from SAMPLE_FORECAST so you can see it.
// The narrative section reuses NARRATIVE_ENDPOINT(ticker) exactly as the
// /narrative page does.
// ═══════════════════════════════════════════════════════════════════

const FORECAST_ENDPOINT = '/api/macro/forecast/latest';
const REGIME_ENDPOINT = '/api/market/regime';
const INDICATOR_HISTORY_ENDPOINT = '/api/macro/indicator-history';
const NARRATIVE_TICKER = 'SPY';
const NARRATIVE_ENDPOINT = (ticker: string) => `/api/narrative/latest?ticker=${ticker}`;

type AnyRecord = Record<string, unknown>;
type HistoryPoint = { date: string; value: number };
type IndicatorHistorySeries = {
  column: string;
  source: string;
  points: HistoryPoint[];
};
type IndicatorHistoryMap = Record<string, IndicatorHistorySeries>;

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
const pct1 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`);

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

function formatHistorySource(source: string): string {
  if (source === 'regime_timeseries') return 'regime states';
  if (source === 'backtest_master_file') return 'backtest master';
  return source || 'not available';
}

const SCENARIO_LABELS: Record<string, string> = {
  reopening_soft_landing: 'Reopening / Soft Landing',
  sticky_late_cycle_ai: 'Sticky Late-Cycle AI',
  late_cycle_risk_off: 'Late-Cycle Risk-Off',
  oil_inflation_tail: 'Oil / Inflation Tail',
  ai_capex_rollover: 'AI Capex Rollover',
};
const SCENARIO_DESC: Record<string, string> = {
  reopening_soft_landing: 'Growth broadens and participation widens while credit stays healthy and policy gradually eases.',
  sticky_late_cycle_ai: 'Narrow AI leadership persists while the Fed stays higher-for-longer and breadth lags.',
  late_cycle_risk_off: 'Late-cycle stress spreads from credit and breadth into a broader de-risking.',
  oil_inflation_tail: 'Energy and oil pressure reignite inflation and force tighter financial conditions.',
  ai_capex_rollover: 'Hyperscaler capex guidance rolls over, undercutting the AI earnings engine.',
};
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
function normalizeForecast(raw: AnyRecord, history: IndicatorHistoryMap = {}) {
  const fi = (raw.forecast_interpretation ?? {}) as AnyRecord;
  const sp = (raw.scenario_probabilities ?? {}) as AnyRecord;
  const det = (raw.scenario_probabilities_deterministic ?? {}) as AnyRecord;

  const calib = safeArray<AnyRecord>(
    ((raw.historical_calibration ?? {}) as AnyRecord).scenario_calibrations,
  );
  const histById: Record<string, AnyRecord> = {};
  for (const c of calib) histById[safeStr(c.scenario_id)] = c;

  const scenarios = Object.keys(sp)
    .map((id) => {
      const c = histById[id] ?? {};
      return {
        id,
        label: SCENARIO_LABELS[id] ?? id,
        desc: SCENARIO_DESC[id] ?? '',
        blended: safeNum(sp[id]) ?? 0,
        det: safeNum(det[id]),
        hist: safeNum(c.historical_probability),
        conf: safeNum(c.confidence),
        n: safeNum(c.n_supporting_analogues),
      };
    })
    .sort((a, b) => b.blended - a.blended);

  // Five layer summaries from input_signals where role === layer_summary
  const signals = safeArray<AnyRecord>(raw.input_signals);
  const layers = signals
    .filter((s) => safeStr(s.role) === 'layer_summary')
    .map((s) => ({
      layer: safeStr(s.parent_layer),
      name: LAYER_NAMES[safeStr(s.parent_layer)] ?? safeStr(s.parent_layer),
      score: safeNum(s.current_value) ?? 0,
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

  // Forward-return fan from historical_calibration.forward_return_stats
  const frs = ((raw.historical_calibration ?? {}) as AnyRecord).forward_return_stats as AnyRecord | undefined;
  const fanOrder = ['1d', '5d', '10d', '21d', '63d', '126d', '252d'];
  const fan = frs
    ? fanOrder
        .filter((h) => frs[h])
        .map((h) => {
          const s = frs[h] as AnyRecord;
          return {
            h,
            p10: safeNum(s.p10) ?? 0,
            p25: safeNum(s.p25) ?? 0,
            med: safeNum(s.median) ?? 0,
            p75: safeNum(s.p75) ?? 0,
            p90: safeNum(s.p90) ?? 0,
            win: safeNum(s.pct_positive),
          };
        })
    : [];

  const dominantId = safeStr(fi.dominant_scenario_id);
  const composite = layers.length
    ? (layers.reduce((a, l) => a + l.score, 0) / layers.length) * 10
    : null;

  return {
    asof: safeStr(raw.asof_date),
    horizon: safeStr(raw.horizon),
    probMode: safeStr(raw.probability_mode),
    headline: safeStr(fi.headline),
    regimeRead: safeStr(fi.regime_read),
    summary: safeStr(fi.summary),
    confLevel: safeStr(fi.confidence_level),
    confRationale: safeStr(fi.confidence_rationale),
    dominantLabel: SCENARIO_LABELS[dominantId] ?? dominantId,
    dominantProb: safeNum(fi.dominant_scenario_probability) ?? 0,
    preferred: safeArray<string>(fi.preferred_exposures),
    avoid: safeArray<string>(fi.exposures_to_avoid),
    tensions: safeArray<string>(fi.key_tensions),
    scenarios,
    layers,
    indicators,
    fan,
    composite,
  };
}
type Forecast = ReturnType<typeof normalizeForecast>;

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

function MarketPulse({ f, regime, scoreHistory }: { f: Forecast; regime: LiveRegime | null; scoreHistory: HistoryPoint[] }) {
  const composite = regime?.scoreTotal ?? f.composite;
  const runnerUp = f.scenarios[1];
  const probabilityGap = runnerUp ? f.dominantProb - runnerUp.blended : null;
  const topDeterministic = f.scenarios
    .filter((scenario) => scenario.det !== null && scenario.det !== undefined)
    .sort((a, b) => (b.det ?? 0) - (a.det ?? 0))[0];
  const pulseLabel =
    regime?.environment ||
    (f.confLevel === 'high' ? 'Constructive, high conviction' : f.confLevel === 'low' ? 'Constructive, selective' : 'Mixed, watchful');
  const pulseMeta = regime ? `Regime · ${regime.asof || '—'}` : `Forecast fallback · ${f.asof || '—'}`;
  const chartPoints = appendHistoryPoint(
    scoreHistory,
    regime?.scoreTotal !== null && regime?.scoreTotal !== undefined && regime?.asof
      ? { date: regime.asof, value: regime.scoreTotal }
      : null,
  );
  return (
    <Panel title="Market pulse" meta={pulseMeta} prominent>
      <div style={{ display: 'grid', gridTemplateColumns: '230px minmax(0, 1fr)', gap: 24, alignItems: 'start' }} className="macro-top-card-grid">
        <div>
          <h2 style={{ fontFamily: M.serif, fontSize: '27px', fontWeight: 500, color: M.ink, margin: 0, lineHeight: 1.03 }}>
            {pulseLabel}
          </h2>
          <div style={{ marginTop: 10 }}>
            <Chip label={`${pct1(f.dominantProb)} probability`} color={M.accent} />
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
            <MiniStat label="Dominant" value={f.dominantLabel || '—'} sub={pct1(f.dominantProb)} color={M.accentBright} />
            <MiniStat label="Runner-up" value={runnerUp?.label ?? '—'} sub={runnerUp ? pct1(runnerUp.blended) : '—'} />
            <MiniStat label="Gap" value={probabilityGap === null ? '—' : pct1(probabilityGap)} sub="dominant spread" color={probabilityGap !== null && probabilityGap > 0.08 ? M.pos : M.warn} />
            <MiniStat label="Deterministic" value={topDeterministic?.label ?? '—'} sub={topDeterministic?.det !== null && topDeterministic?.det !== undefined ? pct1(topDeterministic.det) : '—'} />
          </div>
        </div>
      </div>
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

function CurrentRegime({ f, regime }: { f: Forecast; regime: LiveRegime | null }) {
  const heading = regime?.environment || f.dominantLabel;
  const layers = regime
    ? regime.layers
    : f.layers.map((l) => ({
        key: l.layer,
        name: l.name,
        score: l.score,
        status: l.signal || l.trend || 'neutral',
      }));
  return (
    <Panel title="Current regime read" meta={heading}>
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
      <a href="/state" style={{ display: 'inline-flex', gap: 8, alignItems: 'center', color: M.accentBright, textDecoration: 'none', fontSize: 12.5, marginTop: 3 }}>View factor detail →</a>
    </Panel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 2: Dominant scenario banner
// ─────────────────────────────────────────────────────────────
function DominantBanner({ f }: { f: Forecast }) {
  return (
    <section style={{ background: '#0A1E36', border: `1px solid ${M.line2}`, borderRadius: '16px', overflow: 'hidden', boxShadow: M.shadow }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '30px', padding: '32px', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 520px' }}>
          <div style={{ fontFamily: M.mono, fontSize: '10.5px', letterSpacing: '0.18em', color: M.inkFaint, textTransform: 'uppercase' }}>Dominant scenario</div>
          <h2 style={{ fontFamily: M.serif, fontSize: '32px', fontWeight: 500, color: '#fff', lineHeight: 1.08, margin: '12px 0 14px', maxWidth: '820px' }}>{f.headline}</h2>
          <p style={{ margin: 0, fontFamily: M.sans, fontSize: '14px', color: M.inkDim, lineHeight: 1.65, maxWidth: '760px' }}>{f.summary}</p>
        </div>
        <div style={{ textAlign: 'right', minWidth: '190px' }}>
          <div style={{ fontFamily: M.mono, fontSize: '10.5px', letterSpacing: '0.14em', color: M.inkFaint, textTransform: 'uppercase' }}>Confidence · {f.confLevel}</div>
          <div style={{ marginTop: '6px' }}><ValueText value={pct1(f.dominantProb)} size={40} color="#fff" /></div>
          <div style={{ height: '6px', background: M.well, borderRadius: '999px', marginTop: '12px', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${f.dominantProb * 100}%`, background: M.accent, borderRadius: '999px' }} />
          </div>
          <div style={{ fontFamily: M.sans, fontSize: '11.5px', color: M.inkFaint, marginTop: '12px', lineHeight: 1.45, textAlign: 'right' }}>{f.confRationale}</div>
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 3: Scenario distribution
// ─────────────────────────────────────────────────────────────
function ScenarioCards({ f }: { f: Forecast }) {
  return (
    <Panel title="Scenario explorer" meta="Probability of next regime (blend)">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(118px, 1fr))', gap: '8px' }} className="scenario-card-grid">
        {f.scenarios.map((s, i) => {
          const top = i === 0 ? M.accentBright : s.blended >= 0.15 ? M.pos : M.neg;
          return (
            <div key={s.id} style={{ background: M.well, border: `1px solid ${M.line}`, borderTop: `3px solid ${top}`, borderRadius: '10px', padding: '12px 11px' }}>
              <ValueText value={pct1(s.blended)} size={19} color={top} />
              <h3 style={{ fontFamily: M.serif, fontSize: '15px', fontWeight: 500, color: M.ink, margin: '8px 0 7px', lineHeight: 1.12 }}>{s.label}</h3>
              <p style={{ margin: '0 0 11px', fontFamily: M.sans, fontSize: '10.5px', color: M.inkDim, lineHeight: 1.42, minHeight: '44px' }}>{truncate(s.desc, 86)}</p>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: M.mono, fontSize: '9.5px', color: M.inkFaint, borderTop: `1px solid ${M.line}`, paddingTop: '8px' }}>
                <span>det {pct1(s.det)}</span><span>hist {pct1(s.hist)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: M.mono, fontSize: '9.5px', color: M.inkFaint, paddingTop: '5px' }}>
                <span>conf {s.conf?.toFixed(2) ?? '—'}</span><span>n={s.n ?? '—'}</span>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 4: Forward-return fan chart
// ─────────────────────────────────────────────────────────────
function FanChart({ f }: { f: Forecast }) {
  const fan = f.fan;
  if (!fan.length) return null;
  const W = 620, H = 260, padL = 44, padR = 16, padT = 16, padB = 30;
  const xs = fan.map((_, i) => padL + (i / (fan.length - 1)) * (W - padL - padR));
  const all = fan.flatMap((d) => [d.p10, d.p90]);
  const mn = Math.min(...all, -2), mx = Math.max(...all);
  const y = (v: number) => padT + (1 - (v - mn) / (mx - mn)) * (H - padT - padB);
  const band = (lo: 'p10' | 'p25', hi: 'p90' | 'p75', op: number) => {
    const top = fan.map((d, i) => `${xs[i]},${y(d[hi])}`).join(' L');
    const bot = fan.slice().reverse().map((d, i) => `${xs[fan.length - 1 - i]},${y(d[lo])}`).join(' L');
    return <path d={`M${top} L${bot} Z`} fill={M.accent} opacity={op} />;
  };
  const medPath = `M${fan.map((d, i) => `${xs[i]},${y(d.med)}`).join(' L')}`;
  const fan63 = fan.find((d) => d.h === '63d');
  const fan252 = fan.find((d) => d.h === '252d');

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)', gap: '20px' }} className="helix-fan-grid">
      <Panel title="Forward return distribution" meta="analogue-weighted SPY paths">
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', background: M.well, borderRadius: '14px', border: `1px solid ${M.line}` }}>
          <line x1={padL} y1={y(0)} x2={W - padR} y2={y(0)} stroke={M.line2} strokeDasharray="3 3" />
          {band('p10', 'p90', 0.18)}
          {band('p25', 'p75', 0.32)}
          <path d={medPath} fill="none" stroke={M.accentBright} strokeWidth={2.5} />
          {fan.map((d, i) => <circle key={d.h} cx={xs[i]} cy={y(d.med)} r={3} fill={M.accentBright} />)}
          {[mn, 0, mx].map((t) => (
            <text key={t} x={6} y={y(t) + 4} fill={M.inkFaint} fontSize={10} fontFamily={M.mono}>{t > 0 ? '+' : ''}{t.toFixed(0)}%</text>
          ))}
          {fan.map((d, i) => (
            <text key={d.h} x={xs[i]} y={H - 8} fill={M.inkFaint} fontSize={10} textAnchor="middle" fontFamily={M.mono}>{d.h}</text>
          ))}
        </svg>
        <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap', fontFamily: M.sans, fontSize: '11.5px', color: M.inkDim, marginTop: '10px' }}>
          <LegendSwatch color={`${M.accent}2E`} label="p10–p90" />
          <LegendSwatch color={`${M.accent}52`} label="p25–p75" />
          <LegendSwatch color={M.accentBright} label="median" />
        </div>
      </Panel>
      <Panel title="Risk profile · analogue set">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <RiskCell k="MEDIAN / 63D" v={fan63?.med} suffix="%" sub={`win ${fan63?.win ?? '—'}%`} />
          <RiskCell k="MEDIAN / 252D" v={fan252?.med} suffix="%" sub={`win ${fan252?.win ?? '—'}%`} />
          <RiskCell k="P10 / 63D" v={fan63?.p10} suffix="%" sub="downside tail" />
          <RiskCell k="P90 / 252D" v={fan252?.p90} suffix="%" sub="upside tail" />
        </div>
      </Panel>
    </div>
  );
}

function ForwardReturnDistribution({ f }: { f: Forecast }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const fan = f.fan;
  if (!fan.length) return <Panel title="Forward return distribution" meta="analogue-weighted SPY paths"><EmptyMini message="No fan-chart distribution in this forecast." /></Panel>;
  const W = 620, H = 236, padL = 44, padR = 14, padT = 14, padB = 28;
  const xs = fan.map((_, i) => padL + (i / (fan.length - 1)) * (W - padL - padR));
  const all = fan.flatMap((d) => [d.p10, d.p90]);
  const mn = Math.min(...all, -2), mx = Math.max(...all);
  const y = (v: number) => padT + (1 - (v - mn) / (mx - mn)) * (H - padT - padB);
  const band = (lo: 'p10' | 'p25', hi: 'p90' | 'p75', op: number) => {
    const top = fan.map((d, i) => `${xs[i]},${y(d[hi])}`).join(' L');
    const bot = fan.slice().reverse().map((d, i) => `${xs[fan.length - 1 - i]},${y(d[lo])}`).join(' L');
    return <path d={`M${top} L${bot} Z`} fill={M.accent} opacity={op} />;
  };
  const medPath = `M${fan.map((d, i) => `${xs[i]},${y(d.med)}`).join(' L')}`;
  const activeIndex = hoverIndex === null ? null : Math.max(0, Math.min(fan.length - 1, hoverIndex));
  const active = activeIndex === null ? null : fan[activeIndex];
  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - rect.left) / rect.width) * W;
    const pct = (svgX - padL) / Math.max(1, W - padL - padR);
    setHoverIndex(Math.round(Math.max(0, Math.min(1, pct)) * (fan.length - 1)));
  };
  return (
    <Panel title="Forward return distribution" meta="Analogue-weighted SPY paths">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoverIndex(null)}
        style={{ width: '100%', height: 236, background: M.well, borderRadius: '12px', border: `1px solid ${M.line}`, cursor: 'crosshair', touchAction: 'none' }}
      >
        <line x1={padL} y1={y(0)} x2={W - padR} y2={y(0)} stroke={M.line2} strokeDasharray="3 3" />
        {band('p10', 'p90', 0.18)}
        {band('p25', 'p75', 0.32)}
        <path d={medPath} fill="none" stroke={M.accentBright} strokeWidth={2} />
        {fan.map((d, i) => <circle key={d.h} cx={xs[i]} cy={y(d.med)} r={2.4} fill={M.accentBright} />)}
        {active && activeIndex !== null ? (
          <g pointerEvents="none">
            <line x1={xs[activeIndex]} x2={xs[activeIndex]} y1={padT} y2={H - padB} stroke={M.accentBright} strokeWidth={0.9} opacity={0.72} strokeDasharray="3 3" />
            <circle cx={xs[activeIndex]} cy={y(active.med)} r={4} fill={M.well} stroke={M.accentBright} strokeWidth={1.5} />
            <g transform={`translate(${Math.min(W - 166, Math.max(padL + 8, xs[activeIndex] + 9))}, ${Math.max(padT + 5, y(active.med) - 44)})`}>
              <rect width={152} height={50} rx={7} fill={M.cardElev} stroke={M.line2} />
              <text x={9} y={13} fill={M.inkFaint} fontSize={9.5} fontFamily={M.mono}>{active.h}</text>
              <text x={9} y={28} fill={M.accentBright} fontSize={12} fontFamily={M.mono}>median {active.med > 0 ? '+' : ''}{active.med}%</text>
              <text x={9} y={43} fill={M.inkDim} fontSize={10} fontFamily={M.mono}>p10 {active.p10 > 0 ? '+' : ''}{active.p10}% · p90 {active.p90 > 0 ? '+' : ''}{active.p90}%</text>
            </g>
          </g>
        ) : null}
        {[mn, 0, mx].map((t) => (
          <text key={t} x={7} y={y(t) + 4} fill={M.inkFaint} fontSize={10} fontFamily={M.mono}>{t > 0 ? '+' : ''}{t.toFixed(0)}%</text>
        ))}
        {fan.map((d, i) => (
          <text key={d.h} x={xs[i]} y={H - 8} fill={M.inkFaint} fontSize={10} textAnchor="middle" fontFamily={M.mono}>{d.h}</text>
        ))}
      </svg>
    </Panel>
  );
}

function RiskProfileCompact({ f }: { f: Forecast }) {
  const fan63 = f.fan.find((d) => d.h === '63d');
  const fan252 = f.fan.find((d) => d.h === '252d');
  return (
    <Panel title="Risk profile / analogue set" meta={`${f.scenarios.reduce((sum, s) => sum + (s.n ?? 0), 0)} scenarios`}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
        <RiskCell k="MEDIAN / 63D" v={fan63?.med} suffix="%" sub={`win ${fan63?.win ?? '—'}%`} />
        <RiskCell k="MEDIAN / 252D" v={fan252?.med} suffix="%" sub={`win ${fan252?.win ?? '—'}%`} />
        <RiskCell k="P10 / 63D" v={fan63?.p10} suffix="%" sub="downside tail" />
        <RiskCell k="P90 / 252D" v={fan252?.p90} suffix="%" sub="upside tail" />
      </div>
      <a href="#macro-risk" style={{ display: 'inline-flex', gap: 8, alignItems: 'center', color: M.accentBright, textDecoration: 'none', fontSize: 12.5, marginTop: 10 }}>View full risk register →</a>
    </Panel>
  );
}

function EmptyMini({ message }: { message: string }) {
  return <div style={{ minHeight: 130, display: 'grid', placeItems: 'center', color: M.inkFaint, fontSize: 12, background: M.well, border: `1px solid ${M.line}`, borderRadius: 12 }}>{message}</div>;
}
function LegendSwatch({ color, label }: { color: string; label: string }) {
  return <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><span style={{ width: '12px', height: '12px', borderRadius: '3px', background: color, border: `1px solid ${M.line2}` }} />{label}</span>;
}
function RiskCell({ k, v, suffix, sub }: { k: string; v?: number; suffix: string; sub: string }) {
  const color = v === undefined ? M.ink : v > 0 ? M.pos : M.neg;
  return (
    <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: '12px', padding: '13px' }}>
      <div style={{ fontFamily: M.mono, fontSize: '9.5px', letterSpacing: '0.1em', color: M.inkFaint, marginBottom: '7px' }}>{k}</div>
      <ValueText value={v === undefined ? '—' : `${v > 0 ? '+' : ''}${v}${suffix}`} size={22} color={color} />
      <div style={{ fontFamily: M.sans, fontSize: '11px', color: M.inkFaint, marginTop: '5px' }}>{sub}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 5: Positioning + tensions
// ─────────────────────────────────────────────────────────────
function PositioningTensions({ f }: { f: Forecast }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)', gap: '20px' }} className="helix-fan-grid">
      <Panel title="Positioning read">
        <div style={{ marginBottom: '18px' }}>
          <Chip label="Preferred" color={M.pos} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '11px' }}>
            {f.preferred.map((x) => <Chip key={x} label={x} />)}
          </div>
        </div>
        <div>
          <Chip label="Avoid" color={M.neg} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '11px' }}>
            {f.avoid.map((x) => <Chip key={x} label={x} />)}
          </div>
        </div>
      </Panel>
      <Panel title="Key tensions">
        {f.tensions.map((t, i) => (
          <div key={i} style={{ display: 'flex', gap: '12px', padding: '13px 0', borderTop: i ? `1px solid ${M.line}` : 'none' }}>
            <span style={{ fontFamily: M.mono, fontSize: '12px', color: M.accentBright, paddingTop: '2px' }}>0{i + 1}</span>
            <span style={{ fontFamily: M.sans, fontSize: '13.5px', color: M.inkDim, lineHeight: 1.55 }}>{t}</span>
          </div>
        ))}
      </Panel>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 6: Indicator explorer
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
  const selectedIndicator = categoryItems.find((ind) => indicatorKey(ind) === selectedIndicatorKey) ?? null;

  useEffect(() => {
    if (!activeCategoryName || !categoryItems.length) return;
    if (!selectedIndicator) {
      setSelectedIndicatorKey(indicatorKey(categoryItems[0]));
    }
  }, [activeCategoryName, categoryItems, selectedIndicator]);

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
const backRowStyle: React.CSSProperties = {
  width: '100%',
  border: `1px solid ${M.line}`,
  background: M.well,
  color: M.accentBright,
  borderRadius: '10px',
  padding: '10px 11px',
  fontFamily: M.mono,
  fontSize: '11px',
  fontWeight: 600,
  textAlign: 'left',
  cursor: 'pointer',
};
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
function IndicatorDetail({ ind }: { ind: Indicator }) {
  const value = formatIndicatorValue(ind.val);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '18px', marginBottom: '18px' }}>
        <div>
          <div style={{ fontFamily: M.mono, fontSize: '10px', letterSpacing: '0.14em', textTransform: 'uppercase', color: M.inkFaint, marginBottom: '8px' }}>
            {ind.cat} · {ind.role.replace(/_/g, ' ')}
          </div>
          <h3 style={{ margin: 0, fontFamily: M.serif, fontSize: '26px', fontWeight: 500, color: M.ink, lineHeight: 1.08 }}>{ind.label}</h3>
        </div>
        <Chip label={ind.signal || 'neutral'} color={signalColor(ind.signal)} />
      </div>
      <ValueText value={value} size={42} color={signalColor(ind.signal)} />
      <HistoryLineChart
        points={ind.history}
        color={signalColor(ind.signal)}
        height={220}
        yLabel={ind.unit || 'value'}
      />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px', marginTop: '16px' }}>
        <StatBox label="Trend" value={ind.trend || '—'} />
        <StatBox label="Confidence" value={ind.conf === null ? '—' : ind.conf.toFixed(2)} />
        <StatBox label="Layer" value={ind.layer || '—'} />
        <StatBox label="Unit" value={ind.unit || '—'} />
        <StatBox label="History" value={ind.history.length ? `${ind.history.length} pts · ${formatHistorySource(ind.historySource)}` : '—'} />
      </div>
    </div>
  );
}
function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ background: M.cardElev, border: `1px solid ${M.line2}`, borderRadius: '12px', padding: '12px' }}>
      <div style={{ fontFamily: M.mono, fontSize: '9.5px', letterSpacing: '0.12em', textTransform: 'uppercase', color: M.inkFaint, marginBottom: '6px' }}>{label}</div>
      <div style={{ fontFamily: M.sans, fontSize: '13px', color: M.ink, fontWeight: 600, lineHeight: 1.35 }}>{value}</div>
    </div>
  );
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
  let mn = Math.min(...values);
  let mx = Math.max(...values);
  if (mn === mx) {
    mn -= 1;
    mx += 1;
  }
  const pad = (mx - mn) * 0.08;
  mn -= pad;
  mx += pad;
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
        <ChipCloud label="Preferred" color={M.pos} items={f.preferred} />
        <div style={{ height: 10 }} />
        <ChipCloud label="Avoid" color={M.neg} items={f.avoid} />
      </div>
      <div style={{ borderLeft: `1px solid ${M.line}`, paddingLeft: 18 }}>
        <MutedLabel>Key tensions</MutedLabel>
        {f.tensions.slice(0, 4).map((item, index) => (
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
      <ChipCloud label="Preferred" color={M.pos} items={f.preferred} />
      <ChipCloud label="Avoid" color={M.neg} items={f.avoid} />
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
function SnapChip({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div style={{ padding: '12px 14px', background: M.well, border: `1px solid ${M.line}`, borderRadius: '12px', borderLeft: accent ? `3px solid ${accent}` : `1px solid ${M.line}` }}>
      <div style={{ fontFamily: M.mono, fontSize: '10px', letterSpacing: '0.12em', textTransform: 'uppercase', color: M.inkFaint, fontWeight: 600, marginBottom: '5px' }}>{label}</div>
      <div style={{ fontFamily: M.sans, fontSize: '13.5px', color: M.ink, fontWeight: 600, lineHeight: 1.45 }}>{value}</div>
    </div>
  );
}
function ThemeCard({ theme }: { theme: NarrTheme }) {
  const sc = STANCE_COLOR[theme.stance.toLowerCase()] ?? M.inkFaint;
  const Row = ({ label, color, value }: { label: string; color: string; value: string }) =>
    value ? (
      <div style={{ display: 'flex', gap: '10px', marginBottom: '7px' }}>
        <span style={{ fontFamily: M.mono, fontSize: '10px', letterSpacing: '0.1em', textTransform: 'uppercase', color, fontWeight: 600, width: '70px', flexShrink: 0, paddingTop: '3px' }}>{label}</span>
        <p style={{ margin: 0, fontFamily: M.sans, fontSize: '13px', color: M.inkDim, lineHeight: 1.55, flex: 1 }}>{value}</p>
      </div>
    ) : null;
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
      <Row label="Reality" color={M.pos} value={theme.reality} />
      <Row label="Story" color={M.accentBright} value={theme.story} />
      <Row label="Price" color={M.inkFaint} value={theme.price} />
      <Row label="Gap" color={M.warn} value={theme.gap} />
      <Row label="Falsifier" color={M.neg} value={theme.falsifier} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Page
// ═══════════════════════════════════════════════════════════════════
export default function MacroPage() {
  const authFetcher = useAuthFetcher();

  // Forecast — falls back to embedded sample until the endpoint exists.
  const { data: forecastRaw } = useSWR<AnyRecord>(
    authFetcher.isSignedIn ? FORECAST_ENDPOINT : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
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
  const forecast = useMemo<Forecast>(
    () => normalizeForecast((forecastRaw as AnyRecord) ?? SAMPLE_FORECAST, indicatorHistory),
    [forecastRaw, indicatorHistory],
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
    <main style={{ background: M.canvas, minHeight: '100vh', color: M.canvasInk, fontFamily: M.sans }}>
      <div style={{ width: 'min(1460px, calc(100% - 44px))', margin: '0 auto', padding: '26px 0 46px', display: 'flex', flexDirection: 'column', gap: '9px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '18px', flexWrap: 'wrap', marginBottom: '4px' }}>
          <div>
            <Eyebrow>MACRO &amp; REGIME &gt; CURRENT READ</Eyebrow>
            <h1 style={{ fontFamily: M.serif, fontSize: '42px', fontWeight: 500, color: M.canvasInk, lineHeight: 1.02, margin: 0 }}>Macro Analysis</h1>
            <div style={{ fontFamily: M.sans, fontSize: '13px', color: M.canvasInkDim, lineHeight: 1.45, maxWidth: '960px', marginTop: 10 }}>
              {forecast.regimeRead || forecast.headline}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <div style={{ fontFamily: M.mono, fontSize: '11.5px', letterSpacing: '0.08em', color: M.canvasInkFaint, padding: '8px 11px', border: `1px solid ${M.line2}`, borderRadius: '999px' }}>Regime · {regime?.asof || '—'}</div>
            <div style={{ fontFamily: M.mono, fontSize: '11.5px', letterSpacing: '0.08em', color: M.canvasInkFaint, padding: '8px 11px', border: `1px solid ${M.line2}`, borderRadius: '999px' }}>Forecast · {forecast.asof || '—'}</div>
          </div>
        </div>

        {/* 1 — pulse + regime */}
        <div className="macro-top-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2.08fr) minmax(360px, 1fr)', gap: 10 }}>
          <MarketPulse f={forecast} regime={regime} scoreHistory={compositeScoreHistory} />
          <CurrentRegime f={forecast} regime={regime} />
        </div>

        {/* 2 — scenarios + return distribution + risk */}
        <div className="macro-mid-grid" style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.15fr) minmax(380px, 0.8fr) minmax(270px, 0.48fr)', gap: 10 }}>
          <ScenarioCards f={forecast} />
          <ForwardReturnDistribution f={forecast} />
          <RiskProfileCompact f={forecast} />
        </div>

        {/* 3 — compressed narrative */}
        <NarrativeSection result={narrResult} f={forecast} />

        {/* 4 — indicators */}
        <IndicatorExplorer f={forecast} />
      </div>

      {/* Responsive grid collapse */}
      <style>{`
        @media (max-width: 1280px) {
          .macro-mid-grid { grid-template-columns: 1fr !important; }
          .scenario-card-grid { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
        }
        @media (max-width: 980px) {
          .macro-top-grid, .macro-top-card-grid, .macro-narrative-grid { grid-template-columns: 1fr !important; }
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
  );
}

// ─────────────────────────────────────────────────────────────
// Embedded sample (from macro_forecast_2026-06-05). Keep this offline/dev
// fallback so the page still renders if the authenticated endpoint is down.
// ─────────────────────────────────────────────────────────────
const SAMPLE_FORECAST: AnyRecord = {"asof_date":"2026-06-05","horizon":"3m","probability_mode":"historically_calibrated","forecast_interpretation":{"headline":"Forecast favors reopening soft landing and broader market participation.","regime_read":"Reopening / Soft Landing leads; top macro-supported themes are Grid and power infrastructure, Quality ex-AI cash flow, Quality AI leaders.","summary":"The model assigns the highest probability to Reopening / Soft Landing at 37.7%; runner-up sticky_late_cycle_ai at 31.9%. The largest displayed deterministic driver is Breadth and participation (-0.297). Healthy credit can keep the regime from becoming fully risk-off, while weak breadth, restrictive Fed pricing, and resilient AI earnings determine whether leadership stays narrow. Reported scenario probabilities are historically calibrated after the deterministic update.","confidence_level":"low","confidence_rationale":"Dominant scenario probability is 37.7% with a 5.8% gap to the next scenario; floors keep tail scenarios alive. Probability mode is historically calibrated.","dominant_scenario_id":"reopening_soft_landing","dominant_scenario_probability":0.3766809534526288,"preferred_exposures":["Grid and power infrastructure","Quality ex-AI cash flow","Quality AI leaders","Cash and short duration","Commodities and real assets","Quality","Defensive factor","Cash and carry"],"exposures_to_avoid":["Small caps","High-beta AI semiconductors","Long-duration growth","High beta growth","Duration sensitivity","Small-cap beta"],"key_tensions":["Credit is healthy but breadth is weak or narrow.","Fed path remains restrictive despite some monetary-layer improvement.","Oil risk remains two-sided between inflation pressure and reopening relief.","AI earnings are resilient, but the AI capex rollover tail retains a probability floor."]},"scenario_probabilities":{"ai_capex_rollover":0.08206634437892787,"late_cycle_risk_off":0.11924393354997417,"oil_inflation_tail":0.10310646136127671,"reopening_soft_landing":0.3766809534526288,"sticky_late_cycle_ai":0.3189023072571924},"scenario_probabilities_deterministic":{"ai_capex_rollover":0.08240300063625414,"late_cycle_risk_off":0.05,"oil_inflation_tail":0.08900582905226531,"reopening_soft_landing":0.48991378132295726,"sticky_late_cycle_ai":0.28867738898852324},"historical_calibration":{"scenario_calibrations":[{"scenario_id":"reopening_soft_landing","historical_probability":0.11247102175519583,"confidence":0.6957200720072008,"n_supporting_analogues":6},{"scenario_id":"sticky_late_cycle_ai","historical_probability":0.3894271165507537,"confidence":0.5500000000000002,"n_supporting_analogues":19},{"scenario_id":"oil_inflation_tail","historical_probability":0.13600793674896997,"confidence":0.42739858578340156,"n_supporting_analogues":6},{"scenario_id":"ai_capex_rollover","historical_probability":0.08128081311183324,"confidence":0.45000000000000007,"n_supporting_analogues":4},{"scenario_id":"late_cycle_risk_off","historical_probability":0.2808131118332473,"confidence":0.6757471430116443,"n_supporting_analogues":13}],"forward_return_stats":{"10d":{"p10":-5.12,"p25":-1.59,"median":0.48,"p75":1.2,"p90":3.21,"pct_positive":57.3},"126d":{"p10":-2.34,"p25":-1.0,"median":2.59,"p75":7.98,"p90":9.68,"pct_positive":66.8},"1d":{"p10":-0.58,"p25":-0.34,"median":0.04,"p75":0.48,"p90":0.86,"pct_positive":55.7},"21d":{"p10":-4.5,"p25":-1.25,"median":1.18,"p75":2.42,"p90":4.5,"pct_positive":63.8},"252d":{"p10":-3.36,"p25":2.05,"median":11.97,"p75":17.66,"p90":23.84,"pct_positive":86.9},"5d":{"p10":-1.39,"p25":-0.42,"median":0.42,"p75":0.88,"p90":1.92,"pct_positive":61.2},"63d":{"p10":-11.63,"p25":-2.34,"median":3.17,"p75":5.14,"p90":7.43,"pct_positive":66.6}}},"input_signals":[{"label":"Monetary layer","name":"Monetary layer","category":"monetary","current_value":5.59,"signal":"mixed","trend":"improving","confidence":0.75,"role":"layer_summary","unit":"0-10 layer score","parent_layer":"monetary"},{"label":"Credit layer health","name":"Credit layer health","category":"credit","current_value":8.26,"signal":"bullish","trend":"stable","confidence":1.0,"role":"layer_summary","unit":"0-10 layer score","parent_layer":"credit"},{"label":"Volatility layer summary","name":"Volatility layer summary","category":"volatility","current_value":7.26,"signal":"bullish","trend":"stable","confidence":1.0,"role":"layer_summary","unit":"0-10 layer score","parent_layer":"volatility"},{"label":"Breadth and participation","name":"Breadth and participation","category":"breadth","current_value":4.39,"signal":"bearish","trend":"deteriorating","confidence":0.9,"role":"layer_summary","unit":"0-10 layer score","parent_layer":"breadth"},{"label":"Positioning and hedging","name":"Positioning and hedging","category":"positioning","current_value":7.25,"signal":"mixed","trend":"stable","confidence":1.0,"role":"layer_summary","unit":"generic put/call ratio or 0-10 score","parent_layer":"positioning"},{"label":"Fed path 2026-06-17","name":"Fed path 2026-06-17","category":"monetary","current_value":0.7999999999999999,"signal":"bearish","trend":"stable","confidence":0.75,"role":"raw_component","unit":"hold+hike probability","parent_layer":"monetary"},{"label":"Net liquidity","name":"Net liquidity","category":"monetary","current_value":-869002.2660000001,"signal":"neutral","trend":"stable","confidence":0.45,"role":"raw_component","unit":null,"parent_layer":"monetary"},{"label":"Net liquidity z-score","name":"Net liquidity z-score","category":"monetary","current_value":-0.23619626441240957,"signal":"neutral","trend":"stable","confidence":0.7,"role":"raw_component","unit":null,"parent_layer":"monetary"},{"label":"NFCI level","name":"NFCI level","category":"monetary","current_value":-0.495,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"monetary"},{"label":"NFCI inverted","name":"NFCI inverted","category":"monetary","current_value":0.7277653252468774,"signal":"bullish","trend":"stable","confidence":0.7,"role":"raw_component","unit":null,"parent_layer":"monetary"},{"label":"M2 growth YoY","name":"M2 growth YoY","category":"monetary","current_value":5.58,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"monetary"},{"label":"Hy Spread Level","name":"Hy Spread Level","category":"credit","current_value":276.0,"signal":"bullish","trend":"stable","confidence":0.75,"role":"raw_component","unit":null,"parent_layer":"credit"},{"label":"Hy Spread Z","name":"Hy Spread Z","category":"credit","current_value":-0.7745678361720062,"signal":"bullish","trend":"stable","confidence":0.75,"role":"raw_component","unit":null,"parent_layer":"credit"},{"label":"Hy Spread Chg 4W","name":"Hy Spread Chg 4W","category":"credit","current_value":-6.0,"signal":"neutral","trend":"stable","confidence":0.75,"role":"raw_component","unit":null,"parent_layer":"credit"},{"label":"Ig Spread Level","name":"Ig Spread Level","category":"credit","current_value":74.0,"signal":"bullish","trend":"stable","confidence":0.75,"role":"raw_component","unit":null,"parent_layer":"credit"},{"label":"Ig Spread Z","name":"Ig Spread Z","category":"credit","current_value":-1.2209252667371528,"signal":"bullish","trend":"stable","confidence":0.75,"role":"raw_component","unit":null,"parent_layer":"credit"},{"label":"Hyg Tlt Ratio Z","name":"Hyg Tlt Ratio Z","category":"credit","current_value":1.4186080775138064,"signal":"bullish","trend":"stable","confidence":0.75,"role":"raw_component","unit":null,"parent_layer":"credit"},{"label":"Vix Level","name":"Vix Level","category":"volatility","current_value":21.510000228881836,"signal":"neutral","trend":"stable","confidence":0.7,"role":"raw_component","unit":null,"parent_layer":"volatility"},{"label":"Vix Z 20D","name":"Vix Z 20D","category":"volatility","current_value":3.067421071997353,"signal":"bearish","trend":"stable","confidence":0.7,"role":"raw_component","unit":null,"parent_layer":"volatility"},{"label":"Vix Term Slope","name":"Vix Term Slope","category":"volatility","current_value":0.3099994659423828,"signal":"neutral","trend":"stable","confidence":0.7,"role":"raw_component","unit":null,"parent_layer":"volatility"},{"label":"Vvix Level","name":"Vvix Level","category":"volatility","current_value":102.04000091552734,"signal":"neutral","trend":"stable","confidence":0.7,"role":"raw_component","unit":null,"parent_layer":"volatility"},{"label":"Vvix Z","name":"Vvix Z","category":"volatility","current_value":0.1155892931006652,"signal":"neutral","trend":"stable","confidence":0.7,"role":"raw_component","unit":null,"parent_layer":"volatility"},{"label":"Skew Index","name":"Skew Index","category":"volatility","current_value":152.25,"signal":"bearish","trend":"stable","confidence":0.7,"role":"raw_component","unit":null,"parent_layer":"volatility"},{"label":"Pct Above 200D","name":"Pct Above 200D","category":"breadth","current_value":81.8,"signal":"bullish","trend":"improving","confidence":0.72,"role":"raw_component","unit":null,"parent_layer":"breadth"},{"label":"Sectors Green","name":"Sectors Green","category":"breadth","current_value":5.0,"signal":"neutral","trend":"stable","confidence":0.72,"role":"raw_component","unit":null,"parent_layer":"breadth"},{"label":"Rsp Vs Spy Z","name":"Rsp Vs Spy Z","category":"breadth","current_value":-0.7024383905995703,"signal":"bearish","trend":"deteriorating","confidence":0.72,"role":"raw_component","unit":null,"parent_layer":"breadth"},{"label":"Adl Slope","name":"Adl Slope","category":"breadth","current_value":0.6233082706766926,"signal":"bullish","trend":"improving","confidence":0.72,"role":"raw_component","unit":null,"parent_layer":"breadth"},{"label":"Cot Net Large Spec Z","name":"Cot Net Large Spec Z","category":"positioning","current_value":-1.625860339488422,"signal":"neutral","trend":"stable","confidence":0.65,"role":"raw_component","unit":null,"parent_layer":"positioning"},{"label":"Monetary policy composite","name":"Monetary policy composite","category":"monetary","current_value":"monetary_score=5.59; hold_hike=0.80; cut=0.20","signal":"mixed","trend":"mixed","confidence":0.6375,"role":"composite","unit":null,"parent_layer":"monetary"},{"label":"SPY return","name":"SPY return","category":"breadth","current_value":11.057166970154997,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"QQQ return","name":"QQQ return","category":"breadth","current_value":17.047628580207896,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"IWM return","name":"IWM return","category":"breadth","current_value":12.84523090942551,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"TLT return","name":"TLT return","category":"monetary","current_value":-1.4831129000213106,"signal":"bearish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"HYG return","name":"HYG return","category":"credit","current_value":1.1134123382579242,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"GLD return","name":"GLD return","category":"commodities","current_value":-15.210575684961247,"signal":"bearish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"USO return","name":"USO return","category":"commodities","current_value":-10.44704450201025,"signal":"bearish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"BTC return","name":"BTC return","category":"breadth","current_value":-21.696963318434502,"signal":"bearish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"RSP return","name":"RSP return","category":"breadth","current_value":9.82619089440786,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"HYG minus TLT risk-on proxy","name":"HYG minus TLT risk-on proxy","category":"credit","current_value":2.5965252382792348,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"RSP minus SPY participation proxy","name":"RSP minus SPY participation proxy","category":"breadth","current_value":-1.2309760757471366,"signal":"bearish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"IWM minus SPY small-cap leadership","name":"IWM minus SPY small-cap leadership","category":"breadth","current_value":1.788063939270513,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"QQQ minus SPY growth leadership","name":"QQQ minus SPY growth leadership","category":"breadth","current_value":5.990461610052899,"signal":"bullish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Market tape leadership top 3","name":"Market tape leadership top 3","category":"breadth","current_value":"Technology +27.9%, Financials +10.5%, Health Care +10.4%","signal":"mixed","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Market tape sector dispersion","name":"Market tape sector dispersion","category":"breadth","current_value":8.1538979878423,"signal":"bearish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Spy Above Vwap","name":"Spy Above Vwap","category":"breadth","current_value":0.0,"signal":"bearish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Spy Above Prev Close","name":"Spy Above Prev Close","category":"breadth","current_value":0.0,"signal":"bearish","trend":"stable","confidence":0.55,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Spy Clv","name":"Spy Clv","category":"breadth","current_value":-0.2614601539263484,"signal":"bearish","trend":"stable","confidence":0.5,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Spy Range Pct","name":"Spy Range Pct","category":"breadth","current_value":0.26446904269553584,"signal":"bullish","trend":"stable","confidence":0.5,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Spy Vol Z 20D","name":"Spy Vol Z 20D","category":"breadth","current_value":-2.987515761380753,"signal":"bearish","trend":"stable","confidence":0.5,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Volume Confirmation","name":"Volume Confirmation","category":"breadth","current_value":-2.987515761380753,"signal":"bearish","trend":"stable","confidence":0.5,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"Vix Change Pct 1D","name":"Vix Change Pct 1D","category":"volatility","current_value":8.050565932430498,"signal":"neutral","trend":"stable","confidence":0.5,"role":"raw_component","unit":null,"parent_layer":"market_state"},{"label":"AI earnings resilience","name":"AI earnings resilience","category":"earnings","current_value":"resilient","signal":"bullish","trend":"stable","confidence":0.36,"role":"regime_driver","unit":null,"parent_layer":"earnings"},{"label":"Oil shock and reopening optionality","name":"Oil shock and reopening optionality","category":"commodities","current_value":"two-sided","signal":"mixed","trend":"mixed","confidence":0.36,"role":"regime_driver","unit":null,"parent_layer":"commodities"},{"label":"Hyperscaler capex rollover falsifier","name":"Hyperscaler capex rollover falsifier","category":"earnings","current_value":"not_triggered","signal":"bullish","trend":"stable","confidence":0.55,"role":"scenario_falsifier","unit":null,"parent_layer":"earnings"}]} as AnyRecord;
