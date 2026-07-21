'use client';

import { useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';
import AuthRequired from '@/components/AuthRequired';
import { useAuthFetcher } from '../../lib/api';
import { M } from '../lib/researchOsTheme';

const COVERAGE_ENDPOINT = '/api/research/fundamental/coverage';
const REPORT_ENDPOINT = (ticker: string) => `/api/research/fundamental/${ticker}`;

type AnyRecord = Record<string, unknown>;
type FundamentalReport = {
  ticker: string;
  as_of_date?: string;
  horizon?: string;
  verdict?: string;
  data_confidence?: string;
  company_profile?: { company_name?: string; sector?: string; industry?: string };
  scores?: {
    final_underwriting_score?: number;
    business_quality?: number; financial_health?: number; competitive_position?: number;
    earnings_inflection_potential?: number; regime_fit?: number; valuation_setup?: number;
    variant_perception_strength?: number; idiosyncratic_risk?: number;
  };
  financial_trend_analysis?: Record<string, string | string[] | null | undefined>;
  llm_synthesis?: {
    underwriting_summary?: string; business_summary?: string; confidence?: string;
    qualitative_conviction?: string; key_risks?: string[]; key_metrics_to_monitor?: string[];
    bull_case_variant_view?: string; bear_case_variant_view?: string;
  };
  variant_view?: {
    variant_view_direction?: string; variant_view_strength?: string;
    bull_case_variant_view?: string; bear_case_variant_view?: string;
  };
  falsification_framework?: {
    fundamental_falsifiers?: string[]; macro_falsifiers?: string[];
    valuation_falsifiers?: string[]; timing_falsifiers?: string[];
  };
  final_rationale?: string;
  key_monitoring_items?: string[];
};
type CoverageEntry = { ticker: string; name?: string; as_of_date?: string };
type ViewReport = {
  ticker: string;
  name: string;
  sector: string;
  asOf: string;
  score: number | null;
  conviction: string;
  thesis: string;
  horizon: string;
  verdict: string;
  confidence: string;
  kpis: { label: string; value: string; sub: string }[];
  estimateTrend: string;
  factors: { label: string; value: number | null }[];
  monitoring: string[];
  keyRisks: string[];
  falsifiers: string[];
  variantDirection: string;
  variantStrength: string;
  bullVariant: string;
  bearVariant: string;
};

function safeObj(v: unknown): AnyRecord { return v && typeof v === 'object' ? v as AnyRecord : {}; }
function safeArray<T>(v: unknown): T[] { return Array.isArray(v) ? v as T[] : []; }
function safeStr(v: unknown, fallback = '—'): string { return typeof v === 'string' && v.trim() ? v : fallback; }
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
function titleCase(value: string): string {
  return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase());
}
function truncate(value: unknown, max = 42): string {
  const text = Array.isArray(value) ? value.join(', ') : safeStr(value, '—');
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '—';
}
function reportTicker(raw: unknown): string {
  const r = unwrapPayload(raw);
  return safeStr(r.ticker, '').toUpperCase();
}

function normalizeCoverage(raw: unknown): CoverageEntry[] {
  const obj = unwrapPayload(raw);
  const rows = safeArray<CoverageEntry>(obj.coverage).length
    ? safeArray<CoverageEntry>(obj.coverage)
    : safeArray<CoverageEntry>(raw);
  return rows
    .filter((row) => row?.ticker)
    .map((row) => ({
      ticker: String(row.ticker).toUpperCase(),
      name: row.name || row.ticker,
      as_of_date: row.as_of_date,
    }));
}

