'use client';

import { useState, useCallback, useEffect } from 'react';
import { T, sx, formatNumber, formatAccountingPct } from '@/lib/tokens';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

// ── Types ─────────────────────────────────────────────────────────────────────

interface LayerWeights {
  monetary:    number;
  credit:      number;
  volatility:  number;
  breadth:     number;
  positioning: number;
}

interface LayerThresholds {
  hy_spread_tight:         number;
  hy_spread_stressed:      number;
  vix_calm:                number;
  vix_stressed:            number;
  vix_term_backwardation:  number;
  breadth_strong:          number;
  breadth_weak:            number;
  sectors_strong:          number;
  sectors_weak:            number;
  m2_growth_strong:        number;
  m2_growth_weak:          number;
  bull_score:              number;
  bear_score:              number;
  chop_agreement:          number;
}

interface EnvStat {
  count:            number;
  pct_days:         number;
  fwd_5d:           { median?: number; pct_positive?: number; p25?: number; p75?: number; n: number };
  fwd_21d:          { median?: number; pct_positive?: number; n: number };
  fwd_63d:          { median?: number; pct_positive?: number; n: number };
  reward_risk_5d:   number | null;
  win_rate_5d:      number | null;
  ev_5d:            number | null;
}

interface BacktestResult {
  n_days:       number;
  date_range:   { start: string; end: string };
  env_stats:    Record<string, EnvStat>;
  score_dist:   { mean: number; median: number; pct_bull: number; pct_bear: number };
  score_series: { date: string; score_total: number; environment: string }[];
  env_counts:   Record<string, number>;
}

interface ScorePoint {
  date:        string;
  score:       number;
  environment: string;
}

interface HorizonStats {
  median:       number | null;
  pct_positive: number | null;
  p25:          number | null;
  p75:          number | null;
}

interface ThresholdInstance {
  date:         string;
  score:        number;
  environment:  string;
  vix:          number | null;
  fwd_5d:       number | null;
  fwd_21d:      number | null;
  fwd_63d:      number | null;
  forward_path: number[];
}

interface ThresholdResult {
  instances: ThresholdInstance[];
  summary: {
    n:       number;
    fwd_5d:  HorizonStats;
    fwd_21d: HorizonStats;
    fwd_63d: HorizonStats;
  };
}

// ── Default values ────────────────────────────────────────────────────────────

const DEFAULT_WEIGHTS: LayerWeights = {
  monetary: 0.20, credit: 0.22, volatility: 0.22, breadth: 0.20, positioning: 0.16,
};

const DEFAULT_THRESHOLDS: LayerThresholds = {
  hy_spread_tight: 350, hy_spread_stressed: 600,
  vix_calm: 15, vix_stressed: 30, vix_term_backwardation: -2,
  breadth_strong: 70, breadth_weak: 40,
  sectors_strong: 7, sectors_weak: 3,
  m2_growth_strong: 8, m2_growth_weak: 0,
  bull_score: 70, bear_score: 38, chop_agreement: 0.4,
};

const ENV_COLOR: Record<string, string> = {
  'Trend Day — Broad Participation': T.up,
  'Risk-On — Liquidity Driven':      T.up,
  'Risk-On Rotation Day':            '#168A5A',
  'Risk-Off / Headline Risk':        T.dn,
  'Chop / Layer Divergence':         T.wa,
  'Fear Exhaustion — Mean Reversion Setup': '#4FA3A5',
  'Mixed / Neutral':                 T.accent,
};

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.4px', textTransform: 'uppercase', color: T.label, marginBottom: '12px', fontWeight: 500 }}>
      {children}
    </div>
  );
}

function WeightSlider({ label, description, value, onChange }: {
  label: string;
  description: string;
  value: number;
  onChange: (v: number) => void;
}) {
  const pct = Math.round(value * 100);
  const fill = value > 0.25 ? T.up : value < 0.10 ? T.dn : T.wa;
  return (
    <div style={{ padding: '12px 0', borderBottom: `1px solid ${T.borderSub}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
        <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textSub, textTransform: 'capitalize' }}>{label}</span>
        <span style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 300, color: fill }}>{pct}%</span>
      </div>
      <p style={{ fontFamily: T.sans, fontSize: '11px', color: T.textMuted, margin: '0 0 8px', lineHeight: 1.4 }}>{description}</p>
      <input
        type="range" min={0} max={50} step={1}
        value={pct}
        onChange={e => onChange(parseInt(e.target.value) / 100)}
        style={{ width: '100%', accentColor: fill, cursor: 'pointer' }}
      />
    </div>
  );
}

function ThresholdInput({ label, description, value, onChange, suffix = '', step = 1 }: {
  label: string;
  description: string;
  value: number;
  onChange: (v: number) => void;
  suffix?: string;
  step?: number;
}) {
  return (
    <div style={{ padding: '10px 0', borderBottom: `1px solid ${T.borderSub}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
        <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textSub }}>{label}</span>
        <input
          type="number"
          value={value}
          step={step}
          onChange={e => onChange(parseFloat(e.target.value))}
          style={{
            fontFamily: T.mono, fontSize: '13px', fontWeight: 300,
            color: T.text, background: 'rgba(16,32,51,0.04)',
            border: `1px solid ${T.border}`, padding: '3px 8px',
            width: '80px', textAlign: 'right', outline: 'none',
          }}
        />
      </div>
      <p style={{ fontFamily: T.sans, fontSize: '11px', color: T.textMuted, margin: 0, lineHeight: 1.4 }}>{description}</p>
    </div>
  );
}

