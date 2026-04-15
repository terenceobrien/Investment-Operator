'use client';

import useSWR from 'swr';
import { fetcher } from '../lib/api';
import { SkeletonMetricGrid, SkeletonPanel, SkeletonRows } from '@/components/Skeleton';
import {
  T,
  sx,
  formatAccountingPct,
  formatCurrency,
  formatNumber,
  formatRelativeAge,
  freshnessColor,
} from '@/lib/tokens';

function fmtSigma(val: number | undefined) {
  if (val === undefined || val === null) return '—';
  return `${val >= 0 ? '+' : ''}${val.toFixed(2)}σ`;
}

function barColor(val: number) {
  if (val >= 6) return T.up;
  if (val >= 4) return T.wa;
  return T.dn;
}

function KpiBlock({
  label,
  children,
  meta,
}: {
  label: string;
  children: React.ReactNode;
  meta?: React.ReactNode;
}) {
  return (
    <div
      style={{
        padding: '16px 24px',
        borderRight: `0.5px solid ${T.border}`,
        borderBottom: `0.5px solid ${T.borderSub}`,
        minHeight: '108px',
      }}
    >
      <div
        style={{
          fontFamily: T.sans,
          fontSize: '11px',
          letterSpacing: '1.2px',
          textTransform: 'uppercase',
          color: T.label,
          marginBottom: '10px',
          fontWeight: 400,
        }}
      >
        {label}
      </div>
      {children}
      {meta && (
        <div
          style={{
            fontFamily: T.sans,
            fontSize: '12px',
            color: T.textMuted,
            marginTop: '5px',
            letterSpacing: '0.2px',
          }}
        >
          {meta}
        </div>
      )}
    </div>
  );
}

function KpiValue({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: T.mono,
        fontSize: '30px',
        fontWeight: 300,
        letterSpacing: '-1px',
        color: T.text,
        lineHeight: 1,
      }}
    >
      {children}
    </div>
  );
}

function MacroBadge({ regime }: { regime: string }) {
  const isDown = regime?.toLowerCase() === 'down';
  const color = isDown ? T.dn : T.wa;
  return (
    <span
      style={{
        display: 'inline-block',
        fontFamily: T.sans,
        fontSize: '10.5px',
        letterSpacing: '1px',
        textTransform: 'uppercase',
        padding: '2px 7px',
        marginBottom: '8px',
        fontWeight: 500,
        color,
        background: `${color}10`,
        border: `0.5px solid ${color}40`,
      }}
    >
      {regime || '—'}
    </span>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const fill = barColor(value);
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '8px 24px',
        borderBottom: `0.5px solid ${T.borderSub}`,
      }}
    >
      <span
        style={{
          fontFamily: T.sans,
          fontSize: '12px',
          letterSpacing: '0.3px',
          color: T.textSub,
          width: '130px',
          flexShrink: 0,
        }}
      >
        {label.replace(/_/g, ' ')}
      </span>
      <div style={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.05)' }}>
        <div style={{ width: `${Math.min((value / 10) * 100, 100)}%`, height: '100%', background: fill }} />
      </div>
      <span
        style={{
          fontFamily: T.mono,
          fontSize: '12.5px',
          fontWeight: 300,
          width: '28px',
          textAlign: 'right',
          color: fill,
        }}
      >
        {formatNumber(value, 1)}
      </span>
    </div>
  );
}

