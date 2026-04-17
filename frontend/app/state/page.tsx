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
    <div
      style={{
        padding: '20px 28px',
        borderRight: `1px solid ${T.border}`,
        borderBottom: `1px solid ${T.borderSub}`,
        minHeight: '116px',
      }}
    >
      <div
        style={{
          fontFamily: T.sans,
          fontSize: '11px',
          letterSpacing: '1.4px',
          textTransform: 'uppercase',
          color: T.label,
          marginBottom: '12px',
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
            marginTop: '6px',
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

function ScoreBar({ label, value }: { label: string; value: number }) {
  const fill = barColor(value);
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '10px 28px',
        borderBottom: `1px solid ${T.borderSub}`,
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
          textTransform: 'capitalize',
        }}
      >
        {label.replace(/_/g, ' ')}
      </span>
      <div style={{ flex: 1, height: '2px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px' }}>
        <div
          style={{
            width: `${Math.min((value / 10) * 100, 100)}%`,
            height: '100%',
            background: fill,
            borderRadius: '2px',
          }}
        />
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
        <span
          style={{
            fontFamily: T.mono,
            fontSize: '12px',
            fontWeight: 300,
            color: T.textMuted,
          }}
        >
          {formatCurrency(price)}
        </span>
      </div>
      <span
        style={{
          fontFamily: T.mono,
          fontSize: '12.5px',
          fontWeight: 300,
          color: c,
        }}
      >
        {formatAccountingPct(change)}
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
          <div style={{ borderRight: `1px solid ${T.border}` }}>
            <SkeletonRows rows={7} columns={2} />
          </div>
          <div style={{ borderRight: `1px solid ${T.border}` }}>
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
  const { data: regimeData, error, isLoading } = useSWR('/api/market/regime', fetcher, {
    refreshInterval: 300000,
    revalidateOnFocus: false,
  });

  const { data: tapeData, isLoading: tapeLoading, error: tapeError } = useSWR('/api/market/tape', fetcher, {
    refreshInterval: 300000,
    revalidateOnFocus: false,
  });

  const { data: contextData, error: contextError } = useSWR('/api/market/context', fetcher, {
    refreshInterval: 300000,
    revalidateOnFocus: false,
  });

  const envColor: Record<string, string> = {
    'Risk-On Rotation Day': T.up,
    'Trend Day (Directional)': '#60a5fa',
    'Risk-Off / Headline Risk': T.dn,
    'Chop / Mean Reversion': T.wa,
    'Mixed / Neutral': T.accent,
  };

  const regime = regimeData ?? {};
  const tape = tapeData ?? {};

  const asof = regime?.asof_date ?? tape?.asof_utc?.slice(0, 10) ?? '—';
  const horizon = regime?.horizon ?? '1D';
  const score = regime?.score_total;
  const env = regime?.environment ?? '—';
  const confidence = regime?.confidence;
  const secGreen = tape?.sectors_green_now ?? regime?.layer_breadth;
  const vix = regime?.vix_level ?? tape?.vix_now;
  const vixChg = tape?.vix_vs_close;

  const components =
    regime?.layer_monetary != null
      ? {
          monetary: regime.layer_monetary,
          credit: regime.layer_credit,
          volatility: regime.layer_volatility,
          breadth: regime.layer_breadth,
          positioning: regime.layer_positioning,
        }
      : (regime?.score_components ?? {});

  const animatedScore = useCountUp(score, 800);
  const animatedConfidence = useCountUp(confidence, 800);
  const animatedVix = useCountUp(vix, 800);
  const animatedBreadth = useCountUp(secGreen, 800);

  const sectorReturns: [string, number][] = Array.isArray(contextData?.sectors)
    ? contextData.sectors
        .map((s: any) => [s.name, s.return] as [string, number])
        .filter(([, r]: [string, number]) => r != null)
        .sort((a: [string, number], b: [string, number]) => b[1] - a[1])
    : [];

  const movers: any[] = Array.isArray(contextData?.movers) ? contextData.movers : [];

  const section = {
    borderBottom: `1px solid ${T.border}`,
    margin: '0 0',
  };

  const colDivider = { borderRight: `1px solid ${T.border}` };

  if (isLoading && !regimeData) return <MarketStateSkeleton />;

  if (error) {
    return (
      <div
        style={{
          padding: '48px 28px',
          fontFamily: T.mono,
          fontSize: '13px',
          color: T.dn,
          letterSpacing: '0.5px',
        }}
      >
        Error: {error.message}
      </div>
    );
  }

  return (
    <main style={sx.main}>
      <div style={section}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Market state</span>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              flexWrap: 'wrap',
              justifyContent: 'flex-end',
            }}
          >
            <span style={sx.sectionMeta}>
              {asof} · {horizon} · score {score != null ? formatNumber(score, 1) : '—'} · {env}
            </span>
            <span style={{ ...sx.sectionMeta, color: freshnessColor(tapeData?.asof_utc ?? regimeData?.asof_utc) }}>
              {formatRelativeAge(tapeData?.asof_utc ?? regimeData?.asof_utc)}
            </span>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
          <KpiBlock label="Sentiment" meta="out of 100">
            <KpiValue>{score != null ? formatNumber(animatedScore ?? score, 1) : '—'}</KpiValue>
          </KpiBlock>

          <KpiBlock label="Environment">
            <div
              style={{
                fontFamily: T.sans,
                fontSize: '13px',
                fontWeight: 400,
                color: envColor[env] ?? T.accent,
                letterSpacing: '0.8px',
                lineHeight: 1.6,
                textTransform: 'uppercase',
              }}
            >
              {env}
            </div>
          </KpiBlock>

          <KpiBlock label="Confidence" meta="out of 100">
            <KpiValue>{confidence != null ? formatNumber(animatedConfidence ?? confidence, 0) : '—'}</KpiValue>
          </KpiBlock>

          <KpiBlock label="Breadth" meta="sectors green">
            <KpiValue>
              {animatedBreadth != null ? Math.round(animatedBreadth) : (secGreen ?? '—')}
              <span style={{ fontSize: '15px', color: T.textMuted, fontWeight: 300 }}> /11</span>
            </KpiValue>
          </KpiBlock>

          <KpiBlock label="VIX" meta={vixChg == null ? '—' : `${formatAccountingPct(vixChg)} today`}>
            <KpiValue>{vix != null ? formatNumber(animatedVix ?? vix, 1) : '—'}</KpiValue>
          </KpiBlock>
        </div>
      </div>

      <IntradayTape data={tapeData} fetch={false} loading={tapeLoading} hasError={!!tapeError} />

      <div style={section}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>Signal detail</span>
          <span style={sx.sectionMeta}>Components · Sectors · Movers</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px,1fr))' }}>
          <div style={colDivider}>
            <div style={{ ...sx.sectionHd, padding: '10px 28px' }}>
              <span style={sx.sectionLabel}>Score components</span>
            </div>

            {Object.entries(components).map(([key, val]: [string, any]) => (
              <ScoreBar key={key} label={key} value={val} />
            ))}

            <div
              style={{
                ...sx.sectionHd,
                padding: '10px 28px',
                borderTop: `1px solid ${T.border}`,
                marginTop: '4px',
              }}
            >
              <span style={sx.sectionLabel}>Sector returns · 1D</span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
              {sectorReturns.length > 0 ? (
                sectorReturns.map(([name, ret]) => (
                  <div
                    key={name}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: '12px',
                      padding: '9px 28px',
                      borderBottom: `1px solid ${T.borderSub}`,
                      borderRight: `1px solid ${T.borderSub}`,
                    }}
                  >
                    <span
                      style={{
                        fontFamily: T.sans,
                        fontSize: '11.5px',
                        letterSpacing: '0.3px',
                        color: T.textSub,
                      }}
                    >
                      {name}
                    </span>
                    <span
                      style={{
                        fontFamily: T.mono,
                        fontSize: '12.5px',
                        fontWeight: 300,
                        color: ret >= 0 ? T.up : T.dn,
                      }}
                    >
                      {formatAccountingPct(ret)}
                    </span>
                  </div>
                ))
              ) : contextError ? (
                <div style={{ padding: '16px 28px', color: T.dn, fontSize: '12px' }}>Sector data unavailable.</div>
              ) : (
                <div style={{ padding: '16px 28px', color: T.textMuted, fontSize: '12px' }}>Loading sectors...</div>
              )}
            </div>
          </div>

          <div>
            <div style={{ ...sx.sectionHd, padding: '10px 28px', justifyContent: 'space-between' }}>
              <span style={sx.sectionLabel}>Market moves</span>
              <span style={sx.sectionMeta}>Last · 1D chg</span>
            </div>

            {movers.length > 0 ? (
              movers.map((m: any) => (
                <MoverRow key={m.ticker} ticker={m.ticker} price={m.last} change={m.chg_pct_1d ?? m.change_pct_1d} />
              ))
            ) : contextError ? (
              <div style={{ padding: '16px 28px', color: T.dn, fontSize: '12px' }}>Market moves unavailable.</div>
            ) : (
              <div style={{ padding: '16px 28px', color: T.textMuted, fontSize: '12px' }}>Loading movers...</div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}