function EnvResultCard({ env, stat }: { env: string; stat: EnvStat }) {
  const color = ENV_COLOR[env] ?? T.mid;
  const fwd5  = stat.fwd_5d;
  const fwd21 = stat.fwd_21d;
  const isPos5 = (fwd5.median ?? 0) >= 0;
  return (
    <div style={{ background: 'rgba(16,32,51,0.02)', border: `1px solid ${T.border}`, borderLeft: `3px solid ${color}`, padding: '16px 20px', marginBottom: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <div style={{ fontFamily: T.sans, fontSize: '12px', fontWeight: 500, color, letterSpacing: '0.5px', marginBottom: '3px' }}>{env}</div>
          <div style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>{stat.count} days · {stat.pct_days.toFixed(1)}% of history</div>
        </div>
        {stat.ev_5d !== null && (
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '2px' }}>EV (5d)</div>
            <div style={{ fontFamily: T.mono, fontSize: '18px', fontWeight: 300, color: (stat.ev_5d ?? 0) >= 0 ? T.up : T.dn }}>
              {formatAccountingPct(stat.ev_5d)}
            </div>
          </div>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px,1fr))', gap: '12px' }}>
        {[
          { label: '5D median', val: fwd5.median, color: isPos5 ? T.up : T.dn, fmt: formatAccountingPct },
          { label: '5D win%',   val: fwd5.pct_positive, color: T.mid, fmt: (v: number) => `${v.toFixed(0)}%` },
          { label: '21D median', val: fwd21.median, color: (fwd21.median ?? 0) >= 0 ? T.up : T.dn, fmt: formatAccountingPct },
          { label: 'Rwd/risk',  val: stat.reward_risk_5d, color: T.mid, fmt: (v: number) => `${v.toFixed(1)}×` },
        ].map(({ label, val, color: c, fmt }) => (
          <div key={label}>
            <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '4px' }}>{label}</div>
            <div style={{ fontFamily: T.mono, fontSize: '15px', fontWeight: 300, color: c }}>
              {val != null ? fmt(val) : '—'}
            </div>
          </div>
        ))}
      </div>
      {fwd5.p25 != null && fwd5.p75 != null && (
        <div style={{ marginTop: '10px', fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>
          5D range: <span style={{ color: T.dn }}>{formatAccountingPct(fwd5.p25)}</span>
          {' → '}
          <span style={{ color: T.up }}>{formatAccountingPct(fwd5.p75)}</span>
        </div>
      )}
    </div>
  );
}