function normalizeReport(raw: unknown, ticker: string): ViewReport {
  const r = unwrapPayload(raw) as FundamentalReport;
  const profile = r.company_profile ?? {};
  const scores = r.scores ?? {};
  const trends = r.financial_trend_analysis ?? {};
  const llm = r.llm_synthesis ?? {};
  const variant = r.variant_view ?? {};
  const falsification = r.falsification_framework ?? {};
  const sector = [profile.sector, profile.industry].filter(Boolean).join(' / ') || '—';
  const verdict = safeStr(r.verdict ?? llm.qualitative_conviction, '—');
  const scoreFactors = [
    ['Business quality', scores.business_quality],
    ['Financial health', scores.financial_health],
    ['Competitive position', scores.competitive_position],
    ['Earnings inflection', scores.earnings_inflection_potential],
    ['Regime fit', scores.regime_fit],
    ['Valuation setup', scores.valuation_setup],
    ['Variant perception', scores.variant_perception_strength],
    ['Idiosyncratic risk', scores.idiosyncratic_risk],
  ].map(([label, value]) => ({ label: String(label), value: safeNum(value) }));
  const falsifiers = [
    ...safeArray<string>(falsification.fundamental_falsifiers),
    ...safeArray<string>(falsification.macro_falsifiers),
    ...safeArray<string>(falsification.valuation_falsifiers),
    ...safeArray<string>(falsification.timing_falsifiers),
  ];
  return {
    ticker: safeStr(r.ticker, ticker).toUpperCase(),
    name: safeStr(profile.company_name, ticker.toUpperCase()),
    sector,
    asOf: safeStr(r.as_of_date, '—'),
    score: safeNum(scores.final_underwriting_score),
    conviction: titleCase(verdict),
    thesis: firstText(llm.underwriting_summary, r.final_rationale, llm.business_summary),
    horizon: safeStr(r.horizon, '—'),
    verdict: titleCase(verdict),
    confidence: safeStr(r.data_confidence ?? llm.confidence, '—'),
    kpis: [
      { label: 'Revenue growth', value: truncate(trends.revenue_growth_trend), sub: 'qualitative trend' },
      { label: 'Gross margin', value: truncate(trends.gross_margin_trend), sub: 'qualitative trend' },
      { label: 'Operating margin', value: truncate(trends.operating_margin_trend), sub: 'qualitative trend' },
      { label: 'Free cash flow', value: truncate(trends.fcf_trend), sub: 'qualitative trend' },
    ],
    estimateTrend: truncate(trends.estimate_revision_trend, 260),
    factors: scoreFactors,
    monitoring: [
      ...safeArray<string>(llm.key_metrics_to_monitor),
      ...safeArray<string>(r.key_monitoring_items),
    ].slice(0, 6),
    keyRisks: safeArray<string>(llm.key_risks).slice(0, 4),
    falsifiers: falsifiers.slice(0, 4),
    variantDirection: titleCase(safeStr(variant.variant_view_direction ?? safeObj(llm).variant_view_direction, '—')),
    variantStrength: titleCase(safeStr(variant.variant_view_strength ?? safeObj(llm).variant_view_strength, '—')),
    bullVariant: firstText(variant.bull_case_variant_view, llm.bull_case_variant_view),
    bearVariant: firstText(variant.bear_case_variant_view, llm.bear_case_variant_view),
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
function Meter({ value, color = M.accent }: { value: number | null; color?: string }) {
  const width = value === null ? 0 : Math.max(0, Math.min(100, value));
  return <div style={{ height: 7, background: M.well, borderRadius: 999, overflow: 'hidden' }}><div style={{ height: '100%', width: `${width}%`, background: color, borderRadius: 999 }} /></div>;
}

export default function CompanyPage() {
  const authFetcher = useAuthFetcher();
  const { data: coverageRaw } = useSWR<unknown>(
    authFetcher.isReady ? COVERAGE_ENDPOINT : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const coverage = useMemo(() => {
    const live = normalizeCoverage(coverageRaw);
    return live.length ? live : SAMPLE_COVERAGE;
  }, [coverageRaw]);
  const [ticker, setTicker] = useState('GEV');

  useEffect(() => {
    if (!coverage.length) return;
    if (coverage.some((entry) => entry.ticker === ticker)) return;
    setTicker((coverage.find((entry) => entry.ticker === 'GEV') ?? coverage[0]).ticker);
  }, [coverage, ticker]);

  const { data: reportRaw } = useSWR<unknown>(
    authFetcher.isReady && ticker ? REPORT_ENDPOINT(ticker) : null,
    authFetcher.fetcher,
    { onError: () => null, revalidateOnFocus: false },
  );
  const selectedCoverage = useMemo(
    () => coverage.find((entry) => entry.ticker === ticker),
    [coverage, ticker],
  );
  const matchingReportRaw = reportRaw && reportTicker(reportRaw) === ticker ? reportRaw : undefined;
  const fallbackReport = useMemo(
    () => fallbackReportForTicker(ticker, selectedCoverage),
    [ticker, selectedCoverage],
  );
  const report = useMemo(
    () => normalizeReport(matchingReportRaw ?? fallbackReport, ticker),
    [matchingReportRaw, fallbackReport, ticker],
  );

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  return (
    <main style={{ minHeight: '100vh', background: M.canvas, color: M.canvasInk, fontFamily: M.sans }}>
      <div style={{ width: 'min(1280px, calc(100% - 48px))', margin: '0 auto', padding: '34px 0 76px', display: 'flex', flexDirection: 'column', gap: 22 }}>
        <header style={{ display: 'flex', justifyContent: 'space-between', gap: 18, alignItems: 'end', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontFamily: M.mono, fontSize: 12, letterSpacing: '0.2em', color: M.canvasInkFaint, marginBottom: 10 }}>02 / COMPANY RESEARCH</div>
            <h1 style={{ fontFamily: M.serif, fontSize: 38, fontWeight: 500, color: M.canvasInk, margin: 0, lineHeight: 1.02 }}>Single-name conviction</h1>
          </div>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            <span style={{ ...labelStyle, color: M.canvasInkFaint }}>Coverage</span>
            <select value={ticker} onChange={(event) => setTicker(event.target.value)} style={{ minWidth: 300, maxWidth: 'min(460px, 86vw)', background: M.card, border: `1px solid ${M.line}`, borderRadius: 12, color: M.ink, padding: '11px 12px', fontFamily: M.sans, fontSize: 14, outline: 'none' }}>
              {coverage.map((entry) => (
                <option key={entry.ticker} value={entry.ticker}>{entry.ticker} — {entry.name || entry.ticker}</option>
              ))}
            </select>
          </label>
        </header>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.15fr)', gap: 20 }} className="research-grid">
          <Panel label="Scorecard" meta={report.asOf}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
              <div style={{ width: 56, height: 56, borderRadius: 15, background: M.accent, color: '#07142B', display: 'grid', placeItems: 'center', fontFamily: M.serif, fontSize: 28, fontWeight: 600 }}>{report.ticker[0]}</div>
              <div style={{ flex: 1 }}>
                <div style={labelStyle}>{report.sector}</div>
                <h2 style={{ margin: '7px 0 8px', fontFamily: M.serif, fontSize: 28, fontWeight: 500, color: M.ink, lineHeight: 1.05 }}>{report.name}</h2>
                <div style={{ color: M.inkFaint, fontSize: 12.5 }}>
                  {/* TODO: live quote source. Deep fundamental files do not contain price or daily-change fields. */}
                  Live quote not included in report
                </div>
              </div>
            </div>
            <div style={{ marginTop: 22, background: M.well, border: `1px solid ${M.line}`, borderRadius: 15, padding: 18 }}>
              <div style={labelStyle}>Helix research score</div>
              <div style={{ margin: '8px 0 10px', fontFamily: M.serif, color: M.ink, fontSize: 48, lineHeight: 1 }}>{report.score === null ? '—' : report.score.toFixed(1)} <span style={{ fontFamily: M.mono, fontSize: 15, color: M.inkFaint }}>/ 100</span></div>
              <Chip>{report.conviction}</Chip>
            </div>
          </Panel>

          <Panel label="Investment thesis" meta={report.ticker} tone="accent">
            <p style={{ margin: 0, fontFamily: M.serif, fontSize: 21, lineHeight: 1.28, color: M.ink }}>{report.thesis}</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginTop: 22 }}>
              <Meta label="Horizon" value={report.horizon} />
              <Meta label="Verdict" value={report.verdict} />
              <Meta label="Confidence" value={report.confidence} />
            </div>
          </Panel>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', border: `1px solid ${M.line2}`, borderRadius: 16, overflow: 'hidden', background: M.cardElev }} className="kpi-strip">
          {report.kpis.map((kpi) => (
            <div key={kpi.label} style={{ padding: 18, borderRight: `1px solid ${M.line}` }}>
              <div style={labelStyle}>{kpi.label}</div>
              <div style={{ fontFamily: M.serif, fontSize: 23, color: M.ink, marginTop: 8, lineHeight: 1.08 }}>{kpi.value}</div>
              <div style={{ fontFamily: M.sans, fontSize: 12, color: M.inkFaint, marginTop: 8 }}>{kpi.sub}</div>
            </div>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 20 }} className="bottom-grid">
          <Panel label="Estimate momentum">
            <TextCallout>{report.estimateTrend}</TextCallout>
            <p style={{ margin: '12px 0 0', color: M.inkDim, fontSize: 12.5, lineHeight: 1.5 }}>
              {/* TODO: numeric revision series if available in future report schema. */}
              Text-only estimate trend from the fundamental report.
            </p>
          </Panel>
          <Panel label="Conviction by factor">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {report.factors.map((factor) => <FactorRow key={factor.label} label={factor.label} value={factor.value} />)}
            </div>
          </Panel>
          <Panel label="Key metrics to monitor">
            <BulletList items={report.monitoring.length ? report.monitoring : ['—']} />
          </Panel>
          <Panel label="What breaks the thesis?" tone="risk">
            <Chip color={M.neg}>Active falsifier</Chip>
            <BulletList items={(report.falsifiers.length ? report.falsifiers : report.keyRisks).slice(0, 3)} />
          </Panel>
        </div>

        <Panel label="Variant view" meta={`${report.variantDirection} · ${report.variantStrength}`}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }} className="research-grid">
            <VariantBox title="Bull case variant" text={report.bullVariant} color={M.pos} />
            <VariantBox title="Bear case variant" text={report.bearVariant} color={M.neg} />
          </div>
        </Panel>
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
function TextCallout({ children }: { children: React.ReactNode }) {
  return <div style={{ minHeight: 116, background: M.well, border: `1px solid ${M.line}`, borderRadius: 14, padding: 16, color: M.ink, fontFamily: M.serif, fontSize: 20, lineHeight: 1.25 }}>{children}</div>;
}
function FactorRow({ label, value }: { label: string; value: number | null }) {
  return <div><div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, color: M.inkDim, fontSize: 12 }}><span>{label}</span><span style={{ fontFamily: M.mono }}>{value === null ? '—' : value.toFixed(0)}</span></div><Meter value={value} color={(value ?? 0) >= 70 ? M.accentBright : M.warn} /></div>;
}
function BulletList({ items }: { items: string[] }) {
  return <ul style={{ margin: 0, paddingLeft: 18, color: M.inkDim, lineHeight: 1.5, fontSize: 13 }}>{items.map((item, idx) => <li key={`${item}-${idx}`} style={{ marginBottom: 8 }}>{item}</li>)}</ul>;
}
function VariantBox({ title, text, color }: { title: string; text: string; color: string }) {
  return <div style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 14, padding: 16 }}><div style={{ ...labelStyle, color, marginBottom: 10 }}>{title}</div><p style={{ margin: 0, color: M.inkDim, lineHeight: 1.5, fontSize: 13.5 }}>{text}</p></div>;
}

