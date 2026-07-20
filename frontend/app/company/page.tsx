'use client';

import { useMemo, useState } from 'react';
import useSWR from 'swr';
import AuthRequired from '@/components/AuthRequired';
import { useAuthFetcher } from '../../lib/api';
import { M } from '../lib/researchOsTheme';

const REPORT_ENDPOINT = (ticker: string) => `/api/research/fundamental/${ticker}`;
// TODO: real schema: replace static coverage with /api/research/fundamental/coverage.
const COVERED_TICKERS = ['MU', 'VST', 'MSFT'];

type AnyRecord = Record<string, unknown>;
type FundamentalReport = {
  ticker: string;
  name: string;
  sector: string;
  price: string;
  daily_change_pct: number;
  helix_score: number;
  conviction: string;
  thesis: string;
  horizon: string;
  benchmark: string;
  confidence: string;
  kpis: { label: string; value: string; sub: string }[];
  eps_revisions: number[];
  factor_conviction: { label: string; value: number }[];
  next_catalyst: { day: string; month: string; title: string; desc: string };
  primary_risk: string;
};

function safeObj(v: unknown): AnyRecord { return v && typeof v === 'object' ? v as AnyRecord : {}; }
function safeArray<T>(v: unknown): T[] { return Array.isArray(v) ? v as T[] : []; }
function safeStr(v: unknown, fallback = ''): string { return typeof v === 'string' ? v : fallback; }
function safeNum(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}
function signedPct(v: number): string { return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`; }
function colorFor(v: number): string { return v >= 0 ? M.pos : M.neg; }

function unwrapPayload(raw: unknown): AnyRecord {
  const obj = safeObj(raw);
  if (obj.output) return safeObj(obj.output);
  if (obj.result) return safeObj(obj.result);
  const cached = safeObj(obj.last_cached_result);
  if (cached.output) return safeObj(cached.output);
  if (cached.result) return safeObj(cached.result);
  return obj;
}

function normalizeReport(raw: unknown, ticker: string): FundamentalReport {
  const r = unwrapPayload(raw);
  const sample = SAMPLE_REPORTS[ticker] ?? SAMPLE_REPORTS.MU;
  // TODO: real schema: map DeepFundamentalReport fields into FundamentalReport.
  return {
    ticker: safeStr(r.ticker, sample.ticker).toUpperCase(),
    name: safeStr(r.name ?? r.company_name, sample.name),
    sector: safeStr(r.sector, sample.sector),
    price: typeof r.price === 'number' ? `$${r.price.toFixed(2)}` : safeStr(r.price, sample.price),
    daily_change_pct: safeNum(r.daily_change_pct ?? r.day_change_pct, sample.daily_change_pct),
    helix_score: safeNum(r.helix_score ?? r.score_0_to_100 ?? r.overall_score, sample.helix_score),
    conviction: safeStr(r.conviction ?? r.rating, sample.conviction),
    thesis: safeStr(r.thesis ?? r.investment_thesis, sample.thesis),
    horizon: safeStr(r.horizon, sample.horizon),
    benchmark: safeStr(r.benchmark ?? r.primary_benchmark, sample.benchmark),
    confidence: safeStr(r.confidence ?? r.confidence_level, sample.confidence),
    kpis: safeArray<FundamentalReport['kpis'][number]>(r.kpis).length ? safeArray<FundamentalReport['kpis'][number]>(r.kpis) : sample.kpis,
    eps_revisions: safeArray<number>(r.eps_revisions).length ? safeArray<number>(r.eps_revisions).map(Number) : sample.eps_revisions,
    factor_conviction: safeArray<FundamentalReport['factor_conviction'][number]>(r.factor_conviction).length ? safeArray<FundamentalReport['factor_conviction'][number]>(r.factor_conviction) : sample.factor_conviction,
    next_catalyst: safeObj(r.next_catalyst).title ? safeObj(r.next_catalyst) as FundamentalReport['next_catalyst'] : sample.next_catalyst,
    primary_risk: safeStr(r.primary_risk ?? r.falsifier, sample.primary_risk),
  };
}

function Panel({ label, meta, children, tone }: { label: string; meta?: string; children: React.ReactNode; tone?: 'accent' | 'risk' }) {
  const bg = tone === 'accent' ? M.accentSoft : tone === 'risk' ? '#3B263C' : M.card;
  const border = tone === 'risk' ? `${M.neg}66` : M.line;
  return (
    <section style={{ background: bg, border: `1px solid ${border}`, borderRadius: 16, overflow: 'hidden', boxShadow: '0 24px 70px rgba(26,37,64,0.16)' }}>
      <div style={{ padding: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 18 }}>
          <span style={labelStyle}>{label}</span>
          {meta ? <span style={{ ...labelStyle, color: M.inkFaint, letterSpacing: '0.08em' }}>{meta}</span> : null}
        </div>
        {children}
      </div>
    </section>
  );
}
function Chip({ children, color = M.accentBright }: { children: React.ReactNode; color?: string }) {
  return <span style={{ fontFamily: M.mono, fontSize: 10.5, letterSpacing: '0.06em', textTransform: 'uppercase', color, background: color === M.accentBright ? M.accentSoft : `${color}22`, border: `1px solid ${color}55`, borderRadius: 999, padding: '5px 10px', fontWeight: 600 }}>{children}</span>;
}
function Meter({ value, color = M.accent }: { value: number; color?: string }) {
  return <div style={{ height: 7, background: M.well, borderRadius: 999, overflow: 'hidden' }}><div style={{ height: '100%', width: `${Math.max(0, Math.min(100, value))}%`, background: color, borderRadius: 999 }} /></div>;
}
function BarChart({ values }: { values: number[] }) {
  const max = Math.max(...values.map((v) => Math.abs(v)), 1);
  return (
    <div style={{ display: 'flex', alignItems: 'end', gap: 8, height: 120, padding: '14px 12px', background: M.well, border: `1px solid ${M.line}`, borderRadius: 14 }}>
      {values.map((v, i) => (
        <div key={i} title={String(v)} style={{ flex: 1, minWidth: 10, height: `${Math.max(8, Math.abs(v) / max * 92)}%`, background: i === values.length - 1 ? M.accentBright : v >= 0 ? `${M.pos}AA` : `${M.neg}AA`, borderRadius: '7px 7px 2px 2px' }} />
      ))}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  fontFamily: M.mono,
  fontSize: 10.5,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
  color: M.inkFaint,
  fontWeight: 600,
};

export default function CompanyPage() {
  const authFetcher = useAuthFetcher();
  const [ticker, setTicker] = useState('MU');
  const { data } = useSWR<AnyRecord>(
    authFetcher.isSignedIn ? REPORT_ENDPOINT(ticker) : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const report = useMemo(() => normalizeReport(data ?? SAMPLE_REPORTS[ticker], ticker), [data, ticker]);

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  return (
    <main style={{ minHeight: '100vh', background: M.canvas, color: M.canvasInk, fontFamily: M.sans }}>
      <div style={{ width: 'min(1280px, calc(100% - 48px))', margin: '0 auto', padding: '34px 0 76px', display: 'flex', flexDirection: 'column', gap: 22 }}>
        <header>
          <div style={{ fontFamily: M.mono, fontSize: 12, letterSpacing: '0.2em', color: M.canvasInkFaint, marginBottom: 10 }}>02 / COMPANY RESEARCH</div>
          <h1 style={{ fontFamily: M.serif, fontSize: 38, fontWeight: 500, color: M.canvasInk, margin: 0, lineHeight: 1.02 }}>Single-name conviction</h1>
        </header>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {COVERED_TICKERS.map((t) => {
            const active = t === ticker;
            return (
              <button key={t} type="button" onClick={() => setTicker(t)} style={{ display: 'flex', alignItems: 'center', gap: 9, border: `1px solid ${active ? M.accent : M.line}`, background: active ? M.cardElev : M.card, color: active ? M.ink : M.inkDim, borderRadius: 999, padding: '8px 13px 8px 8px', cursor: 'pointer', fontFamily: M.mono, fontSize: 12, fontWeight: 600 }}>
                <span style={{ width: 24, height: 24, borderRadius: 7, background: active ? M.accent : M.well, color: active ? '#07142B' : M.inkFaint, display: 'grid', placeItems: 'center' }}>{t.slice(0, 1)}</span>
                {t}
              </button>
            );
          })}
          <button type="button" style={{ border: `1px dashed ${M.canvasInkFaint}`, background: 'transparent', color: M.canvasInkDim, borderRadius: 999, padding: '8px 14px', cursor: 'pointer', fontFamily: M.mono, fontSize: 12, fontWeight: 600 }}>＋ Run report</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.15fr)', gap: 20 }} className="research-grid">
          <Panel label="Scorecard">
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
              <div style={{ width: 56, height: 56, borderRadius: 15, background: M.accent, color: '#07142B', display: 'grid', placeItems: 'center', fontFamily: M.serif, fontSize: 28, fontWeight: 600 }}>{report.ticker[0]}</div>
              <div style={{ flex: 1 }}>
                <div style={labelStyle}>{report.sector}</div>
                <h2 style={{ margin: '7px 0 8px', fontFamily: M.serif, fontSize: 28, fontWeight: 500, color: M.ink, lineHeight: 1.05 }}>{report.name}</h2>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <span style={{ fontFamily: M.mono, fontSize: 22, color: M.ink }}>{report.price}</span>
                  <span style={{ fontFamily: M.mono, fontSize: 13, color: colorFor(report.daily_change_pct) }}>{signedPct(report.daily_change_pct)}</span>
                </div>
              </div>
            </div>
            <div style={{ marginTop: 22, background: M.well, border: `1px solid ${M.line}`, borderRadius: 15, padding: 18 }}>
              <div style={labelStyle}>Helix research score</div>
              <div style={{ margin: '8px 0 10px', fontFamily: M.serif, color: M.ink, fontSize: 48, lineHeight: 1 }}>{report.helix_score.toFixed(1)} <span style={{ fontFamily: M.mono, fontSize: 15, color: M.inkFaint }}>/ 100</span></div>
              <Chip>{report.conviction}</Chip>
            </div>
          </Panel>

          <Panel label="Investment thesis" meta={report.ticker} tone="accent">
            <p style={{ margin: 0, fontFamily: M.serif, fontSize: 21, lineHeight: 1.28, color: M.ink }}>{report.thesis}</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginTop: 22 }}>
              <Meta label="Horizon" value={report.horizon} />
              <Meta label="Benchmark" value={report.benchmark} />
              <Meta label="Confidence" value={report.confidence} />
            </div>
          </Panel>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', border: `1px solid ${M.line2}`, borderRadius: 16, overflow: 'hidden', background: M.cardElev }} className="kpi-strip">
          {report.kpis.slice(0, 4).map((kpi) => (
            <div key={kpi.label} style={{ padding: 18, borderRight: `1px solid ${M.line}` }}>
              <div style={labelStyle}>{kpi.label}</div>
              <div style={{ fontFamily: M.serif, fontSize: 30, color: M.ink, marginTop: 7, lineHeight: 1 }}>{kpi.value}</div>
              <div style={{ fontFamily: M.sans, fontSize: 12, color: M.inkFaint, marginTop: 8 }}>{kpi.sub}</div>
            </div>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 20 }} className="bottom-grid">
          <Panel label="Forward EPS revisions">
            <BarChart values={report.eps_revisions} />
            <p style={{ margin: '12px 0 0', color: M.inkDim, fontSize: 12.5, lineHeight: 1.5 }}>Last bar highlights the latest revision pulse.</p>
          </Panel>
          <Panel label="Conviction by factor">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {report.factor_conviction.map((factor) => <FactorRow key={factor.label} label={factor.label} value={factor.value} />)}
            </div>
          </Panel>
          <Panel label="Next catalyst">
            <div style={{ display: 'flex', gap: 14 }}>
              <div style={{ width: 64, height: 72, borderRadius: 14, background: M.well, border: `1px solid ${M.line}`, display: 'grid', placeItems: 'center' }}>
                <div style={{ textAlign: 'center' }}><div style={{ fontFamily: M.serif, fontSize: 28, color: M.ink }}>{report.next_catalyst.day}</div><div style={{ fontFamily: M.mono, fontSize: 10, color: M.inkFaint }}>{report.next_catalyst.month}</div></div>
              </div>
              <div><h3 style={{ margin: 0, fontFamily: M.serif, fontSize: 20, fontWeight: 500, color: M.ink }}>{report.next_catalyst.title}</h3><p style={{ margin: '8px 0 14px', color: M.inkDim, lineHeight: 1.5, fontSize: 13 }}>{report.next_catalyst.desc}</p><button style={{ border: `1px solid ${M.accent}`, background: M.accentSoft, color: M.accentBright, borderRadius: 10, padding: '8px 11px', fontFamily: M.mono, fontSize: 11, cursor: 'pointer' }}>Add to monitor</button></div>
            </div>
          </Panel>
          <Panel label="What breaks the thesis?" tone="risk">
            <Chip color={M.neg}>⚠ Active falsifier</Chip>
            <p style={{ margin: '14px 0 0', fontFamily: M.serif, fontSize: 20, lineHeight: 1.28, color: M.ink }}>{report.primary_risk}</p>
          </Panel>
        </div>
      </div>
      <style>{`
        @media (max-width: 980px) { .research-grid, .bottom-grid { grid-template-columns: 1fr !important; } .kpi-strip { grid-template-columns: repeat(2, 1fr) !important; } }
        @media (max-width: 620px) { .kpi-strip { grid-template-columns: 1fr !important; } }
      `}</style>
    </main>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, padding: 12 }}><div style={labelStyle}>{label}</div><div style={{ marginTop: 6, color: M.ink, fontSize: 13, fontWeight: 600 }}>{value}</div></div>;
}
function FactorRow({ label, value }: { label: string; value: number }) {
  return <div><div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, color: M.inkDim, fontSize: 12 }}><span>{label}</span><span style={{ fontFamily: M.mono }}>{value}</span></div><Meter value={value} color={value >= 70 ? M.accentBright : M.warn} /></div>;
}

const SAMPLE_REPORTS: Record<string, FundamentalReport> = {
  MU: {
    ticker: 'MU',
    name: 'Micron Technology',
    sector: 'Semiconductors / memory',
    price: '$128.40',
    daily_change_pct: 2.1,
    helix_score: 86.4,
    conviction: 'High conviction',
    thesis: 'Micron is not merely participating in semiconductor strength; HBM supply tightness, improving DRAM pricing, and positive relative strength versus SMH make the setup an earnings-revision compounder.',
    horizon: '6-12m',
    benchmark: 'SMH',
    confidence: 'High',
    kpis: [
      { label: 'Revenue growth', value: '+58%', sub: 'next FY consensus' },
      { label: 'Gross margin', value: '39%', sub: 'cycle recovery' },
      { label: 'FCF margin', value: '12%', sub: 'normalizing capex' },
      { label: '6m relative', value: '+18.4%', sub: 'vs SMH' },
    ],
    eps_revisions: [4, 7, 9, 14, 18, 22, 31, 38],
    factor_conviction: [
      { label: 'Moat', value: 74 },
      { label: 'Fundamentals', value: 88 },
      { label: 'Valuation', value: 69 },
      { label: 'Catalysts', value: 91 },
    ],
    next_catalyst: { day: '25', month: 'SEP', title: 'FY earnings', desc: 'HBM capacity commentary and DRAM pricing guide are the key confirmation points.' },
    primary_risk: 'Memory pricing rolls over before HBM mix can offset commodity DRAM margin pressure.',
  },
  VST: {
    ticker: 'VST',
    name: 'Vistra',
    sector: 'Power generation',
    price: '$192.10',
    daily_change_pct: -0.7,
    helix_score: 82.2,
    conviction: 'High conviction',
    thesis: 'Vistra remains a high-beta power scarcity expression with AI load growth support, but the thesis depends on realized power prices staying ahead of regulatory and fuel-cost risk.',
    horizon: '6m',
    benchmark: 'XLU',
    confidence: 'Medium-high',
    kpis: [
      { label: 'Macro support', value: '8.1/10', sub: 'grid + power theme' },
      { label: 'Scenario wins', value: '4/5', sub: 'stress-tested' },
      { label: 'Narrative', value: 'Strong', sub: 'AI power demand' },
      { label: 'Rank', value: '#2', sub: 'theme basket' },
    ],
    eps_revisions: [8, 10, 12, 16, 20, 25, 29, 33],
    factor_conviction: [
      { label: 'Moat', value: 71 },
      { label: 'Fundamentals', value: 83 },
      { label: 'Valuation', value: 62 },
      { label: 'Catalysts', value: 87 },
    ],
    next_catalyst: { day: '08', month: 'AUG', title: 'Power price update', desc: 'Regional forward curves and data-center load commentary drive the next mark.' },
    primary_risk: 'Political or regulatory pressure caps realized merchant power upside.',
  },
  MSFT: {
    ticker: 'MSFT',
    name: 'Microsoft',
    sector: 'Mega-cap software',
    price: '$514.30',
    daily_change_pct: 0.5,
    helix_score: 79.8,
    conviction: 'Core compounder',
    thesis: 'Microsoft has superior business quality and AI distribution, but incremental attractiveness depends on whether Azure/AI monetization can create alpha versus QQQ rather than benchmark-like participation.',
    horizon: '12m',
    benchmark: 'QQQ',
    confidence: 'Medium',
    kpis: [
      { label: 'Cloud growth', value: '+29%', sub: 'Azure constant currency' },
      { label: 'Op margin', value: '45%', sub: 'durable scale' },
      { label: 'FCF margin', value: '31%', sub: 'capex drag watched' },
      { label: '6m relative', value: '+3.2%', sub: 'vs QQQ' },
    ],
    eps_revisions: [3, 5, 6, 8, 9, 12, 13, 15],
    factor_conviction: [
      { label: 'Moat', value: 96 },
      { label: 'Fundamentals', value: 90 },
      { label: 'Valuation', value: 54 },
      { label: 'Catalysts', value: 72 },
    ],
    next_catalyst: { day: '29', month: 'JUL', title: 'Cloud earnings', desc: 'Azure growth, AI revenue disclosures, and capex pacing are the swing factors.' },
    primary_risk: 'AI capex growth outruns visible monetization and compresses free-cash-flow expectations.',
  },
};
