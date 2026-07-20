'use client';

import { useMemo } from 'react';
import useSWR from 'swr';
import AuthRequired from '@/components/AuthRequired';
import { useAuthFetcher } from '../../lib/api';
import { M } from '../lib/researchOsTheme';

const RISK_ENDPOINT = '/api/portfolio/risk/latest';
const FORECAST_ENDPOINT = '/api/macro/forecast/latest';

type AnyRecord = Record<string, unknown>;
type PortfolioRisk = {
  strategy_label: string;
  ytd_return_pct: number;
  bench_ytd_pct: number;
  net_exposure_pct: number;
  cash_pct: number;
  portfolio_beta: number;
  effective_breadth: number;
  factor_tilt_sigma: number;
  risk_decomposition: { label: string; pct: number; kind: 'ai' | 'grid' | 'defensive' | 'idio' | 'cash' | string }[];
  factor_exposures: { label: string; beta: number }[];
  holdings: { ticker: string; name: string; weight_pct: number; beta_contrib: number; marginal_risk_pct: number | null; tag: string; aligned: boolean }[];
  exposure_tags: string[];
};

function safeObj(v: unknown): AnyRecord { return v && typeof v === 'object' ? v as AnyRecord : {}; }
function safeArray<T>(v: unknown): T[] { return Array.isArray(v) ? v as T[] : []; }
function safeStr(v: unknown, fallback = ''): string { return typeof v === 'string' ? v : fallback; }
function safeNum(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}
function fmtPct(v: number, digits = 1): string { return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`; }
function plainPct(v: number, digits = 0): string { return `${v.toFixed(digits)}%`; }

function unwrapPayload(raw: unknown): AnyRecord {
  const obj = safeObj(raw);
  if (obj.output) return safeObj(obj.output);
  if (obj.result) return safeObj(obj.result);
  const cached = safeObj(obj.last_cached_result);
  if (cached.output) return safeObj(cached.output);
  if (cached.result) return safeObj(cached.result);
  return obj;
}

function normalizeRisk(raw: unknown): PortfolioRisk {
  const r = unwrapPayload(raw);
  // TODO: real schema: map EWMA+Vasicek beta, ETF-proxy factors, stressed covariance,
  // risk decomposition, and effective breadth from the risk-stack output.
  return {
    strategy_label: safeStr(r.strategy_label, SAMPLE_RISK.strategy_label),
    ytd_return_pct: safeNum(r.ytd_return_pct, SAMPLE_RISK.ytd_return_pct),
    bench_ytd_pct: safeNum(r.bench_ytd_pct, SAMPLE_RISK.bench_ytd_pct),
    net_exposure_pct: safeNum(r.net_exposure_pct, SAMPLE_RISK.net_exposure_pct),
    cash_pct: safeNum(r.cash_pct, SAMPLE_RISK.cash_pct),
    portfolio_beta: safeNum(r.portfolio_beta, SAMPLE_RISK.portfolio_beta),
    effective_breadth: safeNum(r.effective_breadth, SAMPLE_RISK.effective_breadth),
    factor_tilt_sigma: safeNum(r.factor_tilt_sigma, SAMPLE_RISK.factor_tilt_sigma),
    risk_decomposition: safeArray<PortfolioRisk['risk_decomposition'][number]>(r.risk_decomposition).length ? safeArray<PortfolioRisk['risk_decomposition'][number]>(r.risk_decomposition) : SAMPLE_RISK.risk_decomposition,
    factor_exposures: safeArray<PortfolioRisk['factor_exposures'][number]>(r.factor_exposures).length ? safeArray<PortfolioRisk['factor_exposures'][number]>(r.factor_exposures) : SAMPLE_RISK.factor_exposures,
    holdings: safeArray<PortfolioRisk['holdings'][number]>(r.holdings).length ? safeArray<PortfolioRisk['holdings'][number]>(r.holdings) : SAMPLE_RISK.holdings,
    exposure_tags: safeArray<string>(r.exposure_tags).length ? safeArray<string>(r.exposure_tags) : SAMPLE_RISK.exposure_tags,
  };
}

function normalizeForecast(raw: unknown) {
  const r = unwrapPayload(raw);
  const fi = safeObj(r.forecast_interpretation);
  // TODO: real schema: keep this aligned with macro forecast interpretation fields.
  return {
    preferred: safeArray<string>(fi.preferred_exposures).length ? safeArray<string>(fi.preferred_exposures) : SAMPLE_ALIGNMENT.preferred,
    avoid: safeArray<string>(fi.exposures_to_avoid).length ? safeArray<string>(fi.exposures_to_avoid) : SAMPLE_ALIGNMENT.avoid,
  };
}

function Panel({ label, meta, children, elevated }: { label: string; meta?: string; children: React.ReactNode; elevated?: boolean }) {
  return (
    <section style={{ background: elevated ? M.cardElev : M.card, border: `1px solid ${M.line}`, borderRadius: 16, overflow: 'hidden', boxShadow: '0 24px 70px rgba(26,37,64,0.16)' }}>
      <div style={{ padding: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 18 }}>
          <span style={labelStyle}>{label}</span>
          {meta ? <span style={{ ...labelStyle, letterSpacing: '0.08em' }}>{meta}</span> : null}
        </div>
        {children}
      </div>
    </section>
  );
}
function Chip({ text, color = M.accentBright }: { text: string; color?: string }) {
  return <span style={{ display: 'inline-block', fontFamily: M.mono, fontSize: 10.5, letterSpacing: '0.05em', textTransform: 'uppercase', fontWeight: 600, color, background: `${color}20`, border: `1px solid ${color}55`, borderRadius: 999, padding: '5px 10px' }}>{text}</span>;
}
function Kpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 13, padding: 13 }}><div style={labelStyle}>{label}</div><div style={{ fontFamily: M.serif, fontSize: 24, color: M.ink, marginTop: 6, lineHeight: 1 }}>{value}</div><div style={{ color: M.inkFaint, fontSize: 11.5, marginTop: 7 }}>{sub}</div></div>;
}
function bucketColor(kind: string): string {
  if (kind === 'ai') return M.accentBright;
  if (kind === 'grid') return M.pos;
  if (kind === 'defensive') return M.warn;
  if (kind === 'cash') return M.inkFaint;
  return '#9D8CFF';
}

const labelStyle: React.CSSProperties = {
  fontFamily: M.mono,
  fontSize: 10.5,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
  color: M.inkFaint,
  fontWeight: 600,
};

export default function PortfolioMonitorPage() {
  const authFetcher = useAuthFetcher();
  const { data: riskRaw } = useSWR<AnyRecord>(
    authFetcher.isSignedIn ? RISK_ENDPOINT : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const { data: forecastRaw } = useSWR<AnyRecord>(
    authFetcher.isSignedIn ? FORECAST_ENDPOINT : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const risk = useMemo(() => normalizeRisk(riskRaw ?? SAMPLE_RISK), [riskRaw]);
  const alignment = useMemo(() => normalizeForecast(forecastRaw ?? SAMPLE_ALIGNMENT_RAW), [forecastRaw]);
  const aligned = useMemo(() => intersectTags(risk.exposure_tags, alignment.preferred), [risk.exposure_tags, alignment.preferred]);
  const conflicts = useMemo(() => intersectTags(risk.exposure_tags, alignment.avoid), [risk.exposure_tags, alignment.avoid]);

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  return (
    <main style={{ minHeight: '100vh', background: M.canvas, color: M.canvasInk, fontFamily: M.sans }}>
      <div style={{ width: 'min(1280px, calc(100% - 48px))', margin: '0 auto', padding: '34px 0 76px', display: 'flex', flexDirection: 'column', gap: 22 }}>
        <header style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'end', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontFamily: M.mono, fontSize: 12, letterSpacing: '0.2em', color: M.canvasInkFaint, marginBottom: 10 }}>04 / PORTFOLIO MONITOR</div>
            <h1 style={{ fontFamily: M.serif, fontSize: 38, fontWeight: 500, color: M.canvasInk, margin: 0, lineHeight: 1.02 }}>Risk, alignment, and breadth</h1>
          </div>
          <button type="button" onClick={() => alert('TODO: real schema export endpoint')} style={{ border: `1px solid ${M.canvasInkFaint}77`, background: 'transparent', color: M.canvasInkDim, borderRadius: 999, padding: '9px 14px', fontFamily: M.mono, fontSize: 11.5, cursor: 'pointer' }}>Export to Excel</button>
        </header>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 20 }} className="portfolio-grid">
          <Panel label="Portfolio snapshot" meta="YTD vs SPY">
            <h2 style={{ fontFamily: M.serif, fontSize: 26, fontWeight: 500, color: M.ink, margin: 0 }}>{risk.strategy_label}</h2>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, margin: '13px 0 20px' }}>
              <span style={{ fontFamily: M.serif, fontSize: 56, color: risk.ytd_return_pct >= 0 ? M.pos : M.neg, lineHeight: 1 }}>{fmtPct(risk.ytd_return_pct)}</span>
              <span style={{ fontFamily: M.mono, fontSize: 13, color: M.inkFaint }}>SPY {fmtPct(risk.bench_ytd_pct)}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }} className="snapshot-kpis">
              <Kpi label="Net exposure" value={plainPct(risk.net_exposure_pct)} sub={`${plainPct(risk.cash_pct)} cash`} />
              <Kpi label="Portfolio beta" value={risk.portfolio_beta.toFixed(2)} sub="EWMA + Vasicek" />
              <Kpi label="Eff breadth" value={risk.effective_breadth.toFixed(1)} sub="position-adjusted" />
              <Kpi label="Factor tilt" value={`${risk.factor_tilt_sigma.toFixed(1)}σ`} sub="ETF proxy" />
            </div>
          </Panel>

          <Panel label="Where risk lives" elevated>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {risk.risk_decomposition.map((bucket) => (
                <div key={bucket.label}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 7, color: M.inkDim, fontSize: 13 }}>
                    <span>{bucket.label}</span>
                    <span style={{ fontFamily: M.mono }}>{plainPct(bucket.pct)}</span>
                  </div>
                  <div style={{ height: 8, background: M.well, borderRadius: 999, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, bucket.pct))}%`, background: bucketColor(bucket.kind), borderRadius: 999 }} />
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 0.82fr)', gap: 20 }} className="portfolio-grid">
          <Panel label="ETF-proxy factor model · net beta">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
              {risk.factor_exposures.map((factor) => <DivergingBar key={factor.label} label={factor.label} beta={factor.beta} />)}
            </div>
          </Panel>
          <Panel label="Concentration">
            <Donut buckets={risk.risk_decomposition} breadth={risk.effective_breadth} />
          </Panel>
        </div>

        <Panel label="Regime alignment" meta="macro forecast intersection">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }} className="portfolio-grid">
            <AlignmentColumn title="Aligned · preferred" items={aligned.length ? aligned : ['No direct overlap']} color={M.pos} />
            <AlignmentColumn title="Conflicts · avoid" items={conflicts.length ? conflicts : ['No direct conflict']} color={M.neg} />
          </div>
        </Panel>

        <Panel label="Holdings" meta={`${risk.holdings.length} positions`}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
              <thead>
                <tr>
                  {['Position', 'Weight', 'Beta contrib', 'Marginal risk', 'Tag'].map((h) => <th key={h} style={{ ...labelStyle, textAlign: 'left', padding: '0 12px 12px' }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {risk.holdings.map((h) => (
                  <tr key={h.ticker} style={{ borderTop: `1px solid ${M.line}` }}>
                    <td style={tdStyle}><strong style={{ color: M.ink }}>{h.ticker}</strong><div style={{ color: M.inkFaint, fontSize: 12 }}>{h.name}</div></td>
                    <td style={tdStyle}>{plainPct(h.weight_pct, 1)}</td>
                    <td style={tdStyle}>{h.beta_contrib.toFixed(2)}</td>
                    <td style={tdStyle}>{h.marginal_risk_pct === null ? '—' : plainPct(h.marginal_risk_pct, 1)}</td>
                    <td style={tdStyle}><Chip text={h.tag} color={h.aligned ? M.pos : M.warn} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <style>{`
        @media (max-width: 980px) { .portfolio-grid { grid-template-columns: 1fr !important; } .snapshot-kpis { grid-template-columns: repeat(2, 1fr) !important; } }
        @media (max-width: 620px) { .snapshot-kpis { grid-template-columns: 1fr !important; } }
      `}</style>
    </main>
  );
}

const tdStyle: React.CSSProperties = {
  padding: '14px 12px',
  color: M.inkDim,
  fontFamily: M.sans,
  fontSize: 13,
  verticalAlign: 'middle',
};

function intersectTags(tags: string[], macroItems: string[]): string[] {
  const normalized = macroItems.map((item) => item.toLowerCase());
  return tags.filter((tag) => normalized.some((item) => item.includes(tag.toLowerCase()) || tag.toLowerCase().includes(item)));
}
function AlignmentColumn({ title, items, color }: { title: string; items: string[]; color: string }) {
  return <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 14, padding: 16 }}><div style={{ ...labelStyle, color, marginBottom: 12 }}>{title}</div><div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{items.map((item) => <Chip key={item} text={item} color={color} />)}</div></div>;
}
function DivergingBar({ label, beta }: { label: string; beta: number }) {
  const max = 1.2;
  const width = Math.min(50, Math.abs(beta) / max * 50);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: M.inkDim, fontSize: 13, marginBottom: 7 }}><span>{label}</span><span style={{ fontFamily: M.mono }}>{beta.toFixed(2)}</span></div>
      <div style={{ position: 'relative', height: 10, background: M.well, borderRadius: 999, overflow: 'hidden' }}>
        <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: M.line2 }} />
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: beta >= 0 ? '50%' : `${50 - width}%`, width: `${width}%`, background: beta >= 0 ? M.accent : M.neg, borderRadius: 999 }} />
      </div>
    </div>
  );
}
function Donut({ buckets, breadth }: { buckets: PortfolioRisk['risk_decomposition']; breadth: number }) {
  const total = buckets.reduce((sum, b) => sum + Math.max(0, b.pct), 0) || 1;
  let offset = 25;
  const r = 42;
  const circ = 2 * Math.PI * r;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '180px minmax(0, 1fr)', gap: 18, alignItems: 'center' }} className="portfolio-grid">
      <svg viewBox="0 0 120 120" style={{ width: 180, height: 180 }}>
        <circle cx="60" cy="60" r={r} fill="none" stroke={M.well} strokeWidth="16" />
        {buckets.map((b) => {
          const dash = Math.max(0, b.pct) / total * circ;
          const seg = <circle key={b.label} cx="60" cy="60" r={r} fill="none" stroke={bucketColor(b.kind)} strokeWidth="16" strokeDasharray={`${dash} ${circ - dash}`} strokeDashoffset={offset} transform="rotate(-90 60 60)" strokeLinecap="butt" />;
          offset -= dash;
          return seg;
        })}
        <text x="60" y="56" textAnchor="middle" fill={M.ink} fontFamily={M.serif} fontSize="20">{breadth.toFixed(1)}</text>
        <text x="60" y="73" textAnchor="middle" fill={M.inkFaint} fontFamily={M.mono} fontSize="7">EFF BREADTH</text>
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {buckets.map((b) => <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 8, color: M.inkDim, fontSize: 12.5 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: bucketColor(b.kind) }} />{b.label} <span style={{ marginLeft: 'auto', fontFamily: M.mono }}>{plainPct(b.pct)}</span></div>)}
      </div>
    </div>
  );
}

