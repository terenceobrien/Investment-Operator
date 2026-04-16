'use client';

import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '@/lib/api';
import IntradayTape from '@/components/IntradayTape';
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

function useCountUp(target: number | undefined | null, duration = 800) {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (target === undefined || target === null || Number.isNaN(target)) return;

    let frame = 0;
    let start = 0;

    setValue(0);

    const tick = (timestamp: number) => {
      if (!start) start = timestamp;
      const progress = Math.min((timestamp - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(target * eased);
      if (progress < 1) {
        frame = window.requestAnimationFrame(tick);
      }
    };

    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [target, duration]);

  return target === undefined || target === null || Number.isNaN(target) ? null : value;
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
    <div style={{
      padding: '20px 28px',
      borderRight: `1px solid ${T.border}`,
      borderBottom: `1px solid ${T.borderSub}`,
      minHeight: '116px',
    }}>
      <div style={{
        fontFamily: T.sans,
        fontSize: '11px',
        letterSpacing: '1.4px',
        textTransform: 'uppercase',
        color: T.label,
        marginBottom: '12px',
        fontWeight: 400,
      }}>
        {label}
      </div>
      {children}
      {meta && (
        <div style={{
          fontFamily: T.sans,
          fontSize: '12px',
          color: T.textMuted,
          marginTop: '6px',
          letterSpacing: '0.2px',
        }}>
          {meta}
        </div>
      )}
    </div>
  );
}

function KpiValue({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontFamily: T.mono,
      fontSize: '30px',
      fontWeight: 300,
      letterSpacing: '-1px',
      color: T.text,
      lineHeight: 1,
    }}>
      {children}
    </div>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const fill = barColor(value);
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '10px 28px',
      borderBottom: `1px solid ${T.borderSub}`,
    }}>
      <span style={{
        fontFamily: T.sans,
        fontSize: '12px',
        letterSpacing: '0.3px',
        color: T.textSub,
        width: '130px',
        flexShrink: 0,
        textTransform: 'capitalize',
      }}>
        {label.replace(/_/g, ' ')}
      </span>
      <div style={{ flex: 1, height: '2px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px' }}>
        <div style={{ width: `${Math.min((value / 10) * 100, 100)}%`, height: '100%', background: fill, borderRadius: '2px' }} />
      </div>
      <span style={{
        fontFamily: T.mono,
        fontSize: '12.5px',
        fontWeight: 300,
        width: '28px',
        textAlign: 'right',
        color: fill,
      }}>
        {formatNumber(value, 1)}
      </span>
    </div>
  );
}

function MoverRow({ ticker, price, change }: {
  ticker: string;
  price: number | undefined;
  change: number | undefined;
}) {
  const c = (change ?? 0) >= 0 ? T.up : T.dn;
  return (
    <div
      className="temper-interactive-row"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        padding: '10px 28px',
        borderBottom: `1px solid ${T.borderSub}`,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
        <span style={{ fontFamily: T.mono, fontSize: '13px', fontWeight: 400, color: 'rgba(255,255,255,0.82)', letterSpacing: '0.3px' }}>
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

function FwdCard({ horizon, ret, posPct }: {
  horizon: string;
  ret: number;
  posPct: number;
}) {
  const c = ret >= 0 ? T.up : T.dn;
  return (
    <div style={{
      padding: '14px 28px',
      borderBottom: `1px solid ${T.borderSub}`,
      borderRight: `1px solid ${T.borderSub}`,
    }}>
      <div style={{
        fontFamily: T.sans,
        fontSize: '11px',
        letterSpacing: '1.2px',
        textTransform: 'uppercase',
        color: T.textMuted,
        marginBottom: '8px',
      }}>
        {horizon}
      </div>
      <div style={{ fontFamily: T.mono, fontSize: '19px', fontWeight: 300, letterSpacing: '-0.3px', color: c }}>
        {formatAccountingPct(ret)}
      </div>
      <div style={{ fontFamily: T.sans, fontSize: '11px', color: T.textMuted, marginTop: '4px', letterSpacing: '0.3px' }}>
        {formatNumber(posPct, 0)}% positive
      </div>
    </div>
  );
}

function AnalogueRow({ date, fwd5d, maxFwd }: {
  date: string;
  fwd5d: number;
  maxFwd: number;
}) {
  const c = fwd5d >= 0 ? T.up : T.dn;
  const widthPct = Math.abs((fwd5d ?? 0) / maxFwd) * 100;
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '10px',
      padding: '9px 28px',
      borderBottom: `1px solid ${T.borderSub}`,
    }}>
      <span style={{
        fontFamily: T.mono,
        fontSize: '11.5px',
        fontWeight: 300,
        color: T.textMuted,
        width: '72px',
        flexShrink: 0,
        letterSpacing: '0.3px',
      }}>
        {date}
      </span>
      <div style={{ flex: 1, height: '2px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px' }}>
        <div style={{ width: `${widthPct}%`, height: '100%', background: c, borderRadius: '2px' }} />
      </div>
      <span style={{
        fontFamily: T.mono,
        fontSize: '12px',
        fontWeight: 300,
        color: c,
        width: '62px',
        textAlign: 'right',
      }}>
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
      <SkeletonPanel titleWidth="16%" metaWidth="32%">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))' }}>
          <div style={{ borderRight: `1px solid ${T.border}` }}><SkeletonRows rows={7} columns={2} /></div>
          <div style={{ borderRight: `1px solid ${T.border}` }}><SkeletonRows rows={8} columns={2} /></div>
          <div><SkeletonRows rows={6} columns={2} /></div>
        </div>
      </SkeletonPanel>
    </main>
  );
}