function ScoreChart({ series }: { series: { date: string; score_total: number; environment: string }[] }) {
  if (!series.length) return null;
  const W = 800; const H = 120;
  const pad = { l: 36, r: 8, t: 8, b: 20 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;
  const scores = series.map(s => s.score_total);
  const min = Math.min(...scores, 0);
  const max = Math.max(...scores, 100);
  const range = max - min || 1;
  const pts = series.map((s, i) => {
    const x = pad.l + (i / (series.length - 1)) * plotW;
    const y = pad.t + ((max - s.score_total) / range) * plotH;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const bullY = pad.t + ((max - 70) / range) * plotH;
  const bearY = pad.t + ((max - 38) / range) * plotH;
  return (
    <div style={{ marginTop: '16px' }}>
      <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>Score history</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '120px' }}>
        <line x1={pad.l} y1={bullY} x2={W - pad.r} y2={bullY} stroke={`${T.up}40`} strokeWidth="0.5" strokeDasharray="4,4" />
        <line x1={pad.l} y1={bearY} x2={W - pad.r} y2={bearY} stroke={`${T.dn}40`} strokeWidth="0.5" strokeDasharray="4,4" />
        <text x={pad.l - 4} y={bullY + 3} textAnchor="end" style={{ fontFamily: T.mono, fontSize: '8px', fill: T.textMuted }}>70</text>
        <text x={pad.l - 4} y={bearY + 3} textAnchor="end" style={{ fontFamily: T.mono, fontSize: '8px', fill: T.textMuted }}>38</text>
        <polyline points={pts} fill="none" stroke={T.accent} strokeWidth="1" />
      </svg>
    </div>
  );
}

// ── Score History Chart (large, full-width) ────────────────────────────────────

function ScoreHistoryChart({ series, thresholdVal, isCustom }: {
  series:       ScorePoint[];
  thresholdVal: number;
  isCustom:     boolean;
}) {
  if (!series.length) return null;

  const W = 1200; const H = 300;
  const pad = { l: 48, r: 32, t: 24, b: 36 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;

  const timestamps = series.map(s => new Date(s.date).getTime());
  const minD = Math.min(...timestamps);
  const maxD = Math.max(...timestamps);
  const rangeD = maxD - minD || 1;

  const toX = (d: string) => pad.l + ((new Date(d).getTime() - minD) / rangeD) * plotW;
  const toY = (score: number) => pad.t + (1 - score / 100) * plotH;

  const pts = series.map(s => `${toX(s.date).toFixed(1)},${toY(s.score).toFixed(1)}`).join(' ');

  // Year grid lines
  const firstYear = new Date(minD).getFullYear();
  const lastYear  = new Date(maxD).getFullYear();
  const years: number[] = [];
  for (let y = firstYear; y <= lastYear + 1; y++) years.push(y);

  const y38 = toY(38); const y50 = toY(50); const y70 = toY(70);
  const yThr = toY(Math.max(0, Math.min(100, thresholdVal)));

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.4px', textTransform: 'uppercase', color: T.label }}>
          Score history
        </div>
        <span style={{
          fontFamily: T.mono, fontSize: '10px', letterSpacing: '0.5px',
          color: isCustom ? T.accent : T.textMuted,
          background: isCustom ? `${T.accent}18` : 'rgba(16,32,51,0.04)',
          border: `1px solid ${isCustom ? `${T.accent}50` : T.border}`,
          padding: '2px 10px',
        }}>
          {isCustom ? 'Custom strategy score' : 'Default score'}
        </span>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '300px', display: 'block' }}>
        {/* Regime band fills */}
        <rect x={pad.l} y={pad.t} width={plotW} height={y70 - pad.t} fill={`${T.up}07`} />
        <rect x={pad.l} y={y38}   width={plotW} height={pad.t + plotH - y38} fill={`${T.dn}07`} />

        {/* Year vertical grid lines */}
        {years.map(year => {
          const xPos = pad.l + ((new Date(`${year}-01-01`).getTime() - minD) / rangeD) * plotW;
          if (xPos < pad.l - 1 || xPos > W - pad.r + 1) return null;
          return (
            <g key={year}>
              <line x1={xPos} y1={pad.t} x2={xPos} y2={pad.t + plotH} stroke={T.border} strokeWidth="0.5" />
              <text x={xPos} y={H - 6} textAnchor="middle"
                style={{ fontFamily: T.mono, fontSize: '9px', fill: T.textMuted }}>
                {year}
              </text>
            </g>
          );
        })}

        {/* Horizontal reference lines */}
        <line x1={pad.l} y1={y70} x2={W - pad.r} y2={y70} stroke={`${T.up}35`} strokeWidth="0.6" strokeDasharray="4,6" />
        <line x1={pad.l} y1={y50} x2={W - pad.r} y2={y50} stroke={`${T.mid}`}   strokeWidth="0.5" strokeDasharray="3,7" />
        <line x1={pad.l} y1={y38} x2={W - pad.r} y2={y38} stroke={`${T.dn}35`} strokeWidth="0.6" strokeDasharray="4,6" />

        {/* Y labels */}
        <text x={pad.l - 8} y={y70 + 3} textAnchor="end" style={{ fontFamily: T.mono, fontSize: '9px', fill: `${T.up}90` }}>70</text>
        <text x={pad.l - 8} y={y50 + 3} textAnchor="end" style={{ fontFamily: T.mono, fontSize: '9px', fill: T.textMuted }}>50</text>
        <text x={pad.l - 8} y={y38 + 3} textAnchor="end" style={{ fontFamily: T.mono, fontSize: '9px', fill: `${T.dn}90` }}>38</text>

        {/* X baseline */}
        <line x1={pad.l} y1={pad.t + plotH} x2={W - pad.r} y2={pad.t + plotH} stroke={T.border} strokeWidth="0.5" />

        {/* Main line — ghost shape */}
        <polyline points={pts} fill="none"
          stroke={isCustom ? T.accent : 'rgba(16,32,51,0.2)'}
          strokeWidth="0.7" />

        {/* Regime-colored dots */}
        {series.map((s, i) => (
          <circle
            key={i}
            cx={toX(s.date)}
            cy={toY(s.score)}
            r={1.6}
            fill={ENV_COLOR[s.environment] ?? T.mid}
            opacity={0.72}
          />
        ))}

        {/* Threshold marker line */}
        <line x1={pad.l} y1={yThr} x2={W - pad.r} y2={yThr}
          stroke={T.accent} strokeWidth="1.2" strokeDasharray="7,4" opacity={0.8} />
        <rect x={W - pad.r + 2} y={yThr - 7} width={26} height={13}
          fill={T.bg} />
        <text x={W - pad.r + 4} y={yThr + 4} textAnchor="start"
          style={{ fontFamily: T.mono, fontSize: '9px', fill: T.accent }}>
          {thresholdVal}
        </text>
      </svg>
    </div>
  );
}

// ── Fan Chart ─────────────────────────────────────────────────────────────────