const SAMPLE_ALIGNMENT = {
  preferred: ['Grid and power infrastructure', 'Quality AI leaders', 'Quality ex-AI cash flow', 'Cash and carry'],
  avoid: ['Small caps', 'High-beta AI semiconductors', 'Long-duration growth', 'Duration sensitivity'],
};
const SAMPLE_ALIGNMENT_RAW = {
  forecast_interpretation: {
    preferred_exposures: SAMPLE_ALIGNMENT.preferred,
    exposures_to_avoid: SAMPLE_ALIGNMENT.avoid,
  },
};
const SAMPLE_RISK: PortfolioRisk = {
  strategy_label: 'Helix core + tactical sleeve',
  ytd_return_pct: 14.8,
  bench_ytd_pct: 11.1,
  net_exposure_pct: 86,
  cash_pct: 14,
  portfolio_beta: 0.92,
  effective_breadth: 7.4,
  factor_tilt_sigma: 1.3,
  risk_decomposition: [
    { label: 'AI / semis', pct: 28, kind: 'ai' },
    { label: 'Grid & power', pct: 24, kind: 'grid' },
    { label: 'Defensives', pct: 14, kind: 'defensive' },
    { label: 'Idiosyncratic', pct: 20, kind: 'idio' },
    { label: 'Residual / cash', pct: 14, kind: 'cash' },
  ],
  factor_exposures: [
    { label: 'Market beta', beta: 0.92 },
    { label: 'Quality', beta: 0.48 },
    { label: 'Momentum', beta: 0.36 },
    { label: 'Value', beta: -0.18 },
    { label: 'Size', beta: -0.42 },
    { label: 'Volatility', beta: -0.24 },
  ],
  holdings: [
    { ticker: 'MSFT', name: 'Microsoft', weight_pct: 13.0, beta_contrib: 0.12, marginal_risk_pct: 11.3, tag: 'Quality AI leaders', aligned: true },
    { ticker: 'MU', name: 'Micron Technology', weight_pct: 8.5, beta_contrib: 0.13, marginal_risk_pct: 14.7, tag: 'High-beta AI semiconductors', aligned: false },
    { ticker: 'VST', name: 'Vistra', weight_pct: 7.2, beta_contrib: 0.06, marginal_risk_pct: 9.6, tag: 'Grid and power infrastructure', aligned: true },
    { ticker: 'ETN', name: 'Eaton', weight_pct: 6.9, beta_contrib: 0.07, marginal_risk_pct: 8.1, tag: 'Grid and power infrastructure', aligned: true },
    { ticker: 'JNJ', name: 'Johnson & Johnson', weight_pct: 5.8, beta_contrib: 0.03, marginal_risk_pct: 4.2, tag: 'Defensive quality', aligned: true },
    { ticker: 'BIL', name: 'Treasury bills', weight_pct: 14.0, beta_contrib: 0.00, marginal_risk_pct: null, tag: 'Cash and carry', aligned: true },
  ],
  exposure_tags: ['Quality AI leaders', 'High-beta AI semiconductors', 'Grid and power infrastructure', 'Defensive quality', 'Cash and carry'],
};
