'use client';

import { useMemo } from 'react';
import useSWR from 'swr';
import AuthRequired from '@/components/AuthRequired';
import { useAuthFetcher } from '../../lib/api';
import { M } from '../lib/researchOsTheme';

const RISK_ENDPOINT = '/api/portfolio/risk/latest';
const RISK_EXPORT_ENDPOINT = '/api/portfolio/risk/latest.xlsx';
const FORECAST_ENDPOINT = '/api/macro/forecast/latest';

type AnyRecord = Record<string, unknown>;
type PortfolioRisk = {
  generated_at?: string;
  total_account_value?: number | null;
  invested_value?: number | null; cash_value?: number | null;
  invested_fraction?: number | null; cash_fraction?: number | null;
  factor_exposures?: { factor: string; beta: number | null }[];
  effective_breadth?: number | null; effective_annual_breadth?: number | null;
  avg_pairwise_corr?: number | null; concentration_ratio?: number | null; top_principal_component?: number | null;
  risk_decomposition?: {
    total_vol?: number | null; factor_share?: number | null; specific_share?: number | null;
    factors?: { factor: string; exposure?: number | null; pct_of_total_var?: number | null }[];
  };
  stress?: {
    stressed_total_vol?: number | null; sleeve_drawdown?: number | null; whole_book_drawdown?: number | null;
    contributions?: { factor: string; contribution?: number | null }[];
  };
  positions?: { ticker: string; weight?: number | null; value?: number | null; is_cash?: boolean }[];
  per_name_loadings?: { ticker: string; loadings: Record<string, number | null>; r2?: number | null }[];
};
type ForecastAlignment = { preferred: string[]; avoid: string[] };

