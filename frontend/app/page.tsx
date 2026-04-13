'use client';

import useSWR from 'swr';
import { fetcher } from '../lib/api';

// ── Design tokens ────────────────────────────────────────────────────────────
const T = {
  bg:        '#07070a',
  bgPanel:   '#07070a',
  border:    'rgba(255,255,255,0.06)',
  borderSub: 'rgba(255,255,255,0.03)',
  sectionBg: 'rgba(255,255,255,0.018)',
  text:      'rgba(255,255,255,0.88)',
  textSub:   'rgba(255,255,255,0.28)',
  textMuted: 'rgba(255,255,255,0.18)',
  label:     'rgba(255,255,255,0.22)',
  up:        '#57a06a',
  dn:        '#b85555',
  wa:        '#9e7e35',
  mid:       'rgba(255,255,255,0.22)',
  accent:    '#9580d4',
  mono:      "'JetBrains Mono', monospace",
  sans:      "'Inter', sans-serif",
};

// ── Shared style objects ─────────────────────────────────────────────────────
const sectionHd: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '8px 24px',
  background: T.sectionBg,
  borderBottom: `0.5px solid ${T.border}`,
};

const sectionLabel: React.CSSProperties = {
  fontFamily: T.sans,
  fontSize: '9px',
  letterSpacing: '1.8px',
  textTransform: 'uppercase',
  color: T.label,
  fontWeight: 500,
};

const sectionMeta: React.CSSProperties = {
  fontFamily: T.mono,
  fontSize: '9px',
  fontWeight: 300,
  color: T.textMuted,
  letterSpacing: '0.5px',
};

const colHd: React.CSSProperties = {
  ...sectionHd,
  padding: '8px 24px',
};

// ── Helpers ──────────────────────────────────────────────────────────────────
function pct(val: number | undefined) {
  if (val === undefined || val === null) return '—';
  return `${val >= 0 ? '+' : ''}${val.toFixed(2)}%`;
}

function fmtSigma(val: number | undefined) {
  if (val === undefined || val === null) return '—';
  return `${val >= 0 ? '+' : ''}${val.toFixed(2)}σ`;
}

function signColor(val: number | undefined) {
  if (val === undefined) return T.mid;
  return val >= 0 ? T.up : T.dn;
}

function barColor(val: number) {
  if (val >= 6) return T.up;
  if (val >= 4) return T.wa;
  return T.dn;
}

// ── Sub-components ───────────────────────────────────────────────────────────

function KpiBlock({ label, children, meta }: { label: string; children: React.ReactNode; meta?: React.ReactNode }) {
  return (
    <div style={{ padding: '16px 24px', borderRight: `0.5px solid ${T.border}` }}>
      <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '10px', fontWeight: 400 }}>
        {label}
      </div>
      {children}
      {meta && (
        <div style={{ fontFamily: T.sans, fontSize: '10px', color: T.textMuted, marginTop: '5px', letterSpacing: '0.2px' }}>
          {meta}
        </div>
      )}
    </div>
  );
}

function KpiValue({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: T.mono, fontSize: '28px', fontWeight: 300, letterSpacing: '-1px', color: T.text, lineHeight: 1 }}>
      {children}
    </div>
  );
}

function MacroBadge({ regime }: { regime: string }) {
  const isDown = regime?.toLowerCase() === 'down';
  const color = isDown ? 'rgba(185,80,80,0.75)' : 'rgba(185,155,55,0.75)';
  const bg    = isDown ? 'rgba(185,80,80,0.05)' : 'rgba(185,155,55,0.05)';
  const bdr   = isDown ? 'rgba(185,80,80,0.2)'  : 'rgba(185,155,55,0.2)';
  return (
    <span style={{
      display: 'inline-block', fontFamily: T.sans, fontSize: '8.5px',
      letterSpacing: '1px', textTransform: 'uppercase', padding: '2px 7px',
      marginBottom: '8px', fontWeight: 500, color, background: bg,
      border: `0.5px solid ${bdr}`,
    }}>
      {regime || '—'}
    </span>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const fill = barColor(value);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 24px', borderBottom: `0.5px solid ${T.borderSub}` }}>
      <span style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.3px', color: T.textSub, width: '130px', flexShrink: 0 }}>
        {label.replace(/_/g, ' ')}
      </span>
      <div style={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.05)' }}>
        <div style={{ width: `${Math.min((value / 10) * 100, 100)}%`, height: '100%', background: fill }} />
      </div>
      <span style={{ fontFamily: T.mono, fontSize: '10.5px', fontWeight: 300, width: '28px', textAlign: 'right', color: fill }}>
        {value?.toFixed(1)}
      </span>
    </div>
  );
}

