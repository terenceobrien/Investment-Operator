'use client';

import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';
import { T, sx } from '@/lib/tokens';

const STANCE_COLOR: Record<string, string> = {
  bullish: T.up,
  bearish: T.dn,
  neutral: T.wa,
};

const TAKEAWAY_COLOR: Record<string, string> = {
  CHANGE: '#60a5fa',
  CONFIRMATION: T.up,
  INVALIDATION: T.dn,
  UNCLEAR: T.wa,
};

function NarrativePanel({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section style={sx.panel}>
      <div style={sx.panelHeader}>
        <span style={sx.sectionLabel}>{title}</span>
        {meta ? <span style={sx.sectionMeta}>{meta}</span> : null}
      </div>
      <div style={sx.panelBody}>{children}</div>
    </section>
  );
}

export default function NarrativePage() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [tickers, setTickers] = useState('SPY,QQQ,IWM,AAPL,MSFT,NVDA,TSLA,GOOGL,AMZN,META');
  const [completedResult, setCompletedResult] = useState<any>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);

  const { data: latest } = useSWR('/api/narrative/latest', fetcher, { onError: () => null });

  const { data: jobStatus } = useSWR(jobId ? `/api/narrative/status/${jobId}` : null, fetcher, {
    refreshInterval: jobId ? 2000 : 0,
    onSuccess: (data) => {
      if (data?.status === 'done') {
        setCompletedResult(data.result);
        setJobId(null);
      }
      if (data?.status === 'error') setJobId(null);
    },
  });

  const trigger = async () => {
    setIsTriggering(true);
    try {
      const params = new URLSearchParams({ tickers, news_category: 'general', earnings_days: '7', lookback_hours: '36' });
      const res = await fetch(`/api/narrative/synthesize?${params}`, { method: 'POST' });
      const data = await res.json();
      setJobId(data.job_id);
      setStartedAt(Date.now());
      setElapsedMs(0);
    } catch (e) {
      console.error(e);
    } finally {
      setIsTriggering(false);
    }
  };

  const result = completedResult || (jobStatus?.status === 'done' ? jobStatus.result : latest);
  const isRunning = jobId !== null && jobStatus?.status === 'running';
  const elapsedSeconds = Math.floor(elapsedMs / 1000);

  useEffect(() => {
    if (!isRunning || !startedAt) return;
    const timer = window.setInterval(() => {
      setElapsedMs(Date.now() - startedAt);
    }, 250);
    return () => window.clearInterval(timer);
  }, [isRunning, startedAt]);

  useEffect(() => {
    if (!isRunning) {
      setStartedAt(null);
      setElapsedMs(0);
    }
  }, [isRunning]);

  return (
    <main style={sx.main}>
      <div style={sx.pageShell}>
        <NarrativePanel title="Narrative state" meta="News and earnings synthesis">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.label, flexShrink: 0 }}>
                Watch tickers
              </div>
              <input
                value={tickers}
                onChange={(e) => setTickers(e.target.value)}
                style={{
                  flex: '1 1 320px',
                  fontFamily: T.mono,
                  fontSize: '12.5px',
                  fontWeight: 300,
                  color: 'rgba(255,255,255,0.75)',
                  background: 'rgba(255,255,255,0.03)',
                  border: `0.5px solid ${T.border}`,
                  padding: '8px 10px',
                  outline: 'none',
                  letterSpacing: '0.3px',
                }}
              />
              <button
                onClick={trigger}
                disabled={isTriggering || isRunning}
                style={{
                  fontFamily: T.sans,
                  fontSize: '12px',
                  letterSpacing: '1px',
                  textTransform: 'uppercase',
                  fontWeight: 500,
                  color: isRunning ? T.textMuted : 'rgba(255,255,255,0.8)',
                  background: isRunning ? 'transparent' : 'rgba(255,255,255,0.06)',
                  border: `0.5px solid ${isRunning ? T.border : 'rgba(255,255,255,0.15)'}`,
                  padding: '8px 16px',
                  cursor: isRunning ? 'not-allowed' : 'pointer',
                  flexShrink: 0,
                  whiteSpace: 'nowrap',
                  animation: isRunning ? 'temperPulse 1.8s ease-in-out infinite' : 'none',
                }}
              >
                {isRunning ? 'Synthesis running' : isTriggering ? 'Starting...' : 'Synthesize narrative'}
              </button>
            </div>

            {isRunning ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                  <span style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.text }}>Elapsed {elapsedSeconds}s</span>
                  <span style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.textMuted }}>typically 15–30 seconds</span>
                </div>
                <div style={{ height: '2px', background: T.borderSub, overflow: 'hidden', maxWidth: '320px' }}>
                  <div
                    style={{
                      width: `${Math.min(96, 15 + elapsedSeconds * 3)}%`,
                      height: '100%',
                      background: T.accent,
                      animation: 'temperPulse 1.6s ease-in-out infinite',
                    }}
                  />
                </div>
              </div>
            ) : null}

            {jobStatus?.status === 'error' ? (
              <span style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.dn }}>Error: {jobStatus.error}</span>
            ) : null}
          </div>
        </NarrativePanel>

        {result ? (
          <>
            {result.one_paragraph_summary ? (
              <NarrativePanel
                title="Summary"
                meta={result.asof_utc ? new Date(result.asof_utc).toLocaleString() : undefined}
              >
                <p style={{ fontFamily: T.sans, fontSize: '15px', color: 'rgba(255,255,255,0.72)', lineHeight: 1.7, margin: 0 }}>
                  {result.one_paragraph_summary}
                </p>
              </NarrativePanel>
            ) : null}

            {result.raw_takeaways?.length > 0 ? (
              <NarrativePanel title="What changed today">
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {result.raw_takeaways.map((item: string, i: number) => {
                    const prefix = item.match(/^(CHANGE|CONFIRMATION|INVALIDATION|UNCLEAR)/)?.[0];
                    const c = prefix ? TAKEAWAY_COLOR[prefix] : T.textMuted;
                    return (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          gap: '14px',
                          alignItems: 'flex-start',
                          padding: '12px 14px',
                          border: `0.5px solid ${T.borderSub}`,
                          background: 'rgba(255,255,255,0.012)',
                          borderRadius: '8px',
                        }}
                      >
                        {prefix ? (
                          <span
                            style={{
                              fontFamily: T.sans,
                              fontSize: '10px',
                              letterSpacing: '1px',
                              textTransform: 'uppercase',
                              fontWeight: 500,
                              color: c,
                              background: `${c}18`,
                              border: `0.5px solid ${c}40`,
                              padding: '2px 7px',
                              flexShrink: 0,
                              marginTop: '1px',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {prefix}
                          </span>
                        ) : null}
                        <p style={{ fontFamily: T.sans, fontSize: '14px', color: 'rgba(255,255,255,0.68)', lineHeight: 1.6, margin: 0 }}>
                          {prefix ? item.replace(prefix, '').replace(/^[:\s]+/, '') : item}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </NarrativePanel>
            ) : null}

            {result.dominant_narratives?.length > 0 ? (
              <NarrativePanel title="Dominant narratives">
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  {result.dominant_narratives.map((n: any, i: number) => {
                    const sc = STANCE_COLOR[n.stance] ?? T.mid;
                    return (
                      <div key={i} style={sx.subPanel}>
                        <div style={{ padding: '16px 18px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '10px', gap: '16px' }}>
                            <span style={{ fontFamily: T.sans, fontSize: '15px', fontWeight: 500, color: T.text }}>{n.title}</span>
                            <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                              <span
                                style={{
                                  fontFamily: T.sans,
                                  fontSize: '10px',
                                  letterSpacing: '1px',
                                  textTransform: 'uppercase',
                                  padding: '2px 7px',
                                  color: sc,
                                  background: `${sc}18`,
                                  border: `0.5px solid ${sc}40`,
                                  fontWeight: 500,
                                }}
                              >
                                {n.stance}
                              </span>
                              <span
                                style={{
                                  fontFamily: T.mono,
                                  fontSize: '11px',
                                  padding: '2px 7px',
                                  color: T.textMuted,
                                  border: `0.5px solid ${T.border}`,
                                }}
                              >
                                {n.confidence}/100
                              </span>
                            </div>
                          </div>
                          <p style={{ fontFamily: T.sans, fontSize: '14px', color: 'rgba(255,255,255,0.65)', lineHeight: 1.65, margin: '0 0 12px' }}>
                            {n.why_now}
                          </p>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))', gap: '16px' }}>
                            {n.key_catalysts?.length > 0 ? (
                              <div>
                                <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>
                                  Key catalysts
                                </div>
                                {n.key_catalysts.map((c: string, j: number) => (
                                  <div key={j} style={{ display: 'flex', gap: '8px', marginBottom: '4px' }}>
                                    <div style={{ width: '1px', background: T.border, flexShrink: 0 }} />
                                    <p style={{ fontFamily: T.sans, fontSize: '13px', color: 'rgba(255,255,255,0.62)', margin: 0, lineHeight: 1.5 }}>{c}</p>
                                  </div>
                                ))}
                              </div>
                            ) : null}
                            {n.what_would_change?.length > 0 ? (
                              <div>
                                <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, marginBottom: '6px' }}>
                                  What would change this
                                </div>
                                {n.what_would_change.map((w: string, j: number) => (
                                  <div key={j} style={{ display: 'flex', gap: '8px', marginBottom: '4px' }}>
                                    <div style={{ width: '1px', background: T.border, flexShrink: 0 }} />
                                    <p style={{ fontFamily: T.sans, fontSize: '13px', color: 'rgba(255,255,255,0.62)', margin: 0, lineHeight: 1.5 }}>{w}</p>
                                  </div>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </NarrativePanel>
            ) : null}

            {result.counter_narratives?.length > 0 || result.unknowns?.length > 0 ? (
              <NarrativePanel title="Counter narratives · Watchpoints">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px,1fr))', gap: '16px' }}>
                  {result.counter_narratives?.length > 0 ? (
                    <div style={sx.subPanel}>
                      <div style={sx.subPanelHeader}>
                        <span style={sx.sectionLabel}>Counter narratives</span>
                      </div>
                      <div style={{ padding: '16px 18px' }}>
                        {result.counter_narratives.map((c: string, i: number) => (
                          <p key={i} style={{ fontFamily: T.sans, fontSize: '14px', color: 'rgba(255,255,255,0.65)', lineHeight: 1.6, margin: '0 0 8px' }}>{c}</p>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {result.unknowns?.length > 0 ? (
                    <div style={sx.subPanel}>
                      <div style={sx.subPanelHeader}>
                        <span style={sx.sectionLabel}>Unknowns / watchpoints</span>
                      </div>
                      <div style={{ padding: '16px 18px' }}>
                        {result.unknowns.map((u: string, i: number) => (
                          <p key={i} style={{ fontFamily: T.sans, fontSize: '14px', color: 'rgba(255,255,255,0.65)', lineHeight: 1.6, margin: '0 0 8px' }}>{u}</p>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </NarrativePanel>
            ) : null}
          </>
        ) : !isRunning ? (
          <section style={sx.panel}>
            <div style={{ ...sx.panelBody, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '80px 24px', gap: '6px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '13px', color: T.textMuted }}>No narrative snapshot found</span>
              <span style={{ fontFamily: T.sans, fontSize: '13px', color: 'rgba(255,255,255,0.35)' }}>
                Hit "Synthesize narrative" to generate today's analysis
              </span>
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
