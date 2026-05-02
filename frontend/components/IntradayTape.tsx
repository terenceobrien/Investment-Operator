'use client';

import type { CSSProperties, ReactNode } from 'react';
import useSWR from 'swr';
import { fetcher } from '../lib/api';
import {
  T,
  sx,
  formatAccountingPct,
  formatNumber,
  formatRelativeAge,
  freshnessColor,
} from '@/lib/tokens';

const retColor = (v: number | null | undefined) => {
  if (v == null) return T.textMuted;
  return v >= 0 ? T.up : T.dn;
};

const fmtRet = (v: number | null | undefined, decimals = 2) => {
  if (v == null) return '—';
  return formatAccountingPct(v, decimals);
};

const fmtNum = (v: number | null | undefined, d = 2) => {
  if (v == null) return '—';
  return formatNumber(v, d);
};

const TAPE_CHAR_LABEL: Record<string, string> = {
  trending_up: 'Trending Up',
  trending_down: 'Trending Down',
  choppy: 'Choppy',
  range_bound: 'Range Bound',
};

const TAPE_CHAR_COLOR: Record<string, string> = {
  trending_up: T.up,
  trending_down: T.dn,
  choppy: T.wa,
  range_bound: T.textMuted,
};

const insetPanel: CSSProperties = {
  background: 'rgba(16,32,51,0.015)',
  border: `1px solid ${T.borderSub}`,
  borderRadius: '10px',
  overflow: 'hidden',
};

function TapeStat({
  label,
  value,
  color,
  sub,
}: {
  label: string;
  value: ReactNode;
  color?: string;
  sub?: string;
}) {
  return (
    <div
      style={{
        padding: '14px 16px',
        borderBottom: `1px solid ${T.borderSub}`,
        borderRight: `1px solid ${T.borderSub}`,
        minHeight: '78px',
      }}
    >
      <div
        style={{
          fontFamily: T.sans,
          fontSize: '10px',
          letterSpacing: '1px',
          textTransform: 'uppercase',
          color: T.textMuted,
          marginBottom: '8px',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: '18px',
          fontWeight: 300,
          color: color ?? T.text,
          letterSpacing: '-0.5px',
          lineHeight: 1,
        }}
      >
        {value}
      </div>
      {sub ? (
        <div
          style={{
            fontFamily: T.sans,
            fontSize: '11px',
            color: T.textMuted,
            marginTop: '5px',
          }}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
}

function CrossAssetRow({ ticker, ret }: { ticker: string; ret: number }) {
  const c = retColor(ret);
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '10px 16px',
        borderBottom: `1px solid ${T.borderSub}`,
      }}
    >
      <span style={{ fontSize: '12px', color: T.textSub, fontFamily: T.mono }}>{ticker}</span>
      <span style={{ fontSize: '12px', fontWeight: 300, fontFamily: T.mono, color: c }}>
        {fmtRet(ret)}
      </span>
    </div>
  );
}

function SectorPill({ label, isLeading }: { label: string; isLeading: boolean }) {
  const color = isLeading ? T.up : T.dn;
  return (
    <div
      style={{
        fontSize: '11px',
        color,
        padding: '4px 8px',
        background: `${color}14`,
        border: `1px solid ${color}26`,
        borderRadius: '6px',
        fontFamily: T.mono,
      }}
    >
      {label}
    </div>
  );
}

function PulseDot({ active }: { active: boolean }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: '6px',
        height: '6px',
        borderRadius: '50%',
        background: active ? T.up : T.textMuted,
        marginRight: '8px',
        boxShadow: active ? `0 0 6px ${T.up}` : 'none',
        flexShrink: 0,
      }}
    />
  );
}

interface TapeData {
  asof_utc: string;
  market_open: boolean;
  spy_last: number;
  spy_vwap: number;
  spy_above_vwap: boolean;
  spy_vs_open_pct: number;
  spy_range_pct_intraday: number;
  spy_clv_intraday: number;
  sectors_green_now: number;
  sectors_leading: string[];
  sectors_lagging: string[];
  vix_now: number;
  vix_vs_close: number;
  cross_asset_now: Record<string, number>;
  tape_character: string;
  tape_notes: string[];
  consistent_with_regime: boolean | null;
  consistency_note: string;
}

