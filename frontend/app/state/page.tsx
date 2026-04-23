'use client';

import { useEffect, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import useSWR from 'swr';
import { fetcher } from '@/lib/api';
import IntradayTape from '@/components/IntradayTape';
import { SkeletonMetricGrid, SkeletonPanel, SkeletonRows, SkeletonText } from '@/components/Skeleton';
import {
  T,
  sx,
  formatAccountingPct,
  formatNumber,
  formatRelativeAge,
  freshnessColor,
} from '@/lib/tokens';

// ── Layer descriptions (static — shown on hover) ──────────────────────────────

const LAYER_DESCRIPTIONS: Record<string, string> = {
  monetary:
    'Measures net Federal Reserve liquidity (balance sheet minus Treasury General Account and overnight reverse repo), NFCI financial conditions index, and M2 money supply growth year-over-year. High score = abundant liquidity, easy financial conditions. Low score = Fed tightening or draining reserves.',
  credit:
    'Measures high-yield and investment-grade credit spread levels, 4-week spread momentum, and the HYG/TLT risk-appetite ratio. High score = spreads tight, credit markets healthy, no systemic stress. Low score = spreads widening, credit deteriorating, systemic risk rising.',
  volatility:
    'Measures VIX level and its 20-day z-score, VIX term structure slope (positive contango = calm, negative backwardation = crisis), VVIX volatility-of-volatility, equity put/call ratio, and SKEW tail-risk index. High score = calm, normal term structure. Low score = acute fear or inverted term structure.',
  breadth:
    'Measures the percentage of S&P 500 stocks trading above their 200-day moving average, new 52-week highs minus lows, green sector ETF count, and RSP vs SPY (equal-weight vs cap-weight outperformance). High score = broad market participation. Low score = narrow leadership or deteriorating internals.',
  positioning:
    'Contrarian layer. Measures equity put/call ratio, AAII retail sentiment, CFTC large speculator net positioning in S&P 500 futures (COT data), and dealer gamma exposure. High score = positioning neutral or washed-out (room to run). Low score = crowded longs, complacency, or negative-gamma territory.',
};

// ── Layer ordering ─────────────────────────────────────────────────────────────

const LAYERS = [
  { key: 'monetary',    label: 'Monetary & Liquidity' },
  { key: 'credit',      label: 'Credit & Stress' },
  { key: 'volatility',  label: 'Volatility Structure' },
  { key: 'breadth',     label: 'Breadth & Participation' },
  { key: 'positioning', label: 'Positioning & Sentiment' },
] as const;

// ── Hooks ──────────────────────────────────────────────────────────────────────

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

// ── Helpers ────────────────────────────────────────────────────────────────────

function barColor(val: number) {
  if (val >= 6) return T.up;
  if (val >= 4) return T.wa;
  return T.dn;
}

function statusColor(status: string | undefined): string {
  if (status === 'bullish') return T.up;
  if (status === 'bearish') return T.dn;
  return T.wa;
}

function statusLabel(status: string | undefined): string {
  if (status === 'bullish') return '↑ bullish';
  if (status === 'bearish') return '↓ bearish';
  return '~ neutral';
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

// ── Style constants ────────────────────────────────────────────────────────────

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

// ── Structural components ──────────────────────────────────────────────────────

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

// ── Layer detail card ──────────────────────────────────────────────────────────

function LayerDetailCard({
  label,
  score,
  status,
  dataQuality,
  signals,
  description,
  expanded,
  onToggle,
}: {
  label: string;
  score: number | null | undefined;
  status: string | undefined;
  dataQuality: number | undefined;
  signals: string[];
  description: string;
  expanded: boolean;
  onToggle: () => void;
}) {
  const sc = statusColor(status);
  const fill = score != null ? barColor(score) : T.mid;

  return (
    <div
      style={{
        background: 'rgba(255,255,255,0.018)',
        border: `1px solid ${T.border}`,
        borderRadius: '10px',
        overflow: 'hidden',
      }}
    >
      {/* ── Card header ── */}
      <div
        style={{
          padding: '13px 16px 12px',
          background: 'rgba(255,255,255,0.012)',
          borderBottom: `1px solid ${T.borderSub}`,
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '8px',
        }}
      >
        {/* Layer name + info trigger */}
        <button
          onClick={onToggle}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '5px',
            background: 'none',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
            textAlign: 'left',
          }}
          title={expanded ? 'Hide description' : 'Show description'}
        >
          <span
            style={{
              fontFamily: T.sans,
              fontSize: '11px',
              letterSpacing: '1.4px',
              textTransform: 'uppercase',
              color: T.label,
              fontWeight: 500,
            }}
          >
            {label}
          </span>
          <span
            style={{
              fontFamily: T.sans,
              fontSize: '12px',
              color: expanded ? T.accent : T.textMuted,
              lineHeight: 1,
              userSelect: 'none',
              transition: 'color 0.12s',
            }}
          >
            ⓘ
          </span>
        </button>

        {/* Status badge + data quality */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            flexShrink: 0,
            flexWrap: 'wrap',
            justifyContent: 'flex-end',
          }}
        >
          {dataQuality != null && (
            <span
              style={{
                fontFamily: T.mono,
                fontSize: '10px',
                color: T.textMuted,
                letterSpacing: '0.3px',
              }}
            >
              {Math.round(dataQuality * 100)}% data
            </span>
          )}
          {status && (
            <span
              style={{
                fontFamily: T.mono,
                fontSize: '10px',
                letterSpacing: '0.6px',
                textTransform: 'uppercase',
                color: sc,
                background: `${sc}14`,
                border: `1px solid ${sc}30`,
                padding: '2px 7px',
                borderRadius: '4px',
              }}
            >
              {statusLabel(status)}
            </span>
          )}
        </div>
      </div>

      {/* ── Inline description (shown on click/hover) ── */}
      {expanded && (
        <div
          style={{
            padding: '12px 16px',
            borderBottom: `1px solid ${T.borderSub}`,
            background: 'rgba(149,128,212,0.04)',
          }}
        >
          <p
            style={{
              fontFamily: T.sans,
              fontSize: '12px',
              color: T.textSub,
              margin: 0,
              lineHeight: 1.65,
            }}
          >
            {description}
          </p>
        </div>
      )}

      {/* ── Score bar ── */}
      <div
        style={{
          padding: '11px 16px',
          borderBottom: `1px solid ${T.borderSub}`,
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
        }}
      >
        <span
          style={{
            fontFamily: T.sans,
            fontSize: '10px',
            letterSpacing: '1px',
            textTransform: 'uppercase',
            color: T.textMuted,
            width: '40px',
            flexShrink: 0,
          }}
        >
          Score
        </span>
        <div
          style={{
            flex: 1,
            height: '2px',
            background: 'rgba(255,255,255,0.05)',
            borderRadius: '2px',
          }}
        >
          {score != null && (
            <div
              style={{
                width: `${Math.min((score / 10) * 100, 100)}%`,
                height: '100%',
                background: fill,
                borderRadius: '2px',
              }}
            />
          )}
        </div>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: '13px',
            fontWeight: 300,
            color: score != null ? fill : T.textMuted,
            width: '36px',
            textAlign: 'right',
            flexShrink: 0,
          }}
        >
          {score != null ? formatNumber(score, 1) : '—'}
        </span>
      </div>

      {/* ── Signals list ── */}
      {signals.length > 0 ? (
        <div>
          {signals.map((sig, i) => (
            <div
              key={i}
              style={{
                padding: '9px 16px',
                borderBottom: i < signals.length - 1 ? `1px solid ${T.borderSub}` : 'none',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '8px',
              }}
            >
              <span
                style={{
                  fontFamily: T.mono,
                  fontSize: '11px',
                  color: T.accent,
                  marginTop: '2px',
                  flexShrink: 0,
                  lineHeight: 1.5,
                }}
              >
                →
              </span>
              <span
                style={{
                  fontFamily: T.sans,
                  fontSize: '12px',
                  color: T.textSub,
                  lineHeight: 1.55,
                }}
              >
                {sig}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ padding: '12px 16px' }}>
          <span
            style={{
              fontFamily: T.sans,
              fontSize: '12px',
              color: T.textMuted,
            }}
          >
            No signals active
          </span>
        </div>
      )}
    </div>
  );
}