function safeObj(v: unknown): AnyRecord { return v && typeof v === 'object' ? v as AnyRecord : {}; }
function safeArray<T>(v: unknown): T[] { return Array.isArray(v) ? v as T[] : []; }
function safeNum(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function unwrapPayload(raw: unknown): AnyRecord {
  const obj = safeObj(raw);
  if (obj.output) return safeObj(obj.output);
  if (obj.result) return safeObj(obj.result);
  const cached = safeObj(obj.last_cached_result);
  if (cached.output) return safeObj(cached.output);
  if (cached.result) return safeObj(cached.result);
  return obj;
}
function money(v?: number | null): string {
  return typeof v === 'number' ? v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }) : '—';
}
function pct(v?: number | null, digits = 1, signed = false): string {
  if (typeof v !== 'number') return '—';
  const value = v * 100;
  return `${signed && value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}
function num(v?: number | null, digits = 2): string {
  return typeof v === 'number' ? v.toFixed(digits) : '—';
}

function normalizeRisk(raw: unknown): PortfolioRisk {
  const r = unwrapPayload(raw) as PortfolioRisk;
  const sample = SAMPLE_RISK;
  return {
    generated_at: typeof r.generated_at === 'string' ? r.generated_at : sample.generated_at,
    total_account_value: safeNum(r.total_account_value) ?? sample.total_account_value,
    invested_value: safeNum(r.invested_value) ?? sample.invested_value,
    cash_value: safeNum(r.cash_value) ?? sample.cash_value,
    invested_fraction: safeNum(r.invested_fraction) ?? sample.invested_fraction,
    cash_fraction: safeNum(r.cash_fraction) ?? sample.cash_fraction,
    factor_exposures: safeArray<NonNullable<PortfolioRisk['factor_exposures']>[number]>(r.factor_exposures).length ? r.factor_exposures : sample.factor_exposures,
    effective_breadth: safeNum(r.effective_breadth) ?? sample.effective_breadth,
    effective_annual_breadth: safeNum(r.effective_annual_breadth) ?? sample.effective_annual_breadth,
    avg_pairwise_corr: safeNum(r.avg_pairwise_corr) ?? sample.avg_pairwise_corr,
    concentration_ratio: safeNum(r.concentration_ratio) ?? sample.concentration_ratio,
    top_principal_component: safeNum(r.top_principal_component) ?? sample.top_principal_component,
    risk_decomposition: safeObj(r.risk_decomposition).factors ? r.risk_decomposition : sample.risk_decomposition,
    stress: safeObj(r.stress).contributions ? r.stress : sample.stress,
    positions: safeArray<NonNullable<PortfolioRisk['positions']>[number]>(r.positions).length ? r.positions : sample.positions,
    per_name_loadings: safeArray<NonNullable<PortfolioRisk['per_name_loadings']>[number]>(r.per_name_loadings).length ? r.per_name_loadings : sample.per_name_loadings,
  };
}

function normalizeForecast(raw: unknown): ForecastAlignment {
  const r = unwrapPayload(raw);
  const fi = safeObj(r.forecast_interpretation);
  return {
    preferred: safeArray<string>(fi.preferred_exposures).length ? safeArray<string>(fi.preferred_exposures) : SAMPLE_ALIGNMENT.preferred,
    avoid: safeArray<string>(fi.exposures_to_avoid).length ? safeArray<string>(fi.exposures_to_avoid) : SAMPLE_ALIGNMENT.avoid,
  };
}

const labelStyle: React.CSSProperties = {
  fontFamily: M.mono,
  fontSize: 10.5,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
  color: M.inkFaint,
  fontWeight: 600,
};

function Panel({ label, meta, children, elevated }: { label: string; meta?: string; children: React.ReactNode; elevated?: boolean }) {
  return (
    <section style={{ background: elevated ? M.cardElev : M.card, border: `1px solid ${M.line}`, borderRadius: 16, overflow: 'hidden', boxShadow: M.shadow }}>
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
function factorColor(factor: string, beta?: number | null): string {
  if (factor === 'AI') return beta !== undefined && beta !== null && beta < 0 ? M.neg : M.accentBright;
  if (factor === 'MKT') return M.accentBright;
  if (factor === 'QUAL' || factor === 'VAL') return M.pos;
  if (factor === 'LOWVOL') return M.warn;
  return '#9D8CFF';
}

export default function PortfolioMonitorPage() {
  const authFetcher = useAuthFetcher();
  const { data: riskRaw } = useSWR<unknown>(
    authFetcher.isSignedIn ? RISK_ENDPOINT : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const { data: forecastRaw } = useSWR<unknown>(
    authFetcher.isSignedIn ? FORECAST_ENDPOINT : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const risk = useMemo(() => normalizeRisk(riskRaw ?? SAMPLE_RISK), [riskRaw]);
  const alignment = useMemo(() => normalizeForecast(forecastRaw ?? SAMPLE_ALIGNMENT_RAW), [forecastRaw]);
  const factorMap = useMemo(() => Object.fromEntries((risk.factor_exposures ?? []).map((f) => [f.factor, f.beta])), [risk.factor_exposures]);
  const loadingsMap = useMemo(() => Object.fromEntries((risk.per_name_loadings ?? []).map((row) => [row.ticker, row])), [risk.per_name_loadings]);
  const largestTilt = useMemo(() => largestNonMarketTilt(risk.factor_exposures ?? []), [risk.factor_exposures]);
  const alignmentBuckets = useMemo(() => deriveRegimeAlignment(risk, alignment), [risk, alignment]);

  async function handleExport() {
    const res = await authFetcher.stream(RISK_EXPORT_ENDPOINT);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'risk_report.xlsx';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  const riskFactors = risk.risk_decomposition?.factors ?? [];
  const positions = risk.positions ?? [];
  const visiblePositions = positions;

  return (
    <main style={{ minHeight: '100vh', background: M.canvas, color: M.canvasInk, fontFamily: M.sans }}>
      <div style={{ width: 'min(1440px, calc(100% - 48px))', margin: '0 auto', padding: '34px 0 76px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <header style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'end', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontFamily: M.mono, fontSize: 12, letterSpacing: '0.22em', color: M.canvasInkFaint, marginBottom: 10 }}>PORTFOLIO MONITOR &gt; RISK STACK</div>
            <h1 style={{ fontFamily: M.serif, fontSize: 42, fontWeight: 500, color: M.canvasInk, margin: 0, lineHeight: 1.02 }}>Risk, alignment, and breadth</h1>
          </div>
          <button type="button" onClick={handleExport} style={{ border: `1px solid ${M.canvasInkFaint}77`, background: 'transparent', color: M.canvasInkDim, borderRadius: 999, padding: '9px 14px', fontFamily: M.mono, fontSize: 11.5, cursor: 'pointer' }}>Export to Excel</button>
        </header>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 20 }} className="portfolio-grid">
          <Panel label="Portfolio snapshot" meta={risk.generated_at || 'latest'}>
            <h2 style={{ fontFamily: M.serif, fontSize: 26, fontWeight: 500, color: M.ink, margin: 0 }}>Total account value</h2>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, margin: '13px 0 20px' }}>
              <span style={{ fontFamily: M.serif, fontSize: 56, color: M.ink, lineHeight: 1 }}>{money(risk.total_account_value)}</span>
              <span style={{ fontFamily: M.mono, fontSize: 13, color: M.inkFaint }}>{money(risk.invested_value)} invested · {money(risk.cash_value)} cash</span>
              {/* TODO: returns source. Workbook does not include YTD returns. */}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }} className="snapshot-kpis">
              <Kpi label="Net exposure" value={pct(risk.invested_fraction, 1)} sub={`${pct(risk.cash_fraction, 1)} cash`} />
              <Kpi label="Portfolio beta" value={num(factorMap.MKT, 2)} sub="MKT exposure" />
              <Kpi label="Eff breadth" value={num(risk.effective_breadth, 1)} sub={`${num(risk.effective_annual_breadth, 1)} annual`} />
              <Kpi label="Factor tilt" value={`${largestTilt.factor} ${num(largestTilt.beta, 2)}`} sub="largest non-MKT" />
            </div>
          </Panel>

          <Panel label="Where risk lives" meta={`${pct(risk.risk_decomposition?.factor_share, 0)} factor / ${pct(risk.risk_decomposition?.specific_share, 0)} specific`} elevated>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {riskFactors.map((bucket) => (
                <div key={bucket.factor}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 7, color: M.inkDim, fontSize: 13 }}>
                    <span>{bucket.factor}</span>
                    <span style={{ fontFamily: M.mono }}>{pct(bucket.pct_of_total_var, 1)}</span>
                  </div>
                  <div style={{ height: 8, background: M.well, borderRadius: 999, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${Math.max(0, Math.min(100, (bucket.pct_of_total_var ?? 0) * 100))}%`, background: factorColor(bucket.factor, bucket.exposure), borderRadius: 999 }} />
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 0.82fr)', gap: 20 }} className="portfolio-grid">
          <Panel label="ETF-proxy factor model · net beta">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 13 }}>
              {(risk.factor_exposures ?? []).map((factor) => <DivergingBar key={factor.factor} label={factor.factor} beta={factor.beta} />)}
            </div>
          </Panel>
          <Panel label="Concentration">
            <Concentration positions={positions} breadth={risk.effective_breadth} concentration={risk.concentration_ratio} avgCorr={risk.avg_pairwise_corr} />
          </Panel>
        </div>

        <Panel label="Stress test" meta="MKT -10% shock">
          <div style={{ display: 'grid', gridTemplateColumns: '0.7fr 1.3fr', gap: 18 }} className="portfolio-grid">
            <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 14, padding: 16 }}>
              <div style={labelStyle}>Stressed total vol</div>
              <div style={{ fontFamily: M.serif, fontSize: 42, color: M.ink, marginTop: 8 }}>{pct(risk.stress?.stressed_total_vol, 1)}</div>
              <div style={{ color: M.inkFaint, marginTop: 10, fontSize: 13 }}>Sleeve drawdown {pct(risk.stress?.sleeve_drawdown, 1, true)} · whole book {pct(risk.stress?.whole_book_drawdown, 1, true)}</div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {(risk.stress?.contributions ?? []).map((row) => <StressBar key={row.factor} factor={row.factor} value={row.contribution} />)}
            </div>
          </div>
        </Panel>

        <Panel label="Regime alignment" meta="macro forecast intersection">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }} className="portfolio-grid">
            <AlignmentColumn title="Aligned · preferred" items={alignmentBuckets.aligned.length ? alignmentBuckets.aligned : ['No direct overlap']} color={M.pos} />
            <AlignmentColumn title="Conflicts · avoid" items={alignmentBuckets.conflicts.length ? alignmentBuckets.conflicts : ['No direct conflict']} color={M.neg} />
          </div>
        </Panel>

        <Panel label="Holdings" meta={`${visiblePositions.length} rows`}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
              <thead>
                <tr>
                  {['Position', 'Weight', 'Value', 'Beta', 'Tag'].map((h) => <th key={h} style={{ ...labelStyle, textAlign: 'left', padding: '0 12px 12px' }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {visiblePositions.map((h) => {
                  const loading = loadingsMap[h.ticker];
                  const mkt = h.is_cash ? 0 : safeNum(loading?.loadings?.MKT);
                  const tag = positionTag(h, loading);
                  return (
                    <tr key={h.ticker} style={{ borderTop: `1px solid ${M.line}` }}>
                      <td style={tdStyle}><strong style={{ color: M.ink }}>{h.ticker}</strong>{h.is_cash ? <div style={{ color: M.inkFaint, fontSize: 12 }}>Cash / core</div> : null}</td>
                      <td style={tdStyle}>{pct(h.weight, 1)}</td>
                      <td style={tdStyle}>{money(h.value)}</td>
                      <td style={tdStyle}>{num(mkt, 2)}</td>
                      <td style={tdStyle}><Chip text={tag} color={h.is_cash ? M.inkFaint : factorColor(tag)} /></td>
                    </tr>
                  );
                })}
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

function largestNonMarketTilt(factors: { factor: string; beta: number | null }[]) {
  // TODO: formalize factor-tilt selection once the risk model exposes named tilt diagnostics.
  return factors.filter((f) => f.factor !== 'MKT').reduce(
    (best, factor) => Math.abs(factor.beta ?? 0) > Math.abs(best.beta ?? 0) ? factor : best,
    { factor: '—', beta: null as number | null },
  );
}
function fuzzyIncludes(items: string[], tag: string): boolean {
  const needle = tag.toLowerCase();
  return items.some((item) => {
    const hay = item.toLowerCase();
    return hay.includes(needle) || needle.includes(hay);
  });
}
function deriveRegimeAlignment(risk: PortfolioRisk, macro: ForecastAlignment) {
  // TODO: formalize macro-to-factor exposure mapping; this is a transparent heuristic.
  const factors = Object.fromEntries((risk.factor_exposures ?? []).map((f) => [f.factor, f.beta ?? 0]));
  const candidates = [
    { tag: 'Quality', side: (factors.QUAL ?? 0) > 0 ? 'long' : 'short' },
    { tag: 'Value', side: (factors.VAL ?? 0) > 0 ? 'long' : 'short' },
    { tag: 'Cash and carry', side: (risk.cash_fraction ?? 0) > 0.05 ? 'long' : 'flat' },
    { tag: 'High-beta AI semiconductors', side: (factors.AI ?? 0) < 0 ? 'underweight' : 'long' },
  ];
  const aligned: string[] = [];
  const conflicts: string[] = [];
  for (const item of candidates) {
    if (item.side === 'long' && fuzzyIncludes(macro.preferred, item.tag)) aligned.push(item.tag);
    if (item.side === 'underweight' && fuzzyIncludes(macro.avoid, item.tag)) aligned.push(`Underweight ${item.tag}`);
    if (item.side === 'long' && fuzzyIncludes(macro.avoid, item.tag)) conflicts.push(item.tag);
    if (item.side === 'underweight' && fuzzyIncludes(macro.preferred, item.tag)) conflicts.push(`Underweight ${item.tag}`);
  }
  return { aligned, conflicts };
}
function AlignmentColumn({ title, items, color }: { title: string; items: string[]; color: string }) {
  return <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 14, padding: 16 }}><div style={{ ...labelStyle, color, marginBottom: 12 }}>{title}</div><div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{items.map((item) => <Chip key={item} text={item} color={color} />)}</div></div>;
}
function DivergingBar({ label, beta }: { label: string; beta?: number | null }) {
  const value = beta ?? 0;
  const max = 1.2;
  const width = Math.min(50, Math.abs(value) / max * 50);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: M.inkDim, fontSize: 13, marginBottom: 7 }}><span>{label}</span><span style={{ fontFamily: M.mono }}>{beta === null || beta === undefined ? '—' : value.toFixed(2)}</span></div>
      <div style={{ position: 'relative', height: 10, background: M.well, borderRadius: 999, overflow: 'hidden' }}>
        <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: M.line2 }} />
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: value >= 0 ? '50%' : `${50 - width}%`, width: `${width}%`, background: value >= 0 ? M.accent : M.neg, borderRadius: 999 }} />
      </div>
    </div>
  );
}
function StressBar({ factor, value }: { factor: string; value?: number | null }) {
  const v = value ?? 0;
  const width = Math.min(100, Math.abs(v) / 0.1 * 100);
  return <div><div style={{ display: 'flex', justifyContent: 'space-between', color: M.inkDim, fontSize: 13, marginBottom: 7 }}><span>{factor}</span><span style={{ fontFamily: M.mono, color: v < 0 ? M.neg : M.pos }}>{pct(v, 1, true)}</span></div><div style={{ height: 8, background: M.well, borderRadius: 999, overflow: 'hidden' }}><div style={{ height: '100%', width: `${width}%`, background: v < 0 ? M.neg : M.pos, borderRadius: 999 }} /></div></div>;
}
function Concentration({ positions, breadth, concentration, avgCorr }: { positions: PortfolioRisk['positions']; breadth?: number | null; concentration?: number | null; avgCorr?: number | null }) {
  const top = [...(positions ?? [])].filter((p) => !p.is_cash).sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).slice(0, 6);
  const total = top.reduce((sum, p) => sum + Math.max(0, p.weight ?? 0), 0) || 1;
  let offset = 25;
  const r = 42;
  const circ = 2 * Math.PI * r;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '180px minmax(0, 1fr)', gap: 18, alignItems: 'center' }} className="portfolio-grid">
      <svg viewBox="0 0 120 120" style={{ width: 180, height: 180 }}>
        <circle cx="60" cy="60" r={r} fill="none" stroke={M.well} strokeWidth="16" />
        {top.map((p, idx) => {
          const dash = Math.max(0, p.weight ?? 0) / total * circ;
          const color = [M.accentBright, M.pos, M.warn, '#9D8CFF', M.neg, M.inkFaint][idx % 6];
          const seg = <circle key={p.ticker} cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="16" strokeDasharray={`${dash} ${circ - dash}`} strokeDashoffset={offset} transform="rotate(-90 60 60)" strokeLinecap="butt" />;
          offset -= dash;
          return seg;
        })}
        <text x="60" y="56" textAnchor="middle" fill={M.ink} fontFamily={M.serif} fontSize="20">{num(breadth, 1)}</text>
        <text x="60" y="73" textAnchor="middle" fill={M.inkFaint} fontFamily={M.mono} fontSize="7">EFF BREADTH</text>
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
        {top.map((p) => <div key={p.ticker} style={{ display: 'flex', alignItems: 'center', gap: 8, color: M.inkDim, fontSize: 12.5 }}><span style={{ width: 10, height: 10, borderRadius: 3, background: M.accentBright }} />{p.ticker} <span style={{ marginLeft: 'auto', fontFamily: M.mono }}>{pct(p.weight, 1)}</span></div>)}
        <div style={{ color: M.inkFaint, fontSize: 12, marginTop: 6 }}>Concentration {pct(concentration, 1)} · avg corr {pct(avgCorr, 1)}</div>
      </div>
    </div>
  );
}
function positionTag(position: { ticker: string; is_cash?: boolean }, loading?: { loadings: Record<string, number | null> }) {
  if (position.is_cash) return 'Cash';
  // TODO: replace with formal holding taxonomy when risk stack emits position tags.
  const entries = Object.entries(loading?.loadings ?? {}).filter(([factor]) => factor !== 'MKT');
  if (!entries.length) return 'Position';
  const [factor] = entries.reduce((best, entry) => Math.abs(entry[1] ?? 0) > Math.abs(best[1] ?? 0) ? entry : best, entries[0]);
  return factor;
}