export default function IntradayTape({
  data: initialData,
  fetch = true,
  loading = false,
  hasError = false,
}: {
  data?: TapeData | null;
  fetch?: boolean;
  loading?: boolean;
  hasError?: boolean;
}) {
  const shouldFetch = fetch && !initialData;
  const { data: fetchedData, isLoading, error } = useSWR<TapeData>(
    shouldFetch ? '/api/market/tape' : null,
    fetcher,
    { refreshInterval: 300000 }
  );
  const data = initialData ?? fetchedData;
  const isPending = shouldFetch ? isLoading : loading;
  const isErrored = shouldFetch ? !!error : hasError;

  if (!data && isPending) {
    return (
      <div style={{ ...insetPanel, padding: '18px', color: T.textMuted, fontSize: '12px' }}>
        Loading tape...
      </div>
    );
  }

  if (isErrored || !data) {
    return (
      <div style={{ ...insetPanel, padding: '18px', color: T.dn, fontSize: '12px' }}>
        Tape unavailable
      </div>
    );
  }

  const tapeColor = TAPE_CHAR_COLOR[data.tape_character] ?? T.textMuted;
  const tapeLabel = TAPE_CHAR_LABEL[data.tape_character] ?? data.tape_character;
  const consistencyColor = data.consistent_with_regime === true ? T.up : data.consistent_with_regime === false ? T.dn : T.wa;
  const crossAssetOrder = ['SPY', 'QQQ', 'IWM', 'TLT', 'HYG', 'GLD', '^VIX'];
  const vwapDelta = data.spy_vwap ? ((data.spy_last - data.spy_vwap) / data.spy_vwap) * 100 : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
          flexWrap: 'wrap',
          padding: '0 2px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <PulseDot active={data.market_open} />
            <span style={sx.sectionLabel}>Intraday tape</span>
          </div>
          <span style={{ ...sx.sectionMeta, color: tapeColor }}>{tapeLabel}</span>
          {data.consistency_note ? (
            <span style={{ ...sx.sectionMeta, color: consistencyColor }}>{data.consistency_note}</span>
          ) : null}
        </div>
        <span style={{ ...sx.sectionMeta, color: freshnessColor(data.asof_utc) }}>{formatRelativeAge(data.asof_utc)}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))', gap: '14px' }}>
        <div style={insetPanel}>
          <div style={{ ...sx.sectionHd, padding: '12px 16px', borderLeft: 'none', borderBottom: `1px solid ${T.borderSub}` }}>
            <span style={sx.sectionLabel}>Tape / microstructure</span>
            <span style={sx.sectionMeta}>SPY · VIX · Breadth</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))' }}>
            <TapeStat label="SPY last" value={`$${fmtNum(data.spy_last, 2)}`} sub={`vs open ${fmtRet(data.spy_vs_open_pct)}`} />
            <TapeStat label="vs VWAP" value={fmtRet(vwapDelta)} color={data.spy_above_vwap ? T.up : T.dn} sub={data.spy_above_vwap ? 'Above VWAP' : 'Below VWAP'} />
            <TapeStat label="CLV" value={fmtNum(data.spy_clv_intraday, 3)} color={data.spy_clv_intraday > 0.3 ? T.up : data.spy_clv_intraday < -0.3 ? T.dn : T.wa} sub={`Range ${fmtNum(data.spy_range_pct_intraday, 2)}%`} />
            <TapeStat label="VIX now" value={fmtNum(data.vix_now, 1)} color={data.vix_now > 25 ? T.dn : data.vix_now < 16 ? T.wa : T.text} sub={`${fmtRet(data.vix_vs_close)} vs close`} />
            <TapeStat label="Breadth" value={`${data.sectors_green_now}/11`} color={data.sectors_green_now >= 7 ? T.up : data.sectors_green_now <= 3 ? T.dn : T.wa} sub="Sectors green" />
            <TapeStat label="Market" value={data.market_open ? 'Open' : 'Closed'} color={data.market_open ? T.up : T.textMuted} sub="US session status" />
          </div>
        </div>

        <div style={insetPanel}>
          <div style={{ ...sx.sectionHd, padding: '12px 16px', borderLeft: 'none', borderBottom: `1px solid ${T.borderSub}` }}>
            <span style={sx.sectionLabel}>Cross-asset context</span>
            <span style={sx.sectionMeta}>1D return map</span>
          </div>
          <div>
            {crossAssetOrder
              .filter((ticker) => ticker in data.cross_asset_now)
              .map((ticker) => (
                <CrossAssetRow key={ticker} ticker={ticker} ret={data.cross_asset_now[ticker]} />
              ))}
          </div>
        </div>

        <div style={insetPanel}>
          <div style={{ ...sx.sectionHd, padding: '12px 16px', borderLeft: 'none', borderBottom: `1px solid ${T.borderSub}` }}>
            <span style={sx.sectionLabel}>Sector leadership</span>
            <span style={sx.sectionMeta}>Leading vs lagging</span>
          </div>
          <div style={{ display: 'grid', gap: '14px', padding: '14px 16px' }}>
            <div>
              <div style={{ fontSize: '10px', color: T.up, letterSpacing: '1px', marginBottom: '8px', textTransform: 'uppercase', fontFamily: T.sans }}>
                Leading
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {data.sectors_leading.map((sector) => (
                  <SectorPill key={sector} label={sector} isLeading={true} />
                ))}
              </div>
            </div>

            <div>
              <div style={{ fontSize: '10px', color: T.dn, letterSpacing: '1px', marginBottom: '8px', textTransform: 'uppercase', fontFamily: T.sans }}>
                Lagging
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {data.sectors_lagging.map((sector) => (
                  <SectorPill key={sector} label={sector} isLeading={false} />
                ))}
              </div>
            </div>

            {data.tape_notes.length > 0 ? (
              <div style={{ paddingTop: '12px', borderTop: `1px solid ${T.borderSub}` }}>
                <div style={{ fontSize: '10px', color: T.textMuted, letterSpacing: '1px', marginBottom: '8px', textTransform: 'uppercase', fontFamily: T.sans }}>
                  Interpretation
                </div>
                <div style={{ display: 'grid', gap: '6px' }}>
                  {data.tape_notes.map((note, idx) => (
                    <div key={idx} style={{ fontSize: '11px', color: T.textSub, lineHeight: 1.45 }}>
                      {note}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