export default function Dashboard() {
  const { data, error, isLoading } = useSWR('/api/market/dashboard', fetcher, { refreshInterval: 300000 });
  const { data: heatmap }      = useSWR('/api/prices/heatmap?horizon=1D', fetcher, { refreshInterval: 300000 });
  const { data: moversData }   = useSWR('/api/brief/moves', fetcher, { refreshInterval: 300000 });
  const { data: analoguesData } = useSWR('/api/market/analogues?top_n=10', fetcher, { refreshInterval: 300000 });

  const envColor: Record<string, string> = {
    'Risk-On Rotation Day':      T.up,
    'Trend Day (Directional)':   '#60a5fa',
    'Risk-Off / Headline Risk':  T.dn,
    'Chop / Mean Reversion':     T.wa,
    'Mixed / Neutral':           T.accent,
  };

  if (isLoading) return <MarketStateSkeleton />;
  if (error) {
    return (
      <div style={{ padding: '48px 28px', fontFamily: T.mono, fontSize: '13px', color: T.dn, letterSpacing: '0.5px' }}>
        Error: {error.message}
      </div>
    );
  }

  const regime = data?.regime ?? data ?? {};
  const tape   = data?.tape   ?? {};

  const asof      = regime?.asof_date ?? data?.asof_utc?.slice(0, 10) ?? '—';
  const horizon   = regime?.horizon   ?? '1D';
  const score     = regime?.score_total;
  const env       = regime?.environment ?? '—';
  const confidence = regime?.confidence;
  const secGreen  = tape?.sectors_green_now ?? regime?.layer_breadth;
  const vix       = regime?.vix_level ?? tape?.vix_now;
  const vixChg    = tape?.vix_vs_close;

  const components = regime?.layer_monetary != null
    ? { monetary: regime.layer_monetary, credit: regime.layer_credit, volatility: regime.layer_volatility, breadth: regime.layer_breadth, positioning: regime.layer_positioning }
    : (regime?.score_components ?? {});

  const animatedScore = useCountUp(score, 800);
  const animatedConfidence = useCountUp(confidence, 800);
  const animatedVix = useCountUp(vix, 800);
  const animatedBreadth = useCountUp(secGreen, 800);

  const sectorReturns: [string, number][] = heatmap?.sectors
    ? heatmap.sectors.map((s: any) => [s.name, s.return] as [string, number]).filter(([, r]: [string, number]) => r != null).sort((a: [string, number], b: [string, number]) => b[1] - a[1])
    : [];

  const movers: any[] = moversData ?? [];

  const agg         = analoguesData?.aggregate_stats ?? {};
  const fwdReturns  = agg?.forward_returns ?? {};
  const riskProfile = agg?.risk_profile ?? {};
  const analoguesList = analoguesData?.analogues ?? [];
  const maxFwd = Math.max(...analoguesList.map((e: any) => Math.abs(e.forward_returns?.['5d'] ?? 0)), 1);

  // Section wrapper style
  const section = {
    borderBottom: `1px solid ${T.border}`,
    margin: '0 0',
  };

  const colDivider = { borderRight: `1px solid ${T.border}` };

  return (
    <main style={sx.main}>

      {/* ── Market State KPIs ── */}
      <div style={section}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Market state</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <span style={sx.sectionMeta}>
              {asof} · {horizon} · score {formatNumber(score, 1)} · {env}
            </span>
            <span style={{ ...sx.sectionMeta, color: freshnessColor(data?.asof_utc) }}>
              {formatRelativeAge(data?.asof_utc)}
            </span>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
          <KpiBlock label="Sentiment" meta="out of 100">
            <KpiValue>{formatNumber(animatedScore ?? score, 1)}</KpiValue>
          </KpiBlock>
          <KpiBlock label="Environment">
            <div style={{
              fontFamily: T.sans,
              fontSize: '13px',
              fontWeight: 400,
              color: envColor[env] ?? T.accent,
              letterSpacing: '0.8px',
              lineHeight: 1.6,
              textTransform: 'uppercase',
            }}>
              {env}
            </div>
          </KpiBlock>
          <KpiBlock label="Confidence" meta="out of 100">
            <KpiValue>{formatNumber(animatedConfidence ?? confidence, 0)}</KpiValue>
          </KpiBlock>
          <KpiBlock label="Breadth" meta="sectors green">
            <KpiValue>
              {animatedBreadth != null ? Math.round(animatedBreadth) : (secGreen ?? '—')}
              <span style={{ fontSize: '15px', color: T.textMuted, fontWeight: 300 }}> /11</span>
            </KpiValue>
          </KpiBlock>
          <KpiBlock label="VIX" meta={vixChg == null ? '—' : `${formatAccountingPct(vixChg)} today`}>
            <KpiValue>{formatNumber(animatedVix ?? vix, 1)}</KpiValue>
          </KpiBlock>
        </div>
      </div>

      {/* ── Intraday Tape ── */}
      <IntradayTape />

      {/* ── Signal Detail ── */}
      <div style={section}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Signal detail</span>
          <span style={sx.sectionMeta}>Components · Sectors · Movers · Memory</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px,1fr))' }}>

          {/* Score components + Sector returns */}
          <div style={colDivider}>
            <div style={{ ...sx.sectionHd, padding: '10px 28px' }}>
              <span style={sx.sectionLabel}>Score components</span>
            </div>
            {Object.entries(components).map(([key, val]: [string, any]) => (
              <ScoreBar key={key} label={key} value={val} />
            ))}

            <div style={{ ...sx.sectionHd, padding: '10px 28px', borderTop: `1px solid ${T.border}`, marginTop: '4px' }}>
              <span style={sx.sectionLabel}>Sector returns · 1D</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
              {sectorReturns.length > 0 ? sectorReturns.map(([name, ret]) => (
                <div key={name} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '12px',
                  padding: '9px 28px',
                  borderBottom: `1px solid ${T.borderSub}`,
                  borderRight: `1px solid ${T.borderSub}`,
                }}>
                  <span style={{ fontFamily: T.sans, fontSize: '11.5px', letterSpacing: '0.3px', color: T.textSub }}>{name}</span>
                  <span style={{ fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300, color: ret >= 0 ? T.up : T.dn }}>
                    {formatAccountingPct(ret)}
                  </span>
                </div>
              )) : (
                <div style={{ padding: '16px 28px', color: T.textMuted, fontSize: '12px' }}>Loading sectors...</div>
              )}
            </div>
          </div>

          {/* Market movers */}
          <div style={colDivider}>
            <div style={{ ...sx.sectionHd, padding: '10px 28px', justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Market moves</span>
              <span style={sx.sectionMeta}>Last · 1D chg</span>
            </div>
            {movers.length > 0 ? movers.map((m: any) => (
              <MoverRow key={m.ticker} ticker={m.ticker} price={m.last} change={m.chg_pct_1d ?? m.change_pct_1d} />
            )) : (
              <div style={{ padding: '16px 28px', color: T.textMuted, fontSize: '12px' }}>Loading movers...</div>
            )}
          </div>

          {/* Memory */}
          <div>
            <div style={{ ...sx.sectionHd, padding: '10px 28px', justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Memory · fwd outlook</span>
              <span style={sx.sectionMeta}>n={agg?.n_analogues ?? '—'}</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))' }}>
              {(['1d', '5d', '10d', '21d'] as const).map(h => {
                const s = fwdReturns[h] ?? {};
                return <FwdCard key={h} horizon={`${h.toUpperCase()} fwd`} ret={s.median ?? 0} posPct={s.pct_positive ?? 0} />;
              })}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', borderBottom: `1px solid ${T.borderSub}` }}>
              {[
                { label: 'Max DD',     val: riskProfile?.median_max_drawdown_5d, color: T.dn },
                { label: 'Max upside', val: riskProfile?.median_max_upside_5d,   color: T.up },
                { label: 'Rwd / risk', val: riskProfile?.reward_risk_ratio,       color: T.mid, suffix: '×' },
              ].map(({ label, val, color, suffix }, idx) => (
                <div key={label} style={{
                  padding: '12px 28px',
                  borderRight: idx < 2 ? `1px solid ${T.borderSub}` : 'none',
                  borderBottom: `1px solid ${T.border}`,
                }}>
                  <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '5px' }}>
                    {label}
                  </div>
                  <div style={{ fontFamily: T.mono, fontSize: '15px', fontWeight: 300, color }}>
                    {val != null ? (suffix ? `${formatNumber(val, 1)}${suffix}` : formatAccountingPct(val)) : '—'}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ ...sx.sectionHd, padding: '10px 28px', justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Comparable episodes</span>
              <span style={sx.sectionMeta}>5D fwd</span>
            </div>
            {analoguesList.slice(0, 8).map((ep: any) => (
              <AnalogueRow key={ep.date} date={ep.date} fwd5d={ep.forward_returns?.['5d'] ?? 0} maxFwd={maxFwd} />
            ))}
          </div>

        </div>
      </div>
    </main>
  );
}
