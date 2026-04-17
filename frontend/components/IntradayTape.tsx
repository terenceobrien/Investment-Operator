// components/IntradayTape.tsx
// Drop into frontend/components/IntradayTape.tsx
// Shows live intraday tape metrics, updates every 5 minutes

'use client';

import useSWR from 'swr';
import { fetcher } from '../lib/api';

// ── Tokens (match your existing T.* pattern) ──────────────────────────────────
const UP   = '#4ade80';
const DN   = '#f87171';
const WA   = '#facc15';
const MUTE = '#6b7280';
const SUB  = '#9ca3af';
const BG   = '#111';
const BDR  = '#1f1f1f';
const BDR2 = '#151515';

// ── Helpers ───────────────────────────────────────────────────────────────────

const retColor = (v: number | null | undefined) => {
  if (v == null) return MUTE;
  return v >= 0 ? UP : DN;
};

const fmtRet = (v: number | null | undefined, decimals = 2) => {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}%`;
};

const fmtNum = (v: number | null | undefined, d = 2) => {
  if (v == null) return '—';
  return v.toFixed(d);
};

const TAPE_CHAR_LABEL: Record<string, string> = {
  trending_up:   '↑ Trending Up',
  trending_down: '↓ Trending Down',
  choppy:        '⇅ Choppy',
  range_bound:   '↔ Range Bound',
};

const TAPE_CHAR_COLOR: Record<string, string> = {
  trending_up:   UP,
  trending_down: DN,
  choppy:        WA,
  range_bound:   MUTE,
};

// ── Sub-components ────────────────────────────────────────────────────────────

function TapeKpi({ label, value, color, sub }: {
  label: string;
  value: React.ReactNode;
  color?: string;
  sub?: string;
}) {
  return (
    <div style={{
      padding: '12px 16px',
      borderRight: `1px solid ${BDR}`,
      borderBottom: `1px solid ${BDR2}`,
      minWidth: '100px',
    }}>
      <div style={{ fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: MUTE, marginBottom: '6px' }}>
        {label}
      </div>
      <div style={{ fontSize: '18px', fontWeight: 300, fontFamily: 'monospace', color: color ?? '#fff', letterSpacing: '-0.5px', lineHeight: 1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: '11px', color: MUTE, marginTop: '3px' }}>{sub}</div>
      )}
    </div>
  );
}

function CrossAssetRow({ ticker, ret }: { ticker: string; ret: number }) {
  const c = retColor(ret);
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '6px 16px', borderBottom: `1px solid ${BDR2}`,
    }}>
      <span style={{ fontSize: '12px', color: SUB, fontFamily: 'monospace' }}>{ticker}</span>
      <span style={{ fontSize: '12px', fontWeight: 300, fontFamily: 'monospace', color: c }}>
        {fmtRet(ret)}
      </span>
    </div>
  );
}

function SectorPill({ label, isLeading }: { label: string; isLeading: boolean }) {
  const color = isLeading ? UP : DN;
  return (
    <div style={{
      fontSize: '11px', color, padding: '3px 8px', marginBottom: '4px',
      background: `${color}15`, border: `1px solid ${color}30`,
      borderRadius: '4px', fontFamily: 'monospace',
    }}>
      {label}
    </div>
  );
}

function PulseDot({ active }: { active: boolean }) {
  return (
    <span style={{
      display: 'inline-block',
      width: '6px', height: '6px',
      borderRadius: '50%',
      background: active ? UP : MUTE,
      marginRight: '6px',
      boxShadow: active ? `0 0 4px ${UP}` : 'none',
      flexShrink: 0,
    }} />
  );
}

// ── Main component ────────────────────────────────────────────────────────────

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
    { refreshInterval: 300000 } // 5 min
  );
  const data = initialData ?? fetchedData;
  const isPending = shouldFetch ? isLoading : loading;
  const isErrored = shouldFetch ? !!error : hasError;

  if (!data && isPending) {
    return (
      <div style={{ background: BG, border: `1px solid ${BDR}`, borderRadius: '12px', padding: '1rem', color: MUTE, fontSize: '0.8125rem' }}>
        Loading tape...
      </div>
    );
  }

  if (isErrored || !data) {
    return (
      <div style={{ background: BG, border: `1px solid ${BDR}`, borderRadius: '12px', padding: '1rem', color: DN, fontSize: '0.8125rem' }}>
        Tape unavailable
      </div>
    );
  }

  const tapeColor = TAPE_CHAR_COLOR[data.tape_character] ?? MUTE;
  const tapeLabel = TAPE_CHAR_LABEL[data.tape_character] ?? data.tape_character;
  const lastUpdated = new Date(data.asof_utc).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

  // Consistency indicator
  const consistencyColor = data.consistent_with_regime === true ? UP
    : data.consistent_with_regime === false ? DN : WA;

  const crossAssetOrder = ['SPY', 'QQQ', 'IWM', 'TLT', 'HYG', 'GLD', '^VIX'];

  return (
    <div style={{ background: '#0a0a0a', borderTop: `1px solid ${BDR}`, borderBottom: `1px solid ${BDR}` }}>

      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px', borderBottom: `1px solid ${BDR}`, flexWrap: 'wrap', gap: '8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <PulseDot active={data.market_open} />
          <span style={{ fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: MUTE, fontWeight: 500 }}>
            Intraday Tape
          </span>
          <span style={{
            marginLeft: '10px', fontSize: '11px', fontWeight: 600,
            color: tapeColor, letterSpacing: '0.5px',
          }}>
            {tapeLabel}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {data.consistency_note && (
            <span style={{ fontSize: '11px', color: consistencyColor }}>
              {data.consistency_note}
            </span>
          )}
          <span style={{ fontSize: '10px', color: MUTE }}>Updated {lastUpdated} · 5min refresh</span>
        </div>
      </div>

      {/* Main grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>

        {/* SPY tape */}
        <div style={{ borderRight: `1px solid ${BDR}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)' }}>
            <TapeKpi
              label="SPY Last"
              value={`$${fmtNum(data.spy_last, 2)}`}
              color="#fff"
              sub={`vs open ${fmtRet(data.spy_vs_open_pct)}`}
            />
            <TapeKpi
              label="vs VWAP"
              value={fmtRet((data.spy_last - data.spy_vwap) / data.spy_vwap * 100)}
              color={data.spy_above_vwap ? UP : DN}
              sub={data.spy_above_vwap ? '↑ above' : '↓ below'}
            />
            <TapeKpi
              label="CLV"
              value={fmtNum(data.spy_clv_intraday, 3)}
              color={data.spy_clv_intraday > 0.3 ? UP : data.spy_clv_intraday < -0.3 ? DN : WA}
              sub={`range ${fmtNum(data.spy_range_pct_intraday, 2)}%`}
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)' }}>
            <TapeKpi
              label="VIX Now"
              value={fmtNum(data.vix_now, 1)}
              color={data.vix_now > 25 ? DN : data.vix_now < 16 ? WA : '#fff'}
              sub={`${fmtRet(data.vix_vs_close)} vs close`}
            />
            <TapeKpi
              label="Breadth"
              value={`${data.sectors_green_now}/11`}
              color={data.sectors_green_now >= 7 ? UP : data.sectors_green_now <= 3 ? DN : WA}
              sub="sectors green"
            />
          </div>
        </div>

        {/* Cross asset */}
        <div style={{ borderRight: `1px solid ${BDR}` }}>
          <div style={{ padding: '8px 16px', borderBottom: `1px solid ${BDR}` }}>
            <span style={{ fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: MUTE }}>
              Cross Asset · 1D
            </span>
          </div>
          {crossAssetOrder
            .filter(t => t in data.cross_asset_now)
            .map(ticker => (
              <CrossAssetRow key={ticker} ticker={ticker} ret={data.cross_asset_now[ticker]} />
            ))}
        </div>

        {/* Sector leadership */}
        <div>
          <div style={{ padding: '8px 16px', borderBottom: `1px solid ${BDR}` }}>
            <span style={{ fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: MUTE }}>
              Sector Leadership
            </span>
          </div>
          <div style={{ padding: '10px 16px', borderBottom: `1px solid ${BDR2}` }}>
            <div style={{ fontSize: '10px', color: UP, letterSpacing: '0.5px', marginBottom: '6px', textTransform: 'uppercase' }}>
              Leading
            </div>
            {data.sectors_leading.map(s => (
              <SectorPill key={s} label={s} isLeading={true} />
            ))}
          </div>
          <div style={{ padding: '10px 16px' }}>
            <div style={{ fontSize: '10px', color: DN, letterSpacing: '0.5px', marginBottom: '6px', textTransform: 'uppercase' }}>
              Lagging
            </div>
            {data.sectors_lagging.map(s => (
              <SectorPill key={s} label={s} isLeading={false} />
            ))}
          </div>

          {/* Tape notes */}
          {data.tape_notes.length > 0 && (
            <div style={{ padding: '8px 16px', borderTop: `1px solid ${BDR2}` }}>
              {data.tape_notes.map((note, i) => (
                <div key={i} style={{ fontSize: '11px', color: SUB, marginBottom: '3px' }}>
                  · {note}
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