// ── Skeleton ───────────────────────────────────────────────────────────────────

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
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))', gap: '12px' }}>
            <SkeletonRows rows={4} columns={2} />
            <SkeletonRows rows={4} columns={2} />
            <SkeletonRows rows={4} columns={2} />
          </div>
        </SkeletonPanel>
      </div>
    </main>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { data: regimeData, error, isLoading } = useSWR('/api/market/regime', fetcher, {
    refreshInterval: 300000,
    revalidateOnFocus: false,
  });

  const { data: tapeData, isLoading: tapeLoading, error: tapeError } = useSWR('/api/market/tape', fetcher, {
    refreshInterval: 300000,
    revalidateOnFocus: false,
  });

  const { data: macroData, isLoading: macroLoading } = useSWR('/api/brief/macro', fetcher, {
    refreshInterval: 900000,
    revalidateOnFocus: false,
  });

  const { data: summaryData, isLoading: summaryLoading } = useSWR('/api/brief/summary', fetcher, {
    refreshInterval: 86400000,
    revalidateOnFocus: false,
  });

  // Which layer card has its description expanded (click toggles; null = all collapsed)
  const [expandedLayer, setExpandedLayer] = useState<string | null>(null);

  const envColor: Record<string, string> = {
    'Risk-On Rotation Day': T.up,
    'Trend Day (Directional)': '#60a5fa',
    'Risk-Off / Headline Risk': T.dn,
    'Chop / Mean Reversion': T.wa,
    'Mixed / Neutral': T.accent,
  };

  const regime = regimeData ?? {};
  const tape   = tapeData ?? {};

  const asof       = regime?.asof_date ?? tape?.asof_utc?.slice(0, 10) ?? '—';
  const horizon    = regime?.horizon ?? '1D';
  const score      = regime?.score_total;
  const env        = regime?.environment ?? '—';
  const confidence = regime?.confidence;
  const secGreen   = tape?.sectors_green_now ?? regime?.layer_breadth;
  const vix        = regime?.vix_level ?? tape?.vix_now;
  const vixChg     = tape?.vix_vs_close;

  const components =
    regime?.layer_monetary != null
      ? {
          monetary:    regime.layer_monetary,
          credit:      regime.layer_credit,
          volatility:  regime.layer_volatility,
          breadth:     regime.layer_breadth,
          positioning: regime.layer_positioning,
        }
      : (regime?.score_components ?? {});

  const componentEntries = Object.entries(components).filter(([, val]) => val != null) as [string, number][];

  const animatedScore      = useCountUp(score, 800);
  const animatedConfidence = useCountUp(confidence, 800);
  const animatedVix        = useCountUp(vix, 800);
  const animatedBreadth    = useCountUp(secGreen, 800);

  const diagnostics = [
    { label: 'Environment',   value: env, color: envColor[env] ?? T.text },
    { label: 'Horizon',       value: horizon, color: T.text },
    { label: 'As of',         value: asof, color: T.text },
    { label: 'Confidence',    value: confidence != null ? formatNumber(confidence, 0) : '—', color: T.text },
    { label: 'Breadth',       value: secGreen != null ? `${secGreen}/11` : '—', color: T.text },
    { label: 'VIX',           value: vix != null ? formatNumber(vix, 1) : '—', color: T.text },
    { label: 'VIX vs close',  value: vixChg != null ? formatAccountingPct(vixChg) : '—', color: (vixChg ?? 0) >= 0 ? T.dn : T.up },
    { label: 'Tape character', value: prettyTapeCharacter(tape?.tape_character), color: T.text },
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

        {/* ── Market state hero ── */}
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

        {/* ── Primary market read ── */}
        <PagePanel title="Primary market read" meta="Tape · Cross-asset context · Sector leadership">
          <IntradayTape data={tapeData} fetch={false} loading={tapeLoading} hasError={!!tapeError} />
        </PagePanel>

        {/* ── Secondary diagnostics ── */}
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

        {/* ── Layer detail ── */}
        <PagePanel
          title="Layer detail"
          meta="Per-layer scoring breakdown · click ⓘ on any layer for a description"
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))',
              gap: '12px',
            }}
          >
            {LAYERS.map(({ key, label }) => {
              const layerScore: number | null | undefined =
                key === 'monetary'    ? regime.layer_monetary    :
                key === 'credit'      ? regime.layer_credit      :
                key === 'volatility'  ? regime.layer_volatility  :
                key === 'breadth'     ? regime.layer_breadth     :
                                        regime.layer_positioning;

              const signals: string[] = Array.isArray(regime.layer_signals?.[key])
                ? (regime.layer_signals[key] as string[])
                : [];

              const layerStatus: string | undefined = regime.layer_statuses?.[key];
              const dq: number | undefined           = regime.layer_data_quality?.[key];

              return (
                <LayerDetailCard
                  key={key}
                  label={label}
                  score={layerScore}
                  status={layerStatus}
                  dataQuality={dq}
                  signals={signals}
                  description={LAYER_DESCRIPTIONS[key]}
                  expanded={expandedLayer === key}
                  onToggle={() => setExpandedLayer(prev => prev === key ? null : key)}
                />
              );
            })}
          </div>
        </PagePanel>

        {/* ── Macro Read ── */}
        <PagePanel title="Macro Read" meta="Themes · Growth · Inflation · Liquidity">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

            {/* Themes (formerly "What matters today") */}
            <InsetPanel
              title="Themes"
              meta={summaryData?.fallback ? <span style={{ color: T.wa }}>Heuristic — LLM unavailable</span> : undefined}
            >
              <div style={{ padding: '2px 0' }}>
                {summaryLoading ? (
                  <div style={{ padding: '16px' }}>
                    <SkeletonText lines={4} widths={['96%', '92%', '88%', '72%']} lineHeight={12} />
                  </div>
                ) : summaryData?.summary ? (
                  summaryData.summary
                    .split('\n')
                    .filter((line: string) => line.trim())
                    .map((line: string, i: number) => (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          gap: '12px',
                          padding: '12px 16px',
                          borderBottom: `0.5px solid ${T.borderSub}`,
                          alignItems: 'flex-start',
                        }}
                      >
                        <div
                          style={{
                            width: '3px',
                            height: '3px',
                            borderRadius: '50%',
                            background: T.textMuted,
                            marginTop: '8px',
                            flexShrink: 0,
                          }}
                        />
                        <p
                          style={{
                            fontFamily: T.sans,
                            fontSize: '14px',
                            color: 'rgba(255,255,255,0.70)',
                            lineHeight: 1.65,
                            margin: 0,
                          }}
                        >
                          {line.trim()}
                        </p>
                      </div>
                    ))
                ) : (
                  <div style={{ padding: '16px' }}>
                    <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>
                      Summary unavailable.
                    </span>
                  </div>
                )}
              </div>
            </InsetPanel>

            {/* Macro regime */}
            <InsetPanel title="Macro Regime" meta="Growth · Inflation · Liquidity">
              <div style={{ padding: '14px 16px' }}>
                {macroLoading ? (
                  <SkeletonMetricGrid columns={3} items={3} />
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px,1fr))', gap: '10px' }}>
                    {macroData && Object.entries(macroData).map(([key, signal]: [string, any]) => {
                      const trend = signal.trend ?? '';
                      const isUp = trend === 'UP';
                      const isDown = trend === 'DOWN';
                      const badgeColor = isUp ? T.up : isDown ? T.dn : T.wa;
                      return (
                        <div
                          key={key}
                          style={{
                            background: 'rgba(255,255,255,0.012)',
                            border: `1px solid ${T.borderSub}`,
                            borderRadius: '8px',
                            padding: '16px 18px',
                          }}
                        >
                          <div
                            style={{
                              fontFamily: T.sans,
                              fontSize: '10.5px',
                              letterSpacing: '1.2px',
                              textTransform: 'uppercase',
                              color: T.label,
                              marginBottom: '8px',
                            }}
                          >
                            {key}
                          </div>
                          <span
                            style={{
                              display: 'inline-block',
                              fontFamily: T.sans,
                              fontSize: '10px',
                              letterSpacing: '1px',
                              textTransform: 'uppercase',
                              padding: '2px 7px',
                              marginBottom: '10px',
                              fontWeight: 500,
                              color: badgeColor,
                              background: `${badgeColor}10`,
                              border: `0.5px solid ${badgeColor}40`,
                            }}
                          >
                            {trend || '—'}
                          </span>
                          <div
                            style={{
                              fontFamily: T.mono,
                              fontSize: '22px',
                              fontWeight: 300,
                              letterSpacing: '-0.5px',
                              color: badgeColor,
                              marginBottom: '6px',
                            }}
                          >
                            {signal.latest !== undefined
                              ? `${signal.latest >= 0 ? '+' : ''}${signal.latest.toFixed(2)}σ`
                              : '—'}
                          </div>
                          <div
                            style={{
                              fontFamily: T.mono,
                              fontSize: '11px',
                              fontWeight: 300,
                              color: T.textMuted,
                              letterSpacing: '0.3px',
                            }}
                          >
                            MoM {signal.mom !== undefined ? (signal.mom >= 0 ? '+' : '') + signal.mom.toFixed(2) : '—'}
                            {' · '}
                            YoY {signal.yoy !== undefined ? (signal.yoy >= 0 ? '+' : '') + signal.yoy.toFixed(2) : '—'}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </InsetPanel>

          </div>
        </PagePanel>

      </div>
    </main>
  );
}