const SAMPLE_COVERAGE: CoverageEntry[] = [
  { ticker: 'AAPL', name: 'Apple Inc.', as_of_date: '2026-06-30' },
  { ticker: 'ETN', name: 'Eaton', as_of_date: '2026-06-30' },
  { ticker: 'GE', name: 'GE Aerospace', as_of_date: '2026-07-01' },
  { ticker: 'GEV', name: 'GE Vernova Inc.', as_of_date: '2026-07-01' },
  { ticker: 'JPM', name: 'JPMorgan Chase & Co.', as_of_date: '2026-06-30' },
  { ticker: 'MU', name: 'Micron Technology', as_of_date: '2026-07-01' },
  { ticker: 'PLTR', name: 'Palantir Technologies Inc.', as_of_date: '2026-07-16' },
  { ticker: 'UAL', name: 'UAL', as_of_date: '2026-06-26' },
  { ticker: 'UNH', name: 'UnitedHealth Group Incorporated', as_of_date: '2026-07-02' },
  { ticker: 'V', name: 'Visa Inc.', as_of_date: '2026-07-02' },
  { ticker: 'XOM', name: 'XOM', as_of_date: '2026-06-27' },
];

// TODO: real schema fallback sample. Live data comes from /api/research/fundamental/{ticker}.
const SAMPLE_REPORT: FundamentalReport = {
  ticker: 'GEV',
  as_of_date: '2026-07-01',
  horizon: '6m',
  verdict: 'watchlist',
  data_confidence: 'high',
  company_profile: { company_name: 'GE Vernova Inc.', sector: 'Industrials', industry: 'Electrical equipment' },
  scores: {
    final_underwriting_score: 77,
    business_quality: 82,
    financial_health: 78,
    competitive_position: 86,
    earnings_inflection_potential: 81,
    regime_fit: 88,
    valuation_setup: 58,
    variant_perception_strength: 85,
    idiosyncratic_risk: 44,
  },
  financial_trend_analysis: {
    revenue_growth_trend: 'improving',
    gross_margin_trend: 'stable',
    operating_margin_trend: 'stable',
    fcf_trend: 'improving',
    estimate_revision_trend: 'Positive but quality-of-earnings adjustments matter; orders and backlog are the confirmation points.',
  },
  llm_synthesis: {
    underwriting_summary: 'GEV has a strong company-level and macro-supported setup, with grid and power infrastructure demand reinforced by orders, backlog, and free-cash-flow improvement.',
    confidence: 'medium',
    qualitative_conviction: 'watchlist',
    key_risks: ['Expectations risk from extreme share-price momentum and premium valuation.'],
    key_metrics_to_monitor: ['Organic orders growth by segment.', 'Total backlog and sequential backlog growth.', 'Gas Power equipment backlog and slot reservations.', 'Free cash flow conversion and working-capital quality.'],
    bull_case_variant_view: 'The market may still underestimate the duration and breadth of the power infrastructure cycle.',
    bear_case_variant_view: 'The stock may already price GEV as a scarce grid and AI-power winner, leaving execution risk asymmetric.',
  },
  variant_view: {
    variant_view_direction: 'two_sided',
    variant_view_strength: 'strong',
  },
  falsification_framework: {
    fundamental_falsifiers: ['Backlog growth slows while margins fail to expand.', 'Free cash flow reverses because working-capital gains were temporary.'],
    valuation_falsifiers: ['Multiple expansion continues while estimate revisions flatten.'],
  },
};

