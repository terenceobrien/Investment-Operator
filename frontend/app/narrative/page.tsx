'use client';

import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import { T, sx, pct } from '@/lib/tokens';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

const STANCE_COLOR: Record<string, string> = {
  bullish: T.up,
  bearish: T.dn,
  neutral: T.wa,
};

const TAKEAWAY_COLOR: Record<string, string> = {
  CHANGE:       '#60a5fa',
  CONFIRMATION: T.up,
  INVALIDATION: T.dn,
  UNCLEAR:      T.wa,
};

export default function NarrativePage() {
  const [jobId,           setJobId]           = useState<string | null>(null);
  const [isTriggering,    setIsTriggering]    = useState(false);
  const [tickers,         setTickers]         = useState('SPY,QQQ,IWM,AAPL,MSFT,NVDA,TSLA,GOOGL,AMZN,META');
  const [completedResult, setCompletedResult] = useState<any>(null);

  const { data: latest } = useSWR('/api/narrative/latest', fetcher, { onError: () => null });

  const { data: jobStatus } = useSWR(
    jobId ? `/api/narrative/status/${jobId}` : null,
    fetcher,
    {
      refreshInterval: jobId ? 2000 : 0,
      onSuccess: (data) => {
        if (data?.status === 'done')  { setCompletedResult(data.result); setJobId(null); }
        if (data?.status === 'error') { setJobId(null); }
      },
    }
  );

  const trigger = async () => {
    setIsTriggering(true);
    try {
      const params = new URLSearchParams({ tickers, news_category: 'general', earnings_days: '7', lookback_hours: '36' });
      const res  = await fetch(`${API_URL}/api/narrative/synthesize?${params}`, { method: 'POST' });
      const data = await res.json();
      setJobId(data.job_id);
    } catch (e) { console.error(e); }
    finally     { setIsTriggering(false); }
  };

  const result    = completedResult || (jobStatus?.status === 'done' ? jobStatus.result : latest);
  const isRunning = jobId !== null && jobStatus?.status === 'running';

  return (
    <main style={sx.main}>

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={{ ...sx.sectionHd, justifyContent: 'space-between' }}>
          <span style={sx.sectionLabel}>Narrative state</span>
          <span style={sx.sectionMeta}>News and earnings synthesis</span>
        </div>
      </div>

      {/* ── Controls ─────────────────────────────────────────────────────── */}
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 24px' }}>
          <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.label, flexShrink: 0 }}>
            Watch tickers
          </div>
          <input
            value={tickers}
            onChange={e => setTickers(e.target.value)}
            style={{
              flex: 1,
              fontFamily: T.mono,
              fontSize: '10.5px',
              fontWeight: 300,
              color: 'rgba(255,255,255,0.6)',
              background: 'rgba(255,255,255,0.03)',
              border: `0.5px solid ${T.border}`,
              padding: '6px 10px',
              outline: 'none',
              letterSpacing: '0.3px',
            }}
          />
          <button
            onClick={trigger}
            disabled={isTriggering || isRunning}
            style={{
              fontFamily: T.sans,
              fontSize: '10px',
              letterSpacing: '1px',
              textTransform: 'uppercase',
              fontWeight: 500,
              color: isRunning ? T.textMuted : 'rgba(255,255,255,0.8)',
              background: isRunning ? 'transparent' : 'rgba(255,255,255,0.06)',
              border: `0.5px solid ${isRunning ? T.border : 'rgba(255,255,255,0.15)'}`,
              padding: '6px 16px',
              cursor: isRunning ? 'not-allowed' : 'pointer',
              flexShrink: 0,
              whiteSpace: 'nowrap',
            }}
          >
            {isRunning ? 'Synthesizing...' : isTriggering ? 'Starting...' : 'Synthesize narrative'}
          </button>
        </div>
        {isRunning && (
          <div style={{ padding: '0 24px 10px' }}>
            <span style={{ fontFamily: T.mono, fontSize: '9.5px', color: T.textMuted }}>
              Running LLM synthesis — 15–30 seconds...
            </span>
          </div>
        )}
        {jobStatus?.status === 'error' && (
          <div style={{ padding: '0 24px 10px' }}>
            <span style={{ fontFamily: T.mono, fontSize: '9.5px', color: T.dn }}>Error: {jobStatus.error}</span>
          </div>
        )}
      </div>

      {/* ── Results ──────────────────────────────────────────────────────── */}
      {result ? (
        <>
          {/* Summary */}
          {result.one_paragraph_summary && (
            <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
              <div style={sx.sectionHd}>
                <span style={sx.sectionLabel}>Summary</span>
                {result.asof_utc && (
                  <span style={sx.sectionMeta}>{new Date(result.asof_utc).toLocaleString()}</span>
                )}
              </div>
              <div style={{ padding: '16px 24px' }}>
                <p style={{ fontFamily: T.sans, fontSize: '13px', color: 'rgba(255,255,255,0.55)', lineHeight: 1.7, margin: 0 }}>
                  {result.one_paragraph_summary}
                </p>
              </div>
            </div>
          )}

          {/* What changed */}
          {result.raw_takeaways?.length > 0 && (
            <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
              <div style={sx.sectionHd}>
                <span style={sx.sectionLabel}>What changed today</span>
              </div>
              {result.raw_takeaways.map((item: string, i: number) => {
                const prefix = item.match(/^(CHANGE|CONFIRMATION|INVALIDATION|UNCLEAR)/)?.[0];
                const c      = prefix ? TAKEAWAY_COLOR[prefix] : T.textMuted;
                return (
                  <div key={i} style={{
                    display: 'flex',
                    gap: '14px',
                    alignItems: 'flex-start',
                    padding: '10px 24px',
                    borderBottom: `0.5px solid ${T.borderSub}`,
                  }}>
                    {prefix && (
                      <span style={{
                        fontFamily: T.sans, fontSize: '8px', letterSpacing: '1px', textTransform: 'uppercase',
                        fontWeight: 500, color: c, background: `${c}18`,
                        border: `0.5px solid ${c}40`, padding: '2px 7px',
                        flexShrink: 0, marginTop: '1px', whiteSpace: 'nowrap',
                      }}>
                        {prefix}
                      </span>
                    )}
                    <p style={{ fontFamily: T.sans, fontSize: '12px', color: 'rgba(255,255,255,0.5)', lineHeight: 1.6, margin: 0 }}>
                      {prefix ? item.replace(prefix, '').replace(/^[:\s]+/, '') : item}
                    </p>
                  </div>
                );
              })}
            </div>
          )}

          {/* Dominant narratives */}
          {result.dominant_narratives?.length > 0 && (
            <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
              <div style={sx.sectionHd}>
                <span style={sx.sectionLabel}>Dominant narratives</span>
              </div>
              {result.dominant_narratives.map((n: any, i: number) => {
                const sc = STANCE_COLOR[n.stance] ?? T.mid;
                return (
                  <div key={i} style={{ borderBottom: `0.5px solid ${T.border}`, padding: '16px 24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px', gap: '16px' }}>
                      <span style={{ fontFamily: T.sans, fontSize: '13px', fontWeight: 500, color: T.text }}>{n.title}</span>
                      <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                        <span style={{
                          fontFamily: T.sans, fontSize: '8px', letterSpacing: '1px', textTransform: 'uppercase',
                          padding: '2px 7px', color: sc, background: `${sc}18`, border: `0.5px solid ${sc}40`, fontWeight: 500,
                        }}>{n.stance}</span>
                        <span style={{
                          fontFamily: T.mono, fontSize: '9px', padding: '2px 7px',
                          color: T.textMuted, border: `0.5px solid ${T.border}`,
                        }}>{n.confidence}/100</span>
                      </div>
                    </div>
                    <p style={{ fontFamily: T.sans, fontSize: '12px', color: 'rgba(255,255,255,0.45)', lineHeight: 1.65, margin: '0 0 12px' }}>
                      {n.why_now}
                    </p>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '16px' }}>
                      {n.key_catalysts?.length > 0 && (
                        <div>
                          <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>Key catalysts</div>
                          {n.key_catalysts.map((c: string, j: number) => (
                            <div key={j} style={{ display: 'flex', gap: '8px', marginBottom: '4px' }}>
                              <div style={{ width: '1px', background: T.border, flexShrink: 0 }} />
                              <p style={{ fontFamily: T.sans, fontSize: '11px', color: 'rgba(255,255,255,0.4)', margin: 0, lineHeight: 1.5 }}>{c}</p>
                            </div>
                          ))}
                        </div>
                      )}
                      {n.what_would_change?.length > 0 && (
                        <div>
                          <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>What would change this</div>
                          {n.what_would_change.map((w: string, j: number) => (
                            <div key={j} style={{ display: 'flex', gap: '8px', marginBottom: '4px' }}>
                              <div style={{ width: '1px', background: T.border, flexShrink: 0 }} />
                              <p style={{ fontFamily: T.sans, fontSize: '11px', color: 'rgba(255,255,255,0.4)', margin: 0, lineHeight: 1.5 }}>{w}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Counter narratives + unknowns */}
          {(result.counter_narratives?.length > 0 || result.unknowns?.length > 0) && (
            <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
              <div style={sx.sectionHd}>
                <span style={sx.sectionLabel}>Counter narratives · Watchpoints</span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))' }}>
                {result.counter_narratives?.length > 0 && (
                  <div style={{ padding: '16px 24px', borderRight: `0.5px solid ${T.border}` }}>
                    <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '10px' }}>
                      Counter narratives
                    </div>
                    {result.counter_narratives.map((c: string, i: number) => (
                      <p key={i} style={{ fontFamily: T.sans, fontSize: '12px', color: 'rgba(255,255,255,0.45)', lineHeight: 1.6, margin: '0 0 8px' }}>{c}</p>
                    ))}
                  </div>
                )}
                {result.unknowns?.length > 0 && (
                  <div style={{ padding: '16px 24px' }}>
                    <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '10px' }}>
                      Unknowns / watchpoints
                    </div>
                    {result.unknowns.map((u: string, i: number) => (
                      <p key={i} style={{ fontFamily: T.sans, fontSize: '12px', color: 'rgba(255,255,255,0.45)', lineHeight: 1.6, margin: '0 0 8px' }}>{u}</p>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      ) : !isRunning ? (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '80px 24px', gap: '6px' }}>
          <span style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>No narrative snapshot found</span>
          <span style={{ fontFamily: T.sans, fontSize: '11px', color: 'rgba(255,255,255,0.15)' }}>
            Hit "Synthesize narrative" to generate today's analysis
          </span>
        </div>
      ) : null}

    </main>
  );
}