function FanChart({ instances }: { instances: ThresholdInstance[] }) {
  const paths = instances.map(inst => inst.forward_path).filter(p => p.length > 0);
  if (!paths.length) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px' }}>
      <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted }}>No forward path data</span>
    </div>
  );

  const maxDays = Math.max(...paths.map(p => p.length));
  const allVals = paths.flat().filter(v => isFinite(v));
  if (!allVals.length) return null;

  const rawMin = Math.min(...allVals);
  const rawMax = Math.max(...allVals);
  const pad_y  = (rawMax - rawMin) * 0.1 || 1;
  const minV = rawMin - pad_y;
  const maxV = rawMax + pad_y;
  const rangeV = maxV - minV || 1;

  const W = 440; const H = 220;
  const pad = { l: 42, r: 12, t: 12, b: 28 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;

  const toX = (day: number) => pad.l + (day / Math.max(maxDays - 1, 1)) * plotW;
  const toY = (val: number) => pad.t + (1 - (val - minV) / rangeV) * plotH;

  const zeroY = toY(0);

  // Compute median path
  const medianPath: number[] = [];
  for (let d = 0; d < maxDays; d++) {
    const vals = paths.map(p => p[d]).filter(v => v != null && isFinite(v));
    if (!vals.length) break;
    vals.sort((a, b) => a - b);
    medianPath.push(vals[Math.floor(vals.length / 2)]);
  }

  const toPoints = (path: number[]) =>
    path.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`).join(' ');

  // Y tick values
  const yTicks = [-10, -5, 0, 5, 10].filter(v => v >= minV - 0.5 && v <= maxV + 0.5);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '220px', display: 'block' }}>
      {/* Zero line */}
      {zeroY >= pad.t && zeroY <= pad.t + plotH && (
        <line x1={pad.l} y1={zeroY} x2={W - pad.r} y2={zeroY}
          stroke={T.mid} strokeWidth="0.6" strokeDasharray="3,5" />
      )}

      {/* Y grid + labels */}
      {yTicks.map(tick => {
        const yPos = toY(tick);
        if (yPos < pad.t || yPos > pad.t + plotH) return null;
        return (
          <g key={tick}>
            <line x1={pad.l} y1={yPos} x2={W - pad.r} y2={yPos}
              stroke={T.border} strokeWidth="0.4" />
            <text x={pad.l - 6} y={yPos + 3} textAnchor="end"
              style={{ fontFamily: T.mono, fontSize: '8px', fill: T.textMuted }}>
              {tick > 0 ? `+${tick}` : tick}%
            </text>
          </g>
        );
      })}

      {/* X axis day labels */}
      {[0, 5, 10, 15, 21].filter(d => d < maxDays).map(d => (
        <g key={d}>
          <line x1={toX(d)} y1={pad.t + plotH} x2={toX(d)} y2={pad.t + plotH + 3}
            stroke={T.border} strokeWidth="0.5" />
          <text x={toX(d)} y={H - 4} textAnchor="middle"
            style={{ fontFamily: T.mono, fontSize: '8px', fill: T.textMuted }}>
            d{d}
          </text>
        </g>
      ))}

      {/* Individual instance paths */}
      {paths.map((path, i) => (
        <polyline key={i} points={toPoints(path)} fill="none"
          stroke={T.accent} strokeWidth="0.6" opacity={0.18} />
      ))}

      {/* Median overlay */}
      {medianPath.length > 1 && (
        <polyline points={toPoints(medianPath)} fill="none"
          stroke={T.accent} strokeWidth="2" opacity={0.9} />
      )}

      {/* Axes */}
      <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + plotH}
        stroke={T.border} strokeWidth="0.5" />
      <line x1={pad.l} y1={pad.t + plotH} x2={W - pad.r} y2={pad.t + plotH}
        stroke={T.border} strokeWidth="0.5" />
    </svg>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function StrategyPage() {
  const [weights,    setWeights]    = useState<LayerWeights>(DEFAULT_WEIGHTS);
  const [thresholds, setThresholds] = useState<LayerThresholds>(DEFAULT_THRESHOLDS);
  const [result,     setResult]     = useState<BacktestResult | null>(null);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState<string | null>(null);
  const [configName, setConfigName] = useState('');
  const [saved,      setSaved]      = useState<string | null>(null);
  const [startDate,  setStartDate]  = useState('2021-01-01');
  const [endDate,    setEndDate]    = useState('');

  // Score analysis state
  const [scoreHistory,       setScoreHistory]       = useState<ScorePoint[] | null>(null);
  const [scoreHistoryLoading, setScoreHistoryLoading] = useState(false);
  const [thresholdVal,       setThresholdVal]       = useState(50);
  const [thresholdDir,       setThresholdDir]       = useState<'above' | 'below'>('above');
  const [secEnabled,         setSecEnabled]         = useState(false);
  const [secField,           setSecField]           = useState('vix_level');
  const [secOp,              setSecOp]              = useState('lt');
  const [secVal,             setSecVal]             = useState(20);
  const [thresholdResult,    setThresholdResult]    = useState<ThresholdResult | null>(null);
  const [thresholdLoading,   setThresholdLoading]   = useState(false);

  // Fetch score history on mount
  useEffect(() => {
    setScoreHistoryLoading(true);
    fetch(`${API_URL}/api/strategy/score-history`)
      .then(r => r.json())
      .then(data => setScoreHistory(data.series ?? []))
      .catch(() => setScoreHistory([]))
      .finally(() => setScoreHistoryLoading(false));
  }, []);

  // The chart series: prefer backtest result, fall back to CSV history
  const chartSeries: ScorePoint[] = result
    ? result.score_series.map(s => ({ date: s.date, score: s.score_total, environment: s.environment }))
    : (scoreHistory ?? []);
  const isCustomScore = result !== null;

  const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0);
  const weightWarning = Math.abs(totalWeight - 1.0) > 0.01;

  const runBacktest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/strategy/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          weights,
          thresholds,
          start_date: startDate || undefined,
          end_date:   endDate   || undefined,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `Error ${res.status}`);
      }
      setResult(await res.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [weights, thresholds, startDate, endDate]);

  const saveConfig = async () => {
    if (!configName.trim()) return;
    try {
      const res = await fetch(`${API_URL}/api/strategy/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: configName, weights, thresholds }),
      });
      if (!res.ok) throw new Error('Save failed');
      setSaved(configName);
      setTimeout(() => setSaved(null), 3000);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const resetDefaults = () => {
    setWeights(DEFAULT_WEIGHTS);
    setThresholds(DEFAULT_THRESHOLDS);
    setResult(null);
  };

  const findInstances = async () => {
    setThresholdLoading(true);
    try {
      const body: Record<string, unknown> = {
        score_threshold: thresholdVal,
        direction: thresholdDir,
      };
      if (secEnabled) {
        body.secondary_condition = { field: secField, operator: secOp, value: secVal };
      }
      const res = await fetch(`${API_URL}/api/strategy/threshold-instances`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `Error ${res.status}`);
      }
      setThresholdResult(await res.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setThresholdLoading(false);
    }
  };

  const setWeight = (key: keyof LayerWeights, val: number) =>
    setWeights(prev => ({ ...prev, [key]: val }));

  const setThreshold = (key: keyof LayerThresholds, val: number) =>
    setThresholds(prev => ({ ...prev, [key]: val }));

  const envOrder = [
    'Trend Day — Broad Participation',
    'Risk-On — Liquidity Driven',
    'Risk-On Rotation Day',
    'Mixed / Neutral',
    'Chop / Layer Divergence',
    'Fear Exhaustion — Mean Reversion Setup',
    'Risk-Off / Headline Risk',
  ];

  // Shared select style
  const selectStyle: React.CSSProperties = {
    fontFamily: T.mono, fontSize: '12px', color: T.text,
    background: 'rgba(16,32,51,0.05)', border: `1px solid ${T.border}`,
    padding: '5px 8px', outline: 'none', cursor: 'pointer',
  };

  const numInputStyle: React.CSSProperties = {
    fontFamily: T.mono, fontSize: '13px', color: T.text,
    background: 'rgba(16,32,51,0.05)', border: `1px solid ${T.border}`,
    padding: '5px 10px', outline: 'none', width: '72px', textAlign: 'right',
  };

  return (
    <main style={sx.main}>
      <div style={sx.pageShell}>
        <section style={sx.panel}>
          <div style={{ ...sx.panelHeader, justifyContent: 'space-between' }}>
            <span style={sx.sectionLabel}>Custom strategy</span>
            <span style={sx.sectionMeta}>Tune layer weights + thresholds · backtest against 2021–2026</span>
          </div>
        </section>

        <section style={sx.panel}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 380px) 1fr', minHeight: '80vh' }}>
            <div style={{ borderRight: `1px solid ${T.border}`, overflowY: 'auto' }}>
              <div style={{ padding: '18px 20px', borderBottom: `1px solid ${T.border}` }}>
                <SectionLabel>Date range</SectionLabel>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
                    style={{ fontFamily: T.mono, fontSize: '12px', color: T.text, background: 'rgba(16,32,51,0.04)', border: `1px solid ${T.border}`, padding: '5px 8px', flex: 1, outline: 'none' }} />
                  <span style={{ color: T.textMuted, fontSize: '12px' }}>→</span>
                  <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)}
                    placeholder="Today"
                    style={{ fontFamily: T.mono, fontSize: '12px', color: T.text, background: 'rgba(16,32,51,0.04)', border: `1px solid ${T.border}`, padding: '5px 8px', flex: 1, outline: 'none' }} />
                </div>
              </div>

              <div style={{ padding: '18px 20px', borderBottom: `1px solid ${T.border}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <SectionLabel>Layer weights</SectionLabel>
                  {weightWarning ? (
                    <span style={{ fontFamily: T.sans, fontSize: '11px', color: T.wa }}>
                      Sum: {(totalWeight * 100).toFixed(0)}% (auto-normalised)
                    </span>
                  ) : null}
                </div>
                {([
                  ['monetary', 'Monetary & liquidity — Fed balance sheet, M2 growth'],
                  ['credit', 'Credit & stress — HY/IG spreads, credit health'],
                  ['volatility', 'Volatility structure — VIX level, term slope, VVIX'],
                  ['breadth', 'Breadth & participation — stocks above 200d MA, sector breadth'],
                  ['positioning', 'Positioning & sentiment — put/call ratio (contrarian)'],
                ] as [keyof LayerWeights, string][]).map(([key, desc]) => (
                  <WeightSlider key={key} label={key} description={desc} value={weights[key]} onChange={v => setWeight(key, v)} />
                ))}
              </div>

              <div style={{ padding: '18px 20px', borderBottom: `1px solid ${T.border}` }}>
                <SectionLabel>Credit thresholds</SectionLabel>
                <ThresholdInput label="HY spread tight (bps)" value={thresholds.hy_spread_tight}
                  description="HY spreads below this = maximum credit health"
                  onChange={v => setThreshold('hy_spread_tight', v)} step={10} />
                <ThresholdInput label="HY spread stressed (bps)" value={thresholds.hy_spread_stressed}
                  description="HY spreads above this = maximum credit stress"
                  onChange={v => setThreshold('hy_spread_stressed', v)} step={10} />
              </div>

              <div style={{ padding: '18px 20px', borderBottom: `1px solid ${T.border}` }}>
                <SectionLabel>Volatility thresholds</SectionLabel>
                <ThresholdInput label="VIX calm level" value={thresholds.vix_calm}
                  description="VIX below this scores maximum calm"
                  onChange={v => setThreshold('vix_calm', v)} step={0.5} />
                <ThresholdInput label="VIX stressed level" value={thresholds.vix_stressed}
                  description="VIX above this scores maximum stress"
                  onChange={v => setThreshold('vix_stressed', v)} step={0.5} />
                <ThresholdInput label="Term backwardation" value={thresholds.vix_term_backwardation}
                  description="VIX3M minus VIX below this = backwardation (crisis signal)"
                  onChange={v => setThreshold('vix_term_backwardation', v)} step={0.5} />
              </div>

              <div style={{ padding: '18px 20px', borderBottom: `1px solid ${T.border}` }}>
                <SectionLabel>Breadth thresholds</SectionLabel>
                <ThresholdInput label="Breadth strong (%)" value={thresholds.breadth_strong}
                  description="% stocks above 200d MA above this = strong breadth"
                  onChange={v => setThreshold('breadth_strong', v)} />
                <ThresholdInput label="Breadth weak (%)" value={thresholds.breadth_weak}
                  description="% stocks above 200d MA below this = weak breadth"
                  onChange={v => setThreshold('breadth_weak', v)} />
                <ThresholdInput label="Sectors strong" value={thresholds.sectors_strong}
                  description="Sectors green above this = strong breadth (0-11)"
                  onChange={v => setThreshold('sectors_strong', v)} />
              </div>

              <div style={{ padding: '18px 20px', borderBottom: `1px solid ${T.border}` }}>
                <SectionLabel>Regime classification</SectionLabel>
                <ThresholdInput label="Bull score threshold" value={thresholds.bull_score}
                  description="Composite score above this triggers bull classification"
                  onChange={v => setThreshold('bull_score', v)} />
                <ThresholdInput label="Bear score threshold" value={thresholds.bear_score}
                  description="Composite score below this triggers bear classification"
                  onChange={v => setThreshold('bear_score', v)} />
                <ThresholdInput label="Chop agreement" value={thresholds.chop_agreement}
                  description="Layer agreement below this triggers Chop (0.0–1.0)"
                  onChange={v => setThreshold('chop_agreement', v)} step={0.05} />
              </div>

              <div style={{ padding: '18px 20px' }}>
                <button onClick={runBacktest} disabled={loading} style={{
                  width: '100%', padding: '10px', marginBottom: '8px',
                  background: loading ? 'rgba(16,32,51,0.04)' : T.accent,
                  color: loading ? T.textMuted : '#fff', border: 'none',
                  fontFamily: T.sans, fontSize: '13px', fontWeight: 500,
                  letterSpacing: '0.5px', cursor: loading ? 'not-allowed' : 'pointer',
                }}>
                  {loading ? 'Running backtest...' : 'Run backtest'}
                </button>
                <button onClick={resetDefaults} style={{
                  width: '100%', padding: '8px', background: 'transparent',
                  color: T.textMuted, border: `1px solid ${T.border}`,
                  fontFamily: T.sans, fontSize: '12px', cursor: 'pointer',
                }}>
                  Reset to defaults
                </button>

                <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: `1px solid ${T.border}` }}>
                  <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '8px' }}>
                    Save strategy
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <input value={configName} onChange={e => setConfigName(e.target.value)}
                      placeholder="Strategy name..."
                      style={{ flex: 1, fontFamily: T.mono, fontSize: '12px', color: T.text, background: 'rgba(16,32,51,0.04)', border: `1px solid ${T.border}`, padding: '6px 8px', outline: 'none' }} />
                    <button onClick={saveConfig} style={{
                      padding: '6px 12px', background: 'rgba(16,32,51,0.06)', color: T.textSub,
                      border: `1px solid ${T.border}`, fontFamily: T.sans, fontSize: '12px', cursor: 'pointer',
                    }}>
                      Save
                    </button>
                  </div>
                  {saved ? <p style={{ fontFamily: T.sans, fontSize: '11px', color: T.up, marginTop: '6px' }}>Saved &quot;{saved}&quot;</p> : null}
                </div>
              </div>
            </div>

            <div style={{ overflowY: 'auto', padding: '24px' }}>
              {error ? (
                <div style={{ background: 'rgba(184,85,85,0.1)', border: `1px solid ${T.dn}`, padding: '12px 16px', marginBottom: '16px' }}>
                  <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.dn }}>{error}</span>
                </div>
              ) : null}

              {!result && !loading ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '60vh', textAlign: 'center', gap: '12px' }}>
                  <div style={{ fontFamily: T.sans, fontSize: '15px', color: T.textSub }}>Adjust parameters and run backtest</div>
                  <div style={{ fontFamily: T.sans, fontSize: '13px', color: T.textMuted, maxWidth: '400px', lineHeight: 1.6 }}>
                    Your custom weights and thresholds will be applied to 2021–2026 market data.
                    Results show how each regime classification performed historically.
                  </div>
                </div>
              ) : null}

              {loading ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
                  <span style={{ fontFamily: T.mono, fontSize: '13px', color: T.textMuted }}>Running backtest across {(2021 - new Date().getFullYear()) * -252 + 252} trading days...</span>
                </div>
              ) : null}

              {result ? (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px,1fr))', gap: '12px', marginBottom: '24px' }}>
                    {[
                      { label: 'Trading days', val: result.n_days.toString() },
                      { label: 'Avg score', val: formatNumber(result.score_dist.mean, 1) },
                      { label: 'Bull days', val: `${result.score_dist.pct_bull.toFixed(1)}%` },
                      { label: 'Bear days', val: `${result.score_dist.pct_bear.toFixed(1)}%` },
                      { label: 'Date range', val: `${result.date_range.start} → ${result.date_range.end}` },
                    ].map(({ label, val }) => (
                      <div key={label} style={{ padding: '14px 16px', background: 'rgba(16,32,51,0.02)', border: `1px solid ${T.border}` }}>
                        <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>{label}</div>
                        <div style={{ fontFamily: T.mono, fontSize: '16px', fontWeight: 300, color: T.text }}>{val}</div>
                      </div>
                    ))}
                  </div>

                  <ScoreChart series={result.score_series} />

                  <div style={{ margin: '24px 0 12px' }}>
                    <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1.4px', textTransform: 'uppercase', color: T.label, marginBottom: '4px' }}>
                      Regime classification results
                    </div>
                    <div style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted, marginBottom: '16px' }}>
                      Forward return statistics for each regime under your custom parameters
                    </div>
                    {envOrder.filter(env => result.env_stats[env]).map(env => (
                      <EnvResultCard key={env} env={env} stat={result.env_stats[env]} />
                    ))}
                    {Object.keys(result.env_stats).filter(env => !envOrder.includes(env)).map(env => (
                      <EnvResultCard key={env} env={env} stat={result.env_stats[env]} />
                    ))}
                  </div>
                </>
              ) : null}
            </div>
          </div>
        </section>

        <section style={sx.panel}>
          <div style={sx.panelHeader}>
            <span style={sx.sectionLabel}>Score history</span>
            <span style={sx.sectionMeta}>Regime legend · full history chart</span>
          </div>
          <div style={sx.panelBody}>
            {scoreHistoryLoading && !chartSeries.length ? (
              <div style={{ ...sx.skeleton, height: '300px', borderRadius: '4px' }} />
            ) : (
              <ScoreHistoryChart series={chartSeries} thresholdVal={thresholdVal} isCustom={isCustomScore} />
            )}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: '14px' }}>
              {Object.entries(ENV_COLOR).map(([env, color]) => (
                <div key={env} style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <div style={{ width: '7px', height: '7px', borderRadius: '50%', background: color, flexShrink: 0 }} />
                  <span style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, letterSpacing: '0.3px' }}>{env}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section style={sx.panel}>
          <div style={sx.panelHeader}>
            <span style={sx.sectionLabel}>Threshold finder</span>
            <span style={sx.sectionMeta}>Filter score conditions and inspect forward paths</span>
          </div>
          <div style={sx.panelBody}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'flex-end' }}>
              <div>
                <div style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, letterSpacing: '0.8px', textTransform: 'uppercase', marginBottom: '5px' }}>Score</div>
                <input type="number" min={0} max={100} step={1} value={thresholdVal} onChange={e => setThresholdVal(Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)))} style={numInputStyle} />
              </div>

              <div>
                <div style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, letterSpacing: '0.8px', textTransform: 'uppercase', marginBottom: '5px' }}>Direction</div>
                <div style={{ display: 'flex' }}>
                  {(['above', 'below'] as const).map(dir => (
                    <button key={dir} onClick={() => setThresholdDir(dir)} style={{
                      padding: '5px 16px', fontFamily: T.mono, fontSize: '12px',
                      color: thresholdDir === dir ? T.accent : T.textMuted,
                      background: thresholdDir === dir ? `${T.accent}18` : 'rgba(16,32,51,0.03)',
                      border: `1px solid ${thresholdDir === dir ? `${T.accent}50` : T.border}`,
                      marginRight: '-1px', cursor: 'pointer',
                    }}>
                      {dir}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, letterSpacing: '0.8px', textTransform: 'uppercase', marginBottom: '5px' }}>Filter</div>
                <button onClick={() => setSecEnabled(p => !p)} style={{
                  padding: '5px 14px', fontFamily: T.mono, fontSize: '12px',
                  color: secEnabled ? T.accent : T.textMuted,
                  background: secEnabled ? `${T.accent}18` : 'rgba(16,32,51,0.03)',
                  border: `1px solid ${secEnabled ? `${T.accent}50` : T.border}`,
                  cursor: 'pointer',
                }}>
                  {secEnabled ? '+ condition on' : '+ condition'}
                </button>
              </div>

              {secEnabled ? (
                <>
                  <div>
                    <div style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, letterSpacing: '0.8px', textTransform: 'uppercase', marginBottom: '5px' }}>Field</div>
                    <select value={secField} onChange={e => setSecField(e.target.value)} style={selectStyle}>
                      <option value="vix_level">VIX Level</option>
                      <option value="hy_spread_level">HY Spreads</option>
                      <option value="layer_credit">Credit Layer</option>
                      <option value="layer_volatility">Volatility Layer</option>
                      <option value="layer_breadth">Breadth Layer</option>
                    </select>
                  </div>
                  <div>
                    <div style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, letterSpacing: '0.8px', textTransform: 'uppercase', marginBottom: '5px' }}>Operator</div>
                    <select value={secOp} onChange={e => setSecOp(e.target.value)} style={selectStyle}>
                      <option value="lt">&lt;</option>
                      <option value="lte">≤</option>
                      <option value="gt">&gt;</option>
                      <option value="gte">≥</option>
                    </select>
                  </div>
                  <div>
                    <div style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, letterSpacing: '0.8px', textTransform: 'uppercase', marginBottom: '5px' }}>Value</div>
                    <input type="number" step="any" value={secVal} onChange={e => setSecVal(parseFloat(e.target.value) || 0)} style={numInputStyle} />
                  </div>
                </>
              ) : null}

              <button onClick={findInstances} disabled={thresholdLoading} style={{
                padding: '6px 20px', background: thresholdLoading ? 'rgba(16,32,51,0.04)' : T.accent,
                color: thresholdLoading ? T.textMuted : '#fff', border: 'none', fontFamily: T.sans, fontSize: '12px', fontWeight: 500,
                letterSpacing: '0.5px', cursor: thresholdLoading ? 'not-allowed' : 'pointer',
              }}>
                {thresholdLoading ? 'Searching...' : 'Find instances'}
              </button>

              {thresholdResult && !thresholdLoading ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontFamily: T.mono, fontSize: '18px', fontWeight: 300, color: thresholdResult.summary.n < 15 ? T.wa : T.text }}>
                    {thresholdResult.summary.n}
                  </span>
                  <span style={{ fontFamily: T.sans, fontSize: '11px', color: T.textMuted }}>instances</span>
                  {thresholdResult.summary.n < 15 ? (
                    <span style={{ fontFamily: T.sans, fontSize: '10px', color: T.wa, background: `${T.wa}15`, border: `1px solid ${T.wa}40`, padding: '2px 8px', letterSpacing: '0.5px' }}>
                      Low sample — interpret with caution
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          </div>
        </section>

        {thresholdResult && !thresholdLoading ? (
          <section style={sx.panel}>
            <div style={sx.panelHeader}>
              <span style={sx.sectionLabel}>Threshold results</span>
              <span style={sx.sectionMeta}>{thresholdResult.summary.n} matching instances</span>
            </div>
            <div style={sx.panelBody}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr minmax(260px, 340px)', gap: '24px', marginBottom: '24px' }}>
                <div style={{ background: 'rgba(16,32,51,0.02)', border: `1px solid ${T.border}`, padding: '16px 20px' }}>
                  <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '10px' }}>
                    21-Day forward path — {thresholdResult.summary.n} instances
                  </div>
                  <FanChart instances={thresholdResult.instances} />
                  <div style={{ display: 'flex', gap: '16px', marginTop: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <div style={{ width: '20px', height: '1px', background: T.accent, opacity: 0.25 }} />
                      <span style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted }}>Individual</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <div style={{ width: '20px', height: '2px', background: T.accent }} />
                      <span style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted }}>Median</span>
                    </div>
                  </div>
                </div>

                <div style={{ background: 'rgba(16,32,51,0.02)', border: `1px solid ${T.border}`, padding: '16px 20px' }}>
                  <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '14px' }}>
                    Aggregate statistics
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr>
                        <th style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, fontWeight: 400, textAlign: 'left', paddingBottom: '8px', borderBottom: `1px solid ${T.border}` }}>Horizon</th>
                        <th style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, fontWeight: 400, textAlign: 'right', paddingBottom: '8px', borderBottom: `1px solid ${T.border}` }}>Median</th>
                        <th style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, fontWeight: 400, textAlign: 'right', paddingBottom: '8px', borderBottom: `1px solid ${T.border}` }}>% Pos</th>
                        <th style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, fontWeight: 400, textAlign: 'right', paddingBottom: '8px', borderBottom: `1px solid ${T.border}` }}>P25 / P75</th>
                      </tr>
                    </thead>
                    <tbody>
                      {([['5D', thresholdResult.summary.fwd_5d], ['21D', thresholdResult.summary.fwd_21d], ['63D', thresholdResult.summary.fwd_63d]] as [string, HorizonStats][]).map(([label, stats]) => {
                        const medianColor = stats.median == null ? T.textMuted : stats.median >= 0 ? T.up : T.dn;
                        return (
                          <tr key={label} style={{ borderBottom: `1px solid ${T.borderSub}` }}>
                            <td style={{ fontFamily: T.mono, fontSize: '12px', color: T.textSub, padding: '9px 0' }}>{label}</td>
                            <td style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 300, color: medianColor, textAlign: 'right', padding: '9px 0' }}>
                              {stats.median != null ? formatAccountingPct(stats.median / 100) : '—'}
                            </td>
                            <td style={{ fontFamily: T.mono, fontSize: '12px', color: T.textSub, textAlign: 'right', padding: '9px 0' }}>
                              {stats.pct_positive != null ? `${stats.pct_positive.toFixed(0)}%` : '—'}
                            </td>
                            <td style={{ fontFamily: T.mono, fontSize: '10px', color: T.textMuted, textAlign: 'right', padding: '9px 0' }}>
                              {stats.p25 != null && stats.p75 != null
                                ? <><span style={{ color: T.dn }}>{formatAccountingPct(stats.p25 / 100)}</span>{' / '}<span style={{ color: T.up }}>{formatAccountingPct(stats.p75 / 100)}</span></>
                                : '—'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>

                  <div style={{ marginTop: '16px', padding: '10px 12px', background: 'rgba(16,32,51,0.02)', border: `1px solid ${T.border}` }}>
                    <div style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted, lineHeight: 1.6 }}>
                      <span style={{ color: T.accent }}>{thresholdResult.summary.n}</span> days where score{' '}
                      <span style={{ color: T.text }}>{thresholdDir}</span>{' '}
                      <span style={{ color: T.accent }}>{thresholdVal}</span>
                      {secEnabled ? (
                        <> &amp; <span style={{ color: T.text }}>{secField}</span>{' '}
                          <span style={{ color: T.text }}>{secOp}</span>{' '}
                          <span style={{ color: T.accent }}>{secVal}</span>
                        </>
                      ) : null}
                    </div>
                  </div>
                </div>
              </div>

              <div style={{ background: 'rgba(16,32,51,0.015)', border: `1px solid ${T.border}` }}>
                <div style={{ padding: '12px 20px', borderBottom: `1px solid ${T.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted }}>
                    Instance detail · sorted newest first
                  </span>
                  <span style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>
                    {thresholdResult.instances.length} rows
                  </span>
                </div>

                <div style={{ overflowY: 'auto', maxHeight: '340px' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead style={{ position: 'sticky', top: 0, background: T.bg, zIndex: 1 }}>
                      <tr>
                        {['Date', 'Score', 'Environment', 'VIX', '5D', '21D', '63D'].map(col => (
                          <th key={col} style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, fontWeight: 400, textAlign: col === 'Date' || col === 'Environment' ? 'left' : 'right', padding: '8px 16px', borderBottom: `1px solid ${T.border}` }}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {thresholdResult.instances.map((inst, i) => {
                        const env_color = ENV_COLOR[inst.environment] ?? T.mid;
                        return (
                          <tr key={i} style={{ borderBottom: `1px solid ${T.borderSub}` }}>
                            <td style={{ fontFamily: T.mono, fontSize: '12px', color: T.textSub, padding: '7px 16px' }}>{inst.date}</td>
                            <td style={{ fontFamily: T.mono, fontSize: '12px', fontWeight: 300, color: T.text, textAlign: 'right', padding: '7px 16px' }}>{inst.score != null ? inst.score.toFixed(1) : '—'}</td>
                            <td style={{ fontFamily: T.sans, fontSize: '11px', color: env_color, padding: '7px 16px', maxWidth: '200px' }}><div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{inst.environment}</div></td>
                            <td style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted, textAlign: 'right', padding: '7px 16px' }}>{inst.vix != null ? inst.vix.toFixed(1) : '—'}</td>
                            {([inst.fwd_5d, inst.fwd_21d, inst.fwd_63d] as (number | null)[]).map((val, j) => (
                              <td key={j} style={{ fontFamily: T.mono, fontSize: '12px', fontWeight: 300, color: val == null ? T.textMuted : val >= 0 ? T.up : T.dn, textAlign: 'right', padding: '7px 16px' }}>
                                {val != null ? formatAccountingPct(val / 100) : '—'}
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