function MoverRow({
  ticker,
  price,
  change,
}: {
  ticker: string;
  price: number | undefined;
  change: number | undefined;
}) {
  const c = (change ?? 0) >= 0 ? T.up : T.dn;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        padding: '8px 24px',
        borderBottom: `0.5px solid ${T.borderSub}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', minWidth: 0 }}>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: '13px',
            fontWeight: 400,
            color: 'rgba(255,255,255,0.82)',
            letterSpacing: '0.3px',
          }}
        >
          {ticker}
        </span>
        <span style={{ fontFamily: T.mono, fontSize: '12px', fontWeight: 300, color: T.textMuted }}>
          {formatCurrency(price)}
        </span>
      </div>
      <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: c }}>
        {formatAccountingPct(change)}
      </span>
    </div>
  );
}

function FwdCard({
  horizon,
  ret,
  posPct,
}: {
  horizon: string;
  ret: number;
  posPct: number;
}) {
  const c = ret >= 0 ? T.up : T.dn;
  return (
    <div
      style={{
        padding: '12px 24px',
        borderBottom: `0.5px solid ${T.borderSub}`,
        borderRight: `0.5px solid ${T.borderSub}`,
      }}
    >
      <div
        style={{
          fontFamily: T.sans,
          fontSize: '11px',
          letterSpacing: '1.2px',
          textTransform: 'uppercase',
          color: T.textMuted,
          marginBottom: '6px',
        }}
      >
        {horizon}
      </div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: '19px',
          fontWeight: 300,
          letterSpacing: '-0.3px',
          color: c,
        }}
      >
        {formatAccountingPct(ret)}
      </div>
      <div
        style={{
          fontFamily: T.sans,
          fontSize: '11px',
          color: T.textMuted,
          marginTop: '3px',
          letterSpacing: '0.3px',
        }}
      >
        {formatNumber(posPct, 0)}% positive
      </div>
    </div>
  );
}

function AnalogueRow({
  date,
  fwd5d,
  maxFwd,
}: {
  date: string;
  fwd5d: number;
  maxFwd: number;
}) {
  const c = fwd5d >= 0 ? T.up : T.dn;
  const widthPct = Math.abs((fwd5d ?? 0) / maxFwd) * 100;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        padding: '7px 24px',
        borderBottom: `0.5px solid ${T.borderSub}`,
      }}
    >
      <span
        style={{
          fontFamily: T.mono,
          fontSize: '11.5px',
          fontWeight: 300,
          color: T.textMuted,
          width: '68px',
          flexShrink: 0,
          letterSpacing: '0.3px',
        }}
      >
        {date}
      </span>
      <div style={{ flex: 1, height: '1px', background: 'rgba(255,255,255,0.05)' }}>
        <div style={{ width: `${widthPct}%`, height: '100%', background: c }} />
      </div>
      <span
        style={{
          fontFamily: T.mono,
          fontSize: '12px',
          fontWeight: 300,
          color: c,
          width: '62px',
          textAlign: 'right',
        }}
      >
        {formatAccountingPct(fwd5d)}
      </span>
    </div>
  );
}

function MarketStateSkeleton() {
  return (
    <main style={sx.main}>
      <SkeletonPanel titleWidth="20%" metaWidth="40%">
        <SkeletonMetricGrid columns={5} items={5} />
      </SkeletonPanel>
      <SkeletonPanel titleWidth="18%" metaWidth="26%">
        <SkeletonMetricGrid columns={3} items={3} />
      </SkeletonPanel>
      <SkeletonPanel titleWidth="16%" metaWidth="32%">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))' }}>
          <div style={{ borderRight: `0.5px solid ${T.border}` }}>
            <SkeletonRows rows={7} columns={2} />
          </div>
          <div style={{ borderRight: `0.5px solid ${T.border}` }}>
            <SkeletonRows rows={8} columns={2} />
          </div>
          <div>
            <SkeletonRows rows={6} columns={2} />
          </div>
        </div>
      </SkeletonPanel>
    </main>
  );
}

export default function Dashboard() {
  const { data, error, isLoading } = useSWR('/api/market/state', fetcher, {
    refreshInterval: 300000,
  });

  const envColor: Record<string, string> = {
    'Risk-On Rotation Day': T.up,
    'Trend Day (Directional)': '#60a5fa',
    'Risk-Off / Headline Risk': T.dn,
    'Chop / Mean Reversion': T.wa,
    'Mixed / Neutral': T.accent,
  };

  if (isLoading) return <MarketStateSkeleton />;

  if (error) {
    return (
      <div style={{ padding: '48px 24px', fontFamily: T.mono, fontSize: '13px', color: T.dn, letterSpacing: '0.5px' }}>
        Error: {error.message}
      </div>
    );
  }

  const asof = data?.asof_utc?.slice(0, 10) ?? '—';
  const horizon = data?.horizon ?? '1D';
  const score = data?.score_total;
  const env = data?.environment ?? '—';
  const confidence = data?.confidence;
  const secGreen = data?.sectors_green;
  const vix = data?.vix_level;
  const vixChg = data?.vix_change_pct_1d;
  const components = data?.score_components ?? {};
  const macro = data?.macro_regime ?? {};
  const movers = data?.movers ?? [];
  const memory = data?.memory ?? {};
  const analogues = memory?.comparable_episodes ?? [];
  const maxFwd = Math.max(...analogues.map((e: any) => Math.abs(e.fwd_5d ?? 0)), 1);
  const sectorReturns: [string, number][] = data?.sector_returns
    ? Object.entries(data.sector_returns).sort((a: any, b: any) => b[1] - a[1])
    : (data?.leadership_top3 ?? []);

  return (
    <main style={sx.main}>
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Market state</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <span style={sx.sectionMeta}>
              {asof} · {horizon} horizon · score {formatNumber(score, 1)} · {env}
            </span>
            <span style={{ ...sx.sectionMeta, color: freshnessColor(data?.asof_utc) }}>
              {formatRelativeAge(data?.asof_utc)}
            </span>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
          <KpiBlock label="Sentiment" meta="out of 100">
            <KpiValue>{formatNumber(score, 1)}</KpiValue>
          </KpiBlock>
          <KpiBlock label="Environment">
            <div
              style={{
                fontFamily: T.sans,
                fontSize: '13px',
                fontWeight: 400,
                color: envColor[env] ?? T.accent,
                letterSpacing: '0.8px',
                lineHeight: 1.5,
                textTransform: 'uppercase',
              }}
            >
              {env}
            </div>
          </KpiBlock>
          <KpiBlock label="Confidence" meta="out of 100">
            <KpiValue>{formatNumber(confidence, 0)}</KpiValue>
          </KpiBlock>
          <KpiBlock label="Breadth" meta="sectors green">
            <KpiValue>
              {secGreen ?? '—'}
              <span style={{ fontSize: '15px', color: T.textMuted, fontWeight: 300 }}> /11</span>
            </KpiValue>
          </KpiBlock>
          <KpiBlock label="VIX" meta={vixChg === undefined ? '—' : `${formatAccountingPct(vixChg)} today`}>
            <KpiValue>{formatNumber(vix, 1)}</KpiValue>
          </KpiBlock>
        </div>
      </div>

      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Macro regime</span>
          <span style={sx.sectionMeta}>Growth · Inflation · Liquidity</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))' }}>
          {(['growth', 'inflation', 'liquidity'] as const).map((key) => {
            const m = macro[key] ?? {};
            const val = m.zscore ?? m.value;
            const c = val >= 0 ? T.up : val < -0.2 ? T.dn : T.wa;
            return (
              <div
                key={key}
                style={{
                  padding: '14px 24px',
                  borderRight: `0.5px solid ${T.border}`,
                  borderBottom: `0.5px solid ${T.borderSub}`,
                }}
              >
                <div
                  style={{
                    fontFamily: T.sans,
                    fontSize: '11px',
                    letterSpacing: '1.2px',
                    textTransform: 'uppercase',
                    color: T.label,
                    marginBottom: '6px',
                  }}
                >
                  {key}
                </div>
                <MacroBadge regime={m.regime ?? m.trend ?? '—'} />
                <div
                  style={{
                    fontFamily: T.mono,
                    fontSize: '22px',
                    fontWeight: 300,
                    letterSpacing: '-0.5px',
                    color: c,
                    marginBottom: '5px',
                  }}
                >
                  {val !== undefined ? fmtSigma(val) : '—'}
                </div>
                <div style={{ fontFamily: T.mono, fontSize: '11px', fontWeight: 300, color: T.textMuted, letterSpacing: '0.3px' }}>
                  MoM {m.mom !== undefined ? formatNumber(m.mom, 2) : '—'} · YoY {m.yoy !== undefined ? formatNumber(m.yoy, 2) : '—'}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Signal detail</span>
          <span style={sx.sectionMeta}>Components · Sectors · Movers · Memory</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))' }}>
          <div style={{ borderRight: `0.5px solid ${T.border}` }}>
            <div style={{ ...sx.sectionHd, padding: '8px 24px' }}>
              <span style={sx.sectionLabel}>Score components</span>
            </div>
            {Object.entries(components).map(([key, val]: [string, any]) => (
              <ScoreBar key={key} label={key} value={val} />
            ))}

            <div style={{ ...sx.sectionHd, padding: '8px 24px', borderTop: `0.5px solid ${T.border}` }}>
              <span style={sx.sectionLabel}>Sector returns · 1D</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
              {sectorReturns.map(([name, ret]) => (
                <div
                  key={name}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '8px 24px',
                    borderBottom: `0.5px solid ${T.borderSub}`,
                    borderRight: `0.5px solid ${T.borderSub}`,
                  }}
                >
                  <span style={{ fontFamily: T.sans, fontSize: '11.5px', letterSpacing: '0.3px', color: T.textSub }}>{name}</span>
                  <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: ret >= 0 ? T.up : T.dn }}>
                    {formatAccountingPct(ret)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ borderRight: `0.5px solid ${T.border}` }}>
            <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Market moves</span>
              <span style={sx.sectionMeta}>Last · 1D chg</span>
            </div>
            {(movers.length > 0 ? movers : [{ ticker: 'SPY', last: data?.spy_last_price, change_pct_1d: data?.spy_change_pct }]).map((m: any) => (
              <MoverRow key={m.ticker} ticker={m.ticker} price={m.last} change={m.change_pct_1d} />
            ))}
          </div>

          <div>
            <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Memory · fwd outlook</span>
              <span style={sx.sectionMeta}>n={memory?.n ?? '—'}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))' }}>
              <FwdCard horizon="1D fwd" ret={memory?.fwd_1d ?? 0} posPct={memory?.pct_positive_1d ?? 0} />
              <FwdCard horizon="5D fwd" ret={memory?.fwd_5d ?? 0} posPct={memory?.pct_positive_5d ?? 0} />
              <FwdCard horizon="10D fwd" ret={memory?.fwd_10d ?? 0} posPct={memory?.pct_positive_10d ?? 0} />
              <FwdCard horizon="21D fwd" ret={memory?.fwd_21d ?? 0} posPct={memory?.pct_positive_21d ?? 0} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', borderBottom: `0.5px solid ${T.borderSub}` }}>
              {[
                { label: 'Max DD', val: memory?.risk_max_dd, color: T.dn, suffix: '' },
                { label: 'Max upside', val: memory?.risk_max_up, color: T.up, suffix: '' },
                { label: 'Rwd / risk', val: memory?.reward_risk, color: T.mid, suffix: '×' },
              ].map(({ label, val, color, suffix }, idx) => (
                <div
                  key={label}
                  style={{
                    padding: '10px 24px',
                    borderRight: idx < 2 ? `0.5px solid ${T.borderSub}` : 'none',
                    borderBottom: `0.5px solid ${T.border}`,
                  }}
                >
                  <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '4px' }}>
                    {label}
                  </div>
                  <div style={{ fontFamily: T.mono, fontSize: '15px', fontWeight: 300, color }}>
                    {val !== undefined && val !== null ? (suffix ? `${formatNumber(val, 1)}${suffix}` : formatAccountingPct(val)) : '—'}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Comparable episodes</span>
              <span style={sx.sectionMeta}>5D fwd</span>
            </div>
            {analogues.slice(0, 8).map((ep: any) => (
              <AnalogueRow key={ep.date} date={ep.date} fwd5d={ep.fwd_5d} maxFwd={maxFwd} />
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