function SectorChip({ name, ret }: { name: string; ret: number }) {
  const c = ret >= 0 ? T.up : T.dn;
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '8px 24px', borderBottom: `0.5px solid ${T.borderSub}`,
    }}>
      <span style={{ fontFamily: T.sans, fontSize: '9.5px', letterSpacing: '0.3px', color: T.textSub }}>{name}</span>
      <span style={{ fontFamily: T.mono, fontSize: '10.5px', fontWeight: 300, color: c }}>{pct(ret)}</span>
    </div>
  );
}

function MoverRow({ ticker, price, change }: { ticker: string; price: number; change: number }) {
  const c = change >= 0 ? T.up : T.dn;
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 24px', borderBottom: `0.5px solid ${T.borderSub}` }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
        <span style={{ fontFamily: T.mono, fontSize: '11px', fontWeight: 400, color: 'rgba(255,255,255,0.72)', letterSpacing: '0.3px' }}>{ticker}</span>
        <span style={{ fontFamily: T.mono, fontSize: '10px', fontWeight: 300, color: T.textMuted }}>{price?.toFixed(2)}</span>
      </div>
      <span style={{ fontFamily: T.mono, fontSize: '10.5px', fontWeight: 300, color: c }}>{pct(change)}</span>
    </div>
  );
}

function FwdCard({ horizon, ret, posPct, noBorderRight }: { horizon: string; ret: number; posPct: number; noBorderRight?: boolean }) {
  const c = ret >= 0 ? T.up : T.dn;
  return (
    <div style={{ padding: '12px 24px', borderBottom: `0.5px solid ${T.borderSub}`, borderRight: noBorderRight ? 'none' : `0.5px solid ${T.borderSub}` }}>
      <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>{horizon}</div>
      <div style={{ fontFamily: T.mono, fontSize: '17px', fontWeight: 300, letterSpacing: '-0.3px', color: c }}>{pct(ret)}</div>
      <div style={{ fontFamily: T.sans, fontSize: '9px', color: T.textMuted, marginTop: '3px', letterSpacing: '0.3px' }}>{posPct}% positive</div>
    </div>
  );
}