const SAMPLE_ALIGNMENT = {
  preferred: ['Quality ex-AI cash flow', 'Cash and carry', 'Value cyclicals'],
  avoid: ['High-beta AI semiconductors', 'Long-duration growth'],
};
const SAMPLE_ALIGNMENT_RAW = {
  forecast_interpretation: {
    preferred_exposures: SAMPLE_ALIGNMENT.preferred,
    exposures_to_avoid: SAMPLE_ALIGNMENT.avoid,
  },
};
const SAMPLE_RISK: PortfolioRisk = {
  generated_at: '2026-07-20 21:00',
  total_account_value: 19432.66,
  invested_value: 17384.44,
  cash_value: 2048.22,
  invested_fraction: 0.8945990924556906,
  cash_fraction: 0.1054009075443094,
  factor_exposures: [
    { factor: 'MKT', beta: 0.837113063331445 },
    { factor: 'AI', beta: -0.2204190859986061 },
    { factor: 'MOM', beta: -0.1890699612784261 },
    { factor: 'QUAL', beta: 0.248791976111307 },
    { factor: 'VAL', beta: 0.287408998771072 },
    { factor: 'SIZE', beta: 0.09711689428123711 },
    { factor: 'LOWVOL', beta: 0.09201351328472893 },
  ],
  effective_breadth: 7.045536643350729,
  effective_annual_breadth: 28.18214657340292,
  avg_pairwise_corr: 0.3573038750719487,
  concentration_ratio: 0.503252617382195,
  top_principal_component: 0.4457806535491069,
  risk_decomposition: {
    total_vol: 0.1260614548889882,
    factor_share: 0.8020087092719821,
    specific_share: 0.1979912907280178,
    factors: [
      { factor: 'MKT', exposure: 0.837113063331445, pct_of_total_var: 0.6550125710452499 },
      { factor: 'AI', exposure: -0.2204190859986061, pct_of_total_var: 0.07960582743476954 },
      { factor: 'VAL', exposure: 0.287408998771072, pct_of_total_var: 0.02355699124896584 },
      { factor: 'QUAL', exposure: 0.248791976111307, pct_of_total_var: 0.01740840791354002 },
      { factor: 'SIZE', exposure: 0.09711689428123711, pct_of_total_var: 0.01704830745553063 },
      { factor: 'MOM', exposure: -0.1890699612784261, pct_of_total_var: 0.009999914042833138 },
      { factor: 'LOWVOL', exposure: 0.09201351328472893, pct_of_total_var: -0.0006233098689068536 },
    ],
  },
  stress: {
    stressed_total_vol: 0.1760708049357599,
    sleeve_drawdown: -0.07083896837714121,
    whole_book_drawdown: -0.06337247682068789,
    contributions: [
      { factor: 'MKT', contribution: -0.0837113063331445 },
      { factor: 'AI', contribution: 0.01752667524098619 },
      { factor: 'MOM', contribution: 0.007512634516455804 },
      { factor: 'VAL', contribution: -0.006796383072303415 },
      { factor: 'SIZE', contribution: -0.00424095684293527 },
      { factor: 'QUAL', contribution: -0.002754796471921789 },
      { factor: 'LOWVOL', contribution: 0.001625164585721769 },
    ],
  },
  positions: [
    { ticker: 'PYPL', weight: 0.0750370767563473, value: 1458.17, is_cash: false },
    { ticker: 'MRK', weight: 0.07206270268712568, value: 1400.37, is_cash: false },
    { ticker: 'QQQ', weight: 0.07163815967551533, value: 1392.12, is_cash: false },
    { ticker: 'JPM', weight: 0.06975267410637555, value: 1355.48, is_cash: false },
    { ticker: 'RSP', weight: 0.06558649201910596, value: 1274.52, is_cash: false },
    { ticker: 'CASH', weight: 0.1054009075443094, value: 2048.22, is_cash: true },
  ],
  per_name_loadings: [
    { ticker: 'PYPL', loadings: { MKT: 1.48, AI: -0.35, MOM: -1.24, QUAL: 1.05, VAL: -0.39, SIZE: 0.20, LOWVOL: 0.44 }, r2: 0.28 },
    { ticker: 'MRK', loadings: { MKT: 0.25, AI: -0.51, MOM: -0.24, QUAL: 1.29, VAL: 1.31, SIZE: 0.11, LOWVOL: 0.47 }, r2: 0.30 },
    { ticker: 'QQQ', loadings: { MKT: 1.29, AI: 0.30, MOM: 0.01, QUAL: -0.02, VAL: -0.19, SIZE: 0.00, LOWVOL: 0.19 }, r2: 0.98 },
    { ticker: 'JPM', loadings: { MKT: 0.83, AI: -0.38, MOM: 0.40, QUAL: 0.09, VAL: 0.74, SIZE: -0.01, LOWVOL: -0.97 }, r2: 0.41 },
  ],
};
