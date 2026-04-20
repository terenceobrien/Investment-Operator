'use client';

import { useEffect, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
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
      if (progress < 1) frame = window.requestAnimationFrame(tick);
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

function prettyKey(input: string) {
  return input.replace(/_/g, ' ');
}

function prettyTapeCharacter(input?: string | null) {
  if (!input) return '—';
  return input
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

const pageShell: CSSProperties = {
  padding: '28px 24px 56px',
  display: 'flex',
  flexDirection: 'column',
  gap: '24px',
};

const panelShell: CSSProperties = {
  background: 'rgba(255,255,255,0.022)',
  border: `1px solid ${T.border}`,
  borderRadius: '10px',
  overflow: 'hidden',
};

const panelHeader: CSSProperties = {
  ...sx.sectionHd,
  padding: '14px 18px',
  background: 'rgba(255,255,255,0.016)',
  borderBottom: `1px solid ${T.borderSub}`,
};

const panelBody: CSSProperties = {
  padding: '18px',
};

const subPanel: CSSProperties = {
  background: 'rgba(255,255,255,0.015)',
  border: `1px solid ${T.borderSub}`,
  borderRadius: '10px',
  overflow: 'hidden',
};

function PagePanel({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section style={panelShell}>
      <div style={panelHeader}>
        <span style={sx.sectionLabel}>{title}</span>
        {meta ? <span style={sx.sectionMeta}>{meta}</span> : null}
      </div>
      <div style={panelBody}>{children}</div>
    </section>
  );
}

function InsetPanel({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div style={subPanel}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          padding: '12px 16px',
          borderBottom: `1px solid ${T.borderSub}`,
          background: 'rgba(255,255,255,0.012)',
        }}
      >
        <span style={sx.sectionLabel}>{title}</span>
        {meta ? <span style={sx.sectionMeta}>{meta}</span> : null}
      </div>
      {children}
    </div>
  );
}

function HeroMetric({
  label,
  children,
  meta,
  prominent = false,
}: {
  label: string;
  children: ReactNode;
  meta?: ReactNode;
  prominent?: boolean;
}) {
  return (
    <div
      style={{
        flex: prominent ? '1.8 1 360px' : '1 1 180px',
        minWidth: prominent ? '320px' : '180px',
        padding: prominent ? '24px 24px 22px' : '20px 22px 18px',
        border: `1px solid ${T.borderSub}`,
        borderRadius: '10px',
        background: prominent ? 'rgba(255,255,255,0.028)' : 'rgba(255,255,255,0.014)',
        minHeight: prominent ? '132px' : '120px',
      }}
    >
      <div
        style={{
          fontFamily: T.sans,
          fontSize: '11px',
          letterSpacing: '1.4px',
          textTransform: 'uppercase',
          color: T.label,
          marginBottom: prominent ? '16px' : '12px',
          fontWeight: 500,
        }}
      >
        {label}
      </div>
      {children}
      {meta ? (
        <div
          style={{
            fontFamily: T.sans,
            fontSize: '12px',
            color: T.textMuted,
            marginTop: '8px',
            letterSpacing: '0.2px',
          }}
        >
          {meta}
        </div>
      ) : null}
    </div>
  );
}

function KpiValue({ children }: { children: ReactNode }) {
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
        padding: '12px 16px',
        borderBottom: `1px solid ${T.borderSub}`,
      }}
    >
      <span
        style={{
          fontFamily: T.sans,
          fontSize: '12px',
          letterSpacing: '0.3px',
          color: T.textSub,
          width: '132px',
          flexShrink: 0,
          textTransform: 'capitalize',
        }}
      >
        {prettyKey(label)}
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
          width: '30px',
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
        padding: '12px 16px',
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

function DetailMessage({ children, tone = 'muted' }: { children: ReactNode; tone?: 'muted' | 'danger' }) {
  return (
    <div
      style={{
        padding: '16px',
        color: tone === 'danger' ? T.dn : T.textMuted,
        fontSize: '12px',
        fontFamily: T.sans,
      }}
    >
      {children}
    </div>
  );
}