function fallbackReportForTicker(ticker: string, coverage?: CoverageEntry): FundamentalReport {
  if (ticker === SAMPLE_REPORT.ticker) return SAMPLE_REPORT;
  return {
    ticker,
    as_of_date: coverage?.as_of_date,
    verdict: 'loading',
    data_confidence: '—',
    company_profile: {
      company_name: coverage?.name ?? ticker,
      sector: '—',
      industry: undefined,
    },
    scores: {},
    financial_trend_analysis: {
      revenue_growth_trend: 'Awaiting live report',
      gross_margin_trend: 'Awaiting live report',
      operating_margin_trend: 'Awaiting live report',
      fcf_trend: 'Awaiting live report',
      estimate_revision_trend: 'Loading the latest deep fundamental report for the selected company.',
    },
    llm_synthesis: {
      underwriting_summary: 'Loading the latest deep fundamental report for the selected company.',
      confidence: '—',
      qualitative_conviction: 'loading',
      key_risks: [],
      key_metrics_to_monitor: [],
    },
    falsification_framework: {
      fundamental_falsifiers: [],
      macro_falsifiers: [],
      valuation_falsifiers: [],
      timing_falsifiers: [],
    },
    variant_view: {
      variant_view_direction: '—',
      variant_view_strength: '—',
    },
  };
}
