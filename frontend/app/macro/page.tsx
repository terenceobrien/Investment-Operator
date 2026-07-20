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
const NARRATIVE_TICKER = 'SPY';
const NARRATIVE_ENDPOINT = (ticker: string) => `/api/narrative/latest?ticker=${ticker}`;

type AnyRecord = Record<string, unknown>;

// ─────────────────────────────────────────────────────────────
// Generic safe accessors (mirrors the narrative page conventions)
// ─────────────────────────────────────────────────────────────
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
const pct1 = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`);

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

function signalColor(sig: string): string {
  return sig === 'bullish' ? M.pos : sig === 'bearish' ? M.neg : M.warn;
}

// ─────────────────────────────────────────────────────────────
// Forecast normalization — walk the deep macro_forecast JSON into a
// flat shape the components render from. This is deliberately defensive:
// every field is optional so a partial payload still renders.
// ─────────────────────────────────────────────────────────────
function normalizeForecast(raw: AnyRecord) {
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
    return {
      label: safeStr(s.label) || safeStr(s.name),
      cat: safeStr(s.category),
      layer: LAYER_NAMES[safeStr(s.category)] ?? safeStr(s.category),
      val: typeof cv === 'number' ? cv : safeStr(cv),
      signal: safeStr(s.signal),
      trend: safeStr(s.trend),
      conf: safeNum(s.confidence),
      role: safeStr(s.role),
      unit: safeStr(s.unit),
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
      background: prominent ? '#182541' : M.card,
      border: `1px solid ${prominent ? M.line2 : M.line}`,
      borderRadius: '16px',
      overflow: 'hidden',
      boxShadow: '0 24px 70px rgba(26,37,64,0.16)',
    }}>
      <div style={{ padding: '24px' }}>
        {title ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', marginBottom: '18px' }}>
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
function MarketPulse({ f }: { f: Forecast }) {
  return (
    <Panel title="Market pulse" meta={`${f.horizon.toUpperCase()} · ${f.probMode.replace(/_/g, ' ')}`} prominent>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '14px', flexWrap: 'wrap' }}>
        <h2 style={{ fontFamily: M.serif, fontSize: '26px', fontWeight: 500, color: M.ink, margin: 0, lineHeight: 1.12 }}>
          {f.confLevel === 'high' ? 'Constructive, high conviction' : f.confLevel === 'low' ? 'Constructive, selective' : 'Mixed, watchful'}
        </h2>
        <Chip label={`${pct1(f.dominantProb)} dominant`} color={M.accent} />
      </div>
      {f.composite !== null ? (
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px', margin: '18px 0 8px' }}>
          <ValueText value={f.composite.toFixed(1)} size={44} />
          <span style={{ fontFamily: M.mono, fontSize: '12px', fontWeight: 600, letterSpacing: '0.1em', color: M.accentBright, textTransform: 'uppercase' }}>composite regime score</span>
        </div>
      ) : null}
      <p style={{ margin: '18px 0 0', paddingTop: '18px', borderTop: `1px solid ${M.line}`, fontFamily: M.sans, fontSize: '14px', color: M.inkDim, lineHeight: 1.65 }}>
        {f.summary.split('. ').slice(0, 2).join('. ')}.
      </p>
    </Panel>
  );
}

function CurrentRegime({ f }: { f: Forecast }) {
  return (
    <Panel title="Current regime">
      <h2 style={{ fontFamily: M.serif, fontSize: '24px', fontWeight: 500, color: M.ink, lineHeight: 1.12, margin: '0 0 10px' }}>{f.dominantLabel}</h2>
      <p style={{ margin: '0 0 22px', fontFamily: M.sans, fontSize: '13.5px', color: M.inkDim, lineHeight: 1.6 }}>{f.regimeRead}</p>
      {f.layers.map((l) => (
        <div key={l.layer} style={{ marginBottom: '15px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', marginBottom: '7px' }}>
            <span style={{ fontFamily: M.sans, fontSize: '13px', fontWeight: 600, color: M.ink }}>{l.name}</span>
            <span style={{ fontFamily: M.mono, fontSize: '11.5px', color: M.inkFaint }}>{l.score.toFixed(1)} · {l.trend}</span>
          </div>
          <div style={{ height: '6px', background: M.well, borderRadius: '999px', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${Math.min(100, l.score * 10)}%`, background: signalColor(l.signal), borderRadius: '999px' }} />
          </div>
        </div>
      ))}
    </Panel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 2: Dominant scenario banner