function AnalogueRow({ date, fwd5d, maxFwd }: { date: string; fwd5d: number; maxFwd: number }) {
  const c   = fwd5d >= 0 ? T.up : T.dn;
  const pct = Math.abs(fwd5d / maxFwd) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 24px', borderBottom: `0.5px solid ${T.borderSub}` }}>
      <span style={{ fontFamily: T.mono, fontSize: '9.5px', fontWeight: 300, color: T.textMuted, width: '68px', flexShrink: 0, letterSpacing: '0.3px' }}>{date}</span>
      <div style={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.05)' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: c }} />
      </div>
      <span style={{ fontFamily: T.mono, fontSize: '10px', fontWeight: 300, color: c, width: '46px', textAlign: 'right' }}>
        {fwd5d >= 0 ? '+' : ''}{fwd5d?.toFixed(2)}%
      </span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const { data, error, isLoading } = useSWR('/api/market/state', fetcher, {
    refreshInterval: 300000,
  });

  const envColor: Record<string, string> = {
    'Risk-On Rotation Day':    T.up,
    'Trend Day (Directional)': '#60a5fa',
    'Risk-Off / Headline Risk': T.dn,
    'Chop / Mean Reversion':   T.wa,
    'Mixed / Neutral':         T.accent,
  };

  if (isLoading) return (
    <div style={{ padding: '48px 24px', fontFamily: T.mono, fontSize: '11px', color: T.textMuted, letterSpacing: '0.5px' }}>
      Loading...
    </div>
  );

  if (error) return (
    <div style={{ padding: '48px 24px', fontFamily: T.mono, fontSize: '11px', color: T.dn, letterSpacing: '0.5px' }}>
      Error: {error.message}
    </div>
  );

  const asof       = data?.asof_utc?.slice(0, 10) ?? '—';
  const horizon    = data?.horizon ?? '1D';
  const score      = data?.score_total;
  const env        = data?.environment ?? '—';
  const confidence = data?.confidence;
  const secGreen   = data?.sectors_green;
  const vix        = data?.vix_level;
  const vixChg     = data?.vix_change_pct_1d;
  const components = data?.score_components ?? {};
  const macro      = data?.macro_regime ?? {};
  const movers     = data?.movers ?? [];
  const memory     = data?.memory ?? {};
  const analogues  = memory?.comparable_episodes ?? [];
  const maxFwd     = Math.max(...analogues.map((e: any) => Math.abs(e.fwd_5d ?? 0)), 1);

  // Sector returns from leadership data or sector_returns field
  const sectorReturns: [string, number][] = data?.sector_returns
    ? Object.entries(data.sector_returns).sort((a: any, b: any) => b[1] - a[1])
    : (data?.leadership_top3 ?? []);

  return (
    <main style={{ background: T.bg, minHeight: '100vh' }}>

      {/* ── Section 1: Market State KPIs ─────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sectionHd}>
          <span style={sectionLabel}>Market state</span>
          <span style={sectionMeta}>{asof} · {horizon} horizon · score {score?.toFixed(1)} · {env}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0,1fr))' }}>
          <KpiBlock label="Sentiment" meta="out of 100">
            <KpiValue>{score?.toFixed(1) ?? '—'}</KpiValue>
          </KpiBlock>
          <KpiBlock label="Environment">
            <div style={{ fontFamily: T.sans, fontSize: '11px', fontWeight: 400, color: envColor[env] ?? T.accent, letterSpacing: '0.8px', lineHeight: 1.5, textTransform: 'uppercase' }}>
              {env}
            </div>
          </KpiBlock>
          <KpiBlock label="Confidence" meta="out of 100">
            <KpiValue>{confidence?.toFixed(0) ?? '—'}</KpiValue>
          </KpiBlock>
          <KpiBlock label="Breadth" meta="sectors green · weak">
            <KpiValue>
              {secGreen ?? '—'}
              <span style={{ fontSize: '15px', color: T.textMuted, fontWeight: 300 }}> /11</span>
            </KpiValue>
          </KpiBlock>
          <div style={{ padding: '16px 24px' }}>
            <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '10px', fontWeight: 400 }}>VIX</div>
            <KpiValue>{vix?.toFixed(1) ?? '—'}</KpiValue>
            <div style={{ fontFamily: T.sans, fontSize: '10px', color: vixChg > 0 ? T.dn : T.up, marginTop: '5px', letterSpacing: '0.2px' }}>
              {vixChg > 0 ? '+' : ''}{vixChg?.toFixed(2)}% today
            </div>
          </div>
        </div>
      </div>

      {/* ── Section 2: Macro Regime ───────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sectionHd}>
          <span style={sectionLabel}>Macro regime</span>
          <span style={sectionMeta}>Growth · Inflation · Liquidity</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))' }}>
          {(['growth', 'inflation', 'liquidity'] as const).map((key, i) => {
            const m   = macro[key] ?? {};
            const val = m.zscore ?? m.value;
            const c   = val >= 0 ? T.up : (val < -0.2 ? T.dn : T.wa);
            return (
              <div key={key} style={{ padding: '14px 24px', borderRight: i < 2 ? `0.5px solid ${T.border}` : 'none' }}>
                <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.label, marginBottom: '6px' }}>
                  {key}
                </div>
                <MacroBadge regime={m.regime ?? m.trend ?? '—'} />
                <div style={{ fontFamily: T.mono, fontSize: '20px', fontWeight: 300, letterSpacing: '-0.5px', color: c, marginBottom: '5px' }}>
                  {val !== undefined ? fmtSigma(val) : '—'}
                </div>
                <div style={{ fontFamily: T.mono, fontSize: '9px', fontWeight: 300, color: T.textMuted, letterSpacing: '0.3px' }}>
                  MoM {m.mom !== undefined ? (m.mom >= 0 ? '+' : '') + m.mom?.toFixed(2) : '—'} · YoY {m.yoy !== undefined ? (m.yoy >= 0 ? '+' : '') + m.yoy?.toFixed(2) : '—'}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Section 3: Signal Detail ──────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sectionHd}>
          <span style={sectionLabel}>Signal detail</span>
          <span style={sectionMeta}>Components · Sectors · Movers · Memory</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 272px' }}>

          {/* Left col: Score components + Sectors */}
          <div style={{ borderRight: `0.5px solid ${T.border}` }}>
            <div style={colHd}>
              <span style={sectionLabel}>Score components</span>
            </div>
            {Object.entries(components).map(([key, val]: [string, any]) => (
              <ScoreBar key={key} label={key} value={val} />
            ))}

            <div style={{ ...colHd, marginTop: 0, borderTop: `0.5px solid ${T.border}` }}>
              <span style={sectionLabel}>Sector returns · 1D</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
              {sectorReturns.map(([name, ret]: [string, number], i: number) => (
                <div key={name} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '8px 24px',
                  borderBottom: `0.5px solid ${T.borderSub}`,
                  borderRight: i % 2 === 0 ? `0.5px solid ${T.borderSub}` : 'none',
                }}>
                  <span style={{ fontFamily: T.sans, fontSize: '9.5px', letterSpacing: '0.3px', color: T.textSub }}>{name}</span>
                  <span style={{ fontFamily: T.mono, fontSize: '10.5px', fontWeight: 300, color: ret >= 0 ? T.up : T.dn }}>{pct(ret)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Mid col: Movers */}
          <div style={{ borderRight: `0.5px solid ${T.border}` }}>
            <div style={{ ...colHd, justifyContent: 'space-between' }}>
              <span style={sectionLabel}>Market moves</span>
              <span style={sectionMeta}>Last · 1D chg</span>
            </div>
            {movers.length > 0
              ? movers.map((m: any) => (
                  <MoverRow key={m.ticker} ticker={m.ticker} price={m.last} change={m.change_pct_1d} />
                ))
              : (
                // Fallback: SPY tape data
                [
                  { ticker: 'SPY', price: data?.spy_last_price, change: data?.spy_change_pct },
                ].map((m) => (
                  <MoverRow key={m.ticker} ticker={m.ticker} price={m.price} change={m.change} />
                ))
              )
            }
          </div>

          {/* Right col: Memory */}
          <div>
            <div style={{ ...colHd, justifyContent: 'space-between' }}>
              <span style={sectionLabel}>Memory · fwd outlook</span>
              <span style={sectionMeta}>n={memory?.n ?? '—'}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
              <FwdCard horizon="1D fwd"  ret={memory?.fwd_1d  ?? 0} posPct={memory?.pct_positive_1d  ?? 0} />
              <FwdCard horizon="5D fwd"  ret={memory?.fwd_5d  ?? 0} posPct={memory?.pct_positive_5d  ?? 0} noBorderRight />
              <FwdCard horizon="10D fwd" ret={memory?.fwd_10d ?? 0} posPct={memory?.pct_positive_10d ?? 0} />
              <FwdCard horizon="21D fwd" ret={memory?.fwd_21d ?? 0} posPct={memory?.pct_positive_21d ?? 0} noBorderRight />
            </div>

            {/* Risk profile */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', borderBottom: `0.5px solid ${T.borderSub}` }}>
              {[
                { label: 'Max DD',     val: memory?.risk_max_dd,     c: T.dn },
                { label: 'Max upside', val: memory?.risk_max_up,     c: T.up },
                { label: 'Rwd / risk', val: memory?.reward_risk,     c: T.mid, suffix: '×' },
              ].map(({ label, val, c, suffix }, i) => (
                <div key={label} style={{ padding: '10px 24px', borderRight: i < 2 ? `0.5px solid ${T.borderSub}` : 'none', borderBottom: `0.5px solid ${T.border}` }}>
                  <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '4px' }}>{label}</div>
                  <div style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 300, color: c }}>
                    {val !== undefined ? (suffix ? val.toFixed(1) + suffix : pct(val)) : '—'}
                  </div>
                </div>
              ))}
            </div>

            {/* Comparable episodes */}
            <div style={colHd}>
              <span style={sectionLabel}>Comparable episodes</span>
              <span style={sectionMeta}>5D fwd</span>
            </div>
            {analogues.slice(0, 8).map((ep: any) => (
              <AnalogueRow
                key={ep.date}
                date={ep.date}
                fwd5d={ep.fwd_5d}
                maxFwd={maxFwd}
              />
            ))}
          </div>

        </div>
      </div>

    </main>
  );
}