function MarketStateSkeleton() {
  return (
    <main style={sx.main}>
      <div style={pageShell}>
        <SkeletonPanel titleWidth="20%" metaWidth="40%">
          <SkeletonMetricGrid columns={5} items={5} />
        </SkeletonPanel>
        <SkeletonPanel titleWidth="18%" metaWidth="30%">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))', gap: '16px' }}>
            <SkeletonRows rows={7} columns={2} />
            <SkeletonRows rows={8} columns={2} />
            <SkeletonRows rows={6} columns={2} />
          </div>
        </SkeletonPanel>
        <SkeletonPanel titleWidth="18%" metaWidth="30%">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px,1fr))', gap: '16px' }}>
            <SkeletonRows rows={6} columns={2} />
            <SkeletonRows rows={6} columns={2} />
          </div>
        </SkeletonPanel>
        <SkeletonPanel titleWidth="16%" metaWidth="24%">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px,1fr))', gap: '16px' }}>
            <SkeletonRows rows={8} columns={2} />
            <SkeletonRows rows={8} columns={2} />
          </div>
        </SkeletonPanel>
      </div>
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

  const componentEntries = Object.entries(components).filter(([, val]) => val != null) as [string, number][];

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
  const topSector = sectorReturns[0];
  const weakestSector = sectorReturns[sectorReturns.length - 1];
  const diagnostics = [
    { label: 'Environment', value: env, color: envColor[env] ?? T.text },
    { label: 'Horizon', value: horizon, color: T.text },
    { label: 'As of', value: asof, color: T.text },
    { label: 'Confidence', value: confidence != null ? formatNumber(confidence, 0) : '—', color: T.text },
    { label: 'Breadth', value: secGreen != null ? `${secGreen}/11` : '—', color: T.text },
    { label: 'VIX', value: vix != null ? formatNumber(vix, 1) : '—', color: T.text },
    { label: 'VIX vs close', value: vixChg != null ? formatAccountingPct(vixChg) : '—', color: (vixChg ?? 0) >= 0 ? T.dn : T.up },
    { label: 'Tape character', value: prettyTapeCharacter(tape?.tape_character), color: T.text },
    { label: 'Top sector', value: topSector ? `${topSector[0]} · ${formatAccountingPct(topSector[1])}` : '—', color: topSector ? (topSector[1] >= 0 ? T.up : T.dn) : T.textMuted },
    { label: 'Weakest sector', value: weakestSector ? `${weakestSector[0]} · ${formatAccountingPct(weakestSector[1])}` : '—', color: weakestSector ? (weakestSector[1] >= 0 ? T.up : T.dn) : T.textMuted },
  ];

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
      <div style={pageShell}>
        <PagePanel
          title="Market state"
          meta={
            <span style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <span>
                {asof} · {horizon} · score {score != null ? formatNumber(score, 1) : '—'}
              </span>
              <span style={{ color: freshnessColor(tapeData?.asof_utc ?? regimeData?.asof_utc) }}>
                {formatRelativeAge(tapeData?.asof_utc ?? regimeData?.asof_utc)}
              </span>
            </span>
          }
        >
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
            <HeroMetric label="Environment" meta="Current market state" prominent>
              <div
                style={{
                  fontFamily: T.sans,
                  fontSize: '16px',
                  fontWeight: 500,
                  color: envColor[env] ?? T.accent,
                  letterSpacing: '0.9px',
                  lineHeight: 1.35,
                  textTransform: 'uppercase',
                  maxWidth: '420px',
                }}
              >
                {env}
              </div>
            </HeroMetric>

            <HeroMetric label="Sentiment" meta="out of 100">
              <KpiValue>{score != null ? formatNumber(animatedScore ?? score, 1) : '—'}</KpiValue>
            </HeroMetric>

            <HeroMetric label="Confidence" meta="out of 100">
              <KpiValue>{confidence != null ? formatNumber(animatedConfidence ?? confidence, 0) : '—'}</KpiValue>
            </HeroMetric>

            <HeroMetric label="Breadth" meta="sectors green">
              <KpiValue>
                {animatedBreadth != null ? Math.round(animatedBreadth) : (secGreen ?? '—')}
                <span style={{ fontSize: '15px', color: T.textMuted, fontWeight: 300 }}> /11</span>
              </KpiValue>
            </HeroMetric>

            <HeroMetric label="VIX" meta={vixChg == null ? '—' : `${formatAccountingPct(vixChg)} today`}>
              <KpiValue>{vix != null ? formatNumber(animatedVix ?? vix, 1) : '—'}</KpiValue>
            </HeroMetric>
          </div>
        </PagePanel>

        <PagePanel title="Primary market read" meta="Tape · Cross-asset context · Sector leadership">
          <IntradayTape data={tapeData} fetch={false} loading={tapeLoading} hasError={!!tapeError} />
        </PagePanel>

        <PagePanel title="Secondary diagnostics" meta="Scoring framework · Regime diagnostics">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px,1fr))', gap: '16px' }}>
            <InsetPanel title="Score components" meta={`${componentEntries.length} active`}>
              <div>
                {componentEntries.map(([key, val]) => (
                  <ScoreBar key={key} label={key} value={val} />
                ))}
              </div>
            </InsetPanel>

            <InsetPanel title="Current diagnostics" meta={`${env} · ${horizon}`}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))' }}>
                {diagnostics.map((item, idx) => (
                  <div
                    key={item.label}
                    style={{
                      padding: '14px 16px',
                      borderBottom: `1px solid ${T.borderSub}`,
                      borderRight: idx % 2 === 0 ? `1px solid ${T.borderSub}` : 'none',
                      minHeight: '74px',
                    }}
                  >
                    <div
                      style={{
                        fontFamily: T.sans,
                        fontSize: '10px',
                        letterSpacing: '1px',
                        textTransform: 'uppercase',
                        color: T.textMuted,
                        marginBottom: '9px',
                      }}
                    >
                      {item.label}
                    </div>
                    <div
                      style={{
                        fontFamily: T.mono,
                        fontSize: '13px',
                        lineHeight: 1.45,
                        color: item.color,
                      }}
                    >
                      {item.value}
                    </div>
                  </div>
                ))}
              </div>
            </InsetPanel>
          </div>
        </PagePanel>

        <PagePanel title="Signal detail" meta="Decision layer above · Drill-down tables below">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px,1fr))', gap: '16px' }}>
            <InsetPanel title="Sector returns" meta="1D leadership table">
              <div>
                {sectorReturns.length > 0 ? (
                  sectorReturns.map(([name, ret]) => (
                    <div
                      key={name}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        gap: '12px',
                        padding: '12px 16px',
                        borderBottom: `1px solid ${T.borderSub}`,
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
                  <DetailMessage tone="danger">Sector data unavailable.</DetailMessage>
                ) : (
                  <DetailMessage>Loading sectors...</DetailMessage>
                )}
              </div>
            </InsetPanel>

            <InsetPanel title="Market moves" meta="Last · 1D change">
              <div>
                {movers.length > 0 ? (
                  movers.map((m: any) => (
                    <MoverRow key={m.ticker} ticker={m.ticker} price={m.last} change={m.chg_pct_1d ?? m.change_pct_1d} />
                  ))
                ) : contextError ? (
                  <DetailMessage tone="danger">Market moves unavailable.</DetailMessage>
                ) : (
                  <DetailMessage>Loading movers...</DetailMessage>
                )}
              </div>
            </InsetPanel>
          </div>
        </PagePanel>
      </div>
    </main>
  );
}