// ─────────────────────────────────────────────────────────────
function DominantBanner({ f }: { f: Forecast }) {
  return (
    <section style={{ background: '#182541', border: `1px solid ${M.line2}`, borderRadius: '16px', overflow: 'hidden', boxShadow: '0 28px 80px rgba(24,37,65,0.22)' }}>
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
    <Panel title="Scenario distribution" meta={`${f.scenarios.length} scenarios · blended vs deterministic vs historical`}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px' }}>
        {f.scenarios.map((s, i) => {
          const top = i === 0 ? M.accentBright : s.blended >= 0.15 ? M.pos : M.neg;
          return (
            <div key={s.id} style={{ background: M.well, border: `1px solid ${M.line}`, borderTop: `3px solid ${top}`, borderRadius: '14px', padding: '18px' }}>
              <ValueText value={pct1(s.blended)} size={31} />
              <h3 style={{ fontFamily: M.serif, fontSize: '20px', fontWeight: 500, color: M.ink, margin: '10px 0 9px', lineHeight: 1.1 }}>{s.label}</h3>
              <p style={{ margin: '0 0 14px', fontFamily: M.sans, fontSize: '12.5px', color: M.inkDim, lineHeight: 1.5, minHeight: '76px' }}>{s.desc}</p>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: M.mono, fontSize: '10.5px', color: M.inkFaint, borderTop: `1px solid ${M.line}`, paddingTop: '10px' }}>
                <span>det {pct1(s.det)}</span><span>hist {pct1(s.hist)}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: M.mono, fontSize: '10.5px', color: M.inkFaint, paddingTop: '6px' }}>
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
function LegendSwatch({ color, label }: { color: string; label: string }) {
  return <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><span style={{ width: '12px', height: '12px', borderRadius: '3px', background: color, border: `1px solid ${M.line2}` }} />{label}</span>;
}
function RiskCell({ k, v, suffix, sub }: { k: string; v?: number; suffix: string; sub: string }) {
  const color = v === undefined ? M.ink : v > 0 ? M.pos : M.neg;
  return (
    <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: '14px', padding: '16px' }}>
      <div style={{ fontFamily: M.mono, fontSize: '10.5px', letterSpacing: '0.1em', color: M.inkFaint, marginBottom: '8px' }}>{k}</div>
      <ValueText value={v === undefined ? '—' : `${v > 0 ? '+' : ''}${v}${suffix}`} size={26} color={color} />
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

  const category = categories.find((c) => c.name === selectedCategory) ?? null;
  const categoryItems = category?.items ?? [];
  const selectedIndicator = categoryItems.find((ind) => indicatorKey(ind) === selectedIndicatorKey) ?? null;

  useEffect(() => {
    if (!selectedCategory || !categoryItems.length) return;
    if (!selectedIndicator) {
      setSelectedIndicatorKey(indicatorKey(categoryItems[0]));
    }
  }, [selectedCategory, categoryItems, selectedIndicator]);

  const selectCategory = (name: string, items: Indicator[]) => {
    setSelectedCategory(name);
    setSelectedIndicatorKey(items[0] ? indicatorKey(items[0]) : null);
  };

  return (
    <Panel title="Macro indicators" meta={`${f.indicators.length} model inputs`}>
      <div className="macro-indicator-shell" style={{ display: 'grid', gridTemplateColumns: '230px minmax(0, 1fr)', minHeight: '360px', border: `1px solid ${M.line}`, borderRadius: '14px', overflow: 'hidden', background: M.well }}>
        <div className="macro-indicator-rail" style={{ borderRight: `1px solid ${M.line}`, background: '#1A2746', padding: '12px' }}>
          {!category ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {categories.map((cat) => (
                <button key={cat.name} type="button" onClick={() => selectCategory(cat.name, cat.items)} style={railRowStyle(false)}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '9px', minWidth: 0 }}>
                    <SignalDot signal={cat.signal} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{cat.name}</span>
                  </span>
                  <span style={{ fontFamily: M.mono, color: M.inkFaint }}>{cat.count}</span>
                </button>
              ))}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <button type="button" onClick={() => { setSelectedCategory(null); setSelectedIndicatorKey(null); }} style={backRowStyle}>
                ← All categories
              </button>
              <div style={{ fontFamily: M.mono, fontSize: '10px', letterSpacing: '0.14em', color: M.inkFaint, textTransform: 'uppercase', padding: '8px 10px 4px' }}>
                {category.name} · {category.count}
              </div>
              {categoryItems.map((ind) => {
                const active = indicatorKey(ind) === selectedIndicatorKey;
                return (
                  <button key={indicatorKey(ind)} type="button" onClick={() => setSelectedIndicatorKey(indicatorKey(ind))} style={railRowStyle(active)}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '9px', minWidth: 0 }}>
                      <SignalDot signal={ind.signal} />
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ind.label}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <div style={{ padding: '22px' }}>
          {selectedIndicator ? <IndicatorDetail ind={selectedIndicator} /> : (
            <div style={{ height: '100%', minHeight: '300px', display: 'grid', placeItems: 'center', textAlign: 'center' }}>
              <div>
                <h3 style={{ margin: '0 0 8px', fontFamily: M.serif, fontSize: '24px', fontWeight: 500, color: M.ink }}>Select a category, then an indicator</h3>
                <p style={{ margin: 0, fontFamily: M.sans, fontSize: '13px', color: M.inkDim }}>The detail pane will show the signal, trend, confidence, value, and chart.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </Panel>
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
      <Sparkline seed={hashStr(ind.label)} color={signalColor(ind.signal)} tall />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '12px', marginTop: '16px' }}>
        <StatBox label="Trend" value={ind.trend || '—'} />
        <StatBox label="Confidence" value={ind.conf === null ? '—' : ind.conf.toFixed(2)} />
        <StatBox label="Layer" value={ind.layer || '—'} />
        <StatBox label="Unit" value={ind.unit || '—'} />
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
function hashStr(s: string): number { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 99991; return h + 1; }
function Sparkline({ seed, color, tall }: { seed: number; color: string; tall?: boolean }) {
  const n = 24; let x = (seed * 9301) % 233280 / 233280; const pts: number[] = [];
  for (let i = 0; i < n; i++) { x = (x * 9301 + 49297) % 233280 / 233280; pts.push((x - 0.5) * 1); }
  let acc = 0; const series = pts.map((p) => { acc = acc * 0.7 + p; return acc; });
  const mn = Math.min(...series), mx = Math.max(...series), rng = (mx - mn) || 1;
  const W = 200, H = tall ? 120 : 44;
  const d = series.map((p, i) => `${(i / (n - 1)) * W},${H - ((p - mn) / rng) * (H - 10) - 5}`).join(' L');
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: tall ? '120px' : '44px', marginTop: '14px', background: M.well, border: `1px solid ${M.line}`, borderRadius: '12px' }}>
      <path d={`M${d}`} fill="none" stroke={color} strokeWidth={2} />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────
// Section 7: Market narrative (SPY)
// ─────────────────────────────────────────────────────────────
function NarrativeSection({ result }: { result: AnyRecord | null }) {
  if (!result) {
    return (
      <Panel title="Market narrative · SPY">
        <div style={{ padding: '28px 8px', fontFamily: M.sans, fontSize: '13px', color: M.inkDim }}>
          No cached SPY narrative read available yet. It will appear here once generated.
        </div>
      </Panel>
    );
  }
  const snap = extractSnapshot(result);
  const themes = normalizeThemes(result);
  const inefficiency = extractInefficiency(result, themes);
  const watch = extractWatchpoints(result, themes);

  return (
    <>
      <Panel title="Market narrative · SPY" meta="Reality · story · price">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: snap.bullets.length ? '18px' : 0 }}>
          {snap.regimeTone ? <SnapChip label="Regime Tone" value={snap.regimeTone} accent={STANCE_COLOR[snap.regimeTone.toLowerCase()] ?? M.inkFaint} /> : null}
          {snap.primaryGap ? <SnapChip label="Primary Gap" value={snap.primaryGap} accent={M.warn} /> : null}
          {snap.primaryArchetype ? <SnapChip label="Primary Archetype" value={snap.primaryArchetype} accent={M.accentBright} /> : null}
          {snap.priceConfirmation ? <SnapChip label="Price Confirmation" value={snap.priceConfirmation} /> : null}
          {snap.confidence !== null ? <SnapChip label="Confidence" value={`${snap.confidence}/100`} /> : null}
        </div>
        {snap.bullets.map((b) => (
          <div key={b.label} style={{ display: 'flex', gap: '12px', alignItems: 'flex-start', marginBottom: '11px' }}>
            <span style={{ flexShrink: 0, width: '68px', fontFamily: M.mono, fontSize: '10px', letterSpacing: '0.12em', textTransform: 'uppercase', fontWeight: 600, marginTop: '4px', color: b.label === 'Reality' ? M.pos : b.label === 'Story' ? M.accentBright : M.inkFaint }}>{b.label}</span>
            <p style={{ margin: 0, fontFamily: M.sans, fontSize: '14px', color: M.inkDim, lineHeight: 1.65 }}>{b.text}</p>
          </div>
        ))}
      </Panel>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '20px' }} className="helix-fan-grid">
        <Panel title="Dominant themes" meta={`${themes.length} theme${themes.length !== 1 ? 's' : ''}`}>
          {themes.length === 0 ? (
            <div style={{ padding: '20px 4px', fontFamily: M.sans, fontSize: '13px', color: M.inkDim }}>No dominant themes identified.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {themes.slice(0, 4).map((t, i) => <ThemeCard key={i} theme={t} />)}
            </div>
          )}
        </Panel>
        <Panel title="Inefficiency map">
          {inefficiency.length === 0 ? (
            <div style={{ padding: '20px 4px', fontFamily: M.sans, fontSize: '13px', color: M.inkDim }}>No explicit inefficiency classifications in this run.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {inefficiency.map((row, i) => (
                <div key={i} style={{ background: M.well, border: `1px solid ${M.line}`, borderLeft: `3px solid ${M.warn}`, borderRadius: '12px', padding: '13px 14px' }}>
                  <div style={{ display: 'flex', gap: '10px', marginBottom: '8px' }}>
                    <span style={{ fontFamily: M.mono, fontSize: '11px', color: M.inkFaint, paddingTop: '2px' }}>{i + 1}.</span>
                    <span style={{ fontFamily: M.serif, fontSize: '17px', fontWeight: 500, color: M.ink, lineHeight: 1.18 }}>{row.subject}</span>
                  </div>
                  {row.gap ? <div style={{ fontFamily: M.sans, fontSize: '12.5px', color: M.inkDim, lineHeight: 1.55, marginBottom: row.archetype || row.confidence !== null ? '8px' : 0 }}>{row.gap}</div> : null}
                  {(row.archetype || row.confidence !== null) ? (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      {row.archetype ? <Chip label={truncate(row.archetype, 40)} color={M.accentBright} /> : null}
                      {row.underlyingGapType ? <Chip label={row.underlyingGapType.replace(/_/g, ' ')} /> : null}
                      {row.confidence !== null ? <Chip label={`${row.confidence}/100`} /> : null}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {watch.length ? (
        <Panel title="Watchpoints">
          <MutedLabel>Top watchpoints</MutedLabel>
          <ol style={{ margin: 0, paddingLeft: '20px' }}>
            {watch.map((w, i) => (
              <li key={i} style={{ fontFamily: M.sans, fontSize: '13.5px', color: M.inkDim, lineHeight: 1.6, marginBottom: '7px' }}>{w}</li>
            ))}
          </ol>
        </Panel>
      ) : null}
    </>
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
  const [stacked, setStacked] = useState(false);

  useEffect(() => {
    const update = () => setStacked(window.innerWidth < 980);
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  // Forecast — falls back to embedded sample until the endpoint exists.
  const { data: forecastRaw } = useSWR<AnyRecord>(
    authFetcher.isSignedIn ? FORECAST_ENDPOINT : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const forecast = useMemo<Forecast>(
    () => normalizeForecast((forecastRaw as AnyRecord) ?? SAMPLE_FORECAST),
    [forecastRaw],
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

  const twoCol: React.CSSProperties = stacked
    ? { display: 'flex', flexDirection: 'column', gap: '20px' }
    : { display: 'grid', gridTemplateColumns: 'minmax(0, 1.9fr) minmax(0, 1fr)', gap: '20px' };

  return (
    <main style={{ background: M.canvas, minHeight: '100vh', color: M.canvasInk, fontFamily: M.sans }}>
      <div style={{ width: 'min(1280px, calc(100% - 48px))', margin: '0 auto', padding: '34px 0 76px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: '18px', flexWrap: 'wrap', marginBottom: '2px' }}>
          <div>
            <Eyebrow>01 / MACRO &amp; REGIME</Eyebrow>
            <h1 style={{ fontFamily: M.serif, fontSize: '38px', fontWeight: 500, color: M.canvasInk, lineHeight: 1.02, margin: 0 }}>What matters now</h1>
          </div>
          <div style={{ fontFamily: M.mono, fontSize: '11.5px', letterSpacing: '0.08em', color: M.canvasInkFaint, padding: '8px 11px', border: `1px solid ${M.canvasInkFaint}55`, borderRadius: '999px' }}>Model run · {forecast.asof || '—'}</div>
        </div>

        <div style={{ fontFamily: M.sans, fontSize: '15px', color: M.canvasInkDim, lineHeight: 1.55, maxWidth: '760px', marginTop: '-8px' }}>
          {forecast.regimeRead || forecast.headline}
        </div>

        {/* 1 — pulse + regime */}
        <div style={twoCol}>
          <MarketPulse f={forecast} />
          <CurrentRegime f={forecast} />
        </div>

        {/* 2 — dominant banner */}
        <DominantBanner f={forecast} />

        {/* 3 — scenarios */}
        <ScenarioCards f={forecast} />

        {/* 4 — fan + risk */}
        <FanChart f={forecast} />

        {/* 5 — positioning + tensions */}
        <PositioningTensions f={forecast} />

        {/* 6 — indicators */}
        <IndicatorExplorer f={forecast} />

        {/* 7 — SPY narrative */}
        <NarrativeSection result={narrResult} />
      </div>

      {/* Responsive grid collapse */}
      <style>{`
        @media (max-width: 980px) {
          .helix-fan-grid { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 720px) {
          .macro-indicator-shell { grid-template-columns: 1fr !important; }
          .macro-indicator-rail { border-right: none !important; border-bottom: 1px solid ${M.line} !important; }
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
