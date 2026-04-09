'use client';

import { useState } from 'react';
import useSWR from 'swr';
import { fetcher } from '../../lib/api';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

export default function NarrativePage() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [tickers, setTickers] = useState('SPY,QQQ,IWM,AAPL,MSFT,NVDA,TSLA,GOOGL,AMZN,META');
  const [completedResult, setCompletedResult] = useState<any>(null);

  const { data: latest } = useSWR('/api/narrative/latest', fetcher, {
    onError: () => null,
  });

  const { data: jobStatus } = useSWR(
    jobId ? `/api/narrative/status/${jobId}` : null,
    fetcher,
    {
      refreshInterval: jobId ? 2000 : 0,
      onSuccess: (data) => {
        if (data?.status === 'done') {
          setCompletedResult(data.result);
          setJobId(null);
        } else if (data?.status === 'error') {
          setJobId(null);
        }
      },
    }
  );

  const trigger = async () => {
    setIsTriggering(true);
    try {
      const params = new URLSearchParams({
        tickers,
        news_category: 'general',
        earnings_days: '7',
        lookback_hours: '36',
      });
      const res = await fetch(`${API_URL}/api/narrative/synthesize?${params}`, {
        method: 'POST',
      });
      const data = await res.json();
      setJobId(data.job_id);
    } catch (e) {
      console.error(e);
    } finally {
      setIsTriggering(false);
    }
  };

  const result = completedResult || (jobStatus?.status === 'done' ? jobStatus.result : latest);
  const isRunning = jobId !== null && jobStatus?.status === 'running';

  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif', color: '#fff', background: '#0a0a0a', minHeight: '100vh' }}>

      <h1 style={{ fontSize: '1.5rem', fontWeight: 600, marginBottom: '0.25rem' }}>Narrative State</h1>
      <p style={{ fontSize: '0.875rem', color: '#6b7280', marginBottom: '2rem' }}>
        News and earnings synthesis — what changed today and why
      </p>

      {/* Controls */}
      <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem 1.25rem', marginBottom: '2rem' }}>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: '200px' }}>
            <label style={{ fontSize: '0.75rem', color: '#6b7280', display: 'block', marginBottom: '0.5rem' }}>
              Watch tickers
            </label>
            <input
              value={tickers}
              onChange={e => setTickers(e.target.value)}
              style={{
                width: '100%',
                background: '#0a0a0a',
                border: '1px solid #333',
                borderRadius: '8px',
                padding: '0.5rem 0.75rem',
                color: '#fff',
                fontSize: '0.875rem',
                boxSizing: 'border-box',
              }}
            />
          </div>
          <button
            onClick={trigger}
            disabled={isTriggering || isRunning}
            style={{
              background: isRunning ? '#1f1f1f' : '#fff',
              color: isRunning ? '#6b7280' : '#000',
              border: 'none',
              borderRadius: '8px',
              padding: '0.5rem 1.25rem',
              fontSize: '0.875rem',
              fontWeight: 500,
              cursor: isRunning ? 'not-allowed' : 'pointer',
              flexShrink: 0,
              height: '38px',
            }}
          >
            {isRunning ? 'Synthesizing...' : isTriggering ? 'Starting...' : 'Synthesize narrative'}
          </button>
        </div>
        {isRunning && (
          <p style={{ fontSize: '0.75rem', color: '#6b7280', margin: '0.75rem 0 0' }}>
            Running LLM synthesis — this takes 15–30 seconds...
          </p>
        )}
        {jobStatus?.status === 'error' && (
          <p style={{ fontSize: '0.75rem', color: '#f87171', margin: '0.75rem 0 0' }}>
            Error: {jobStatus.error}
          </p>
        )}
      </div>

      {/* Result */}
      {result && (
        <>
          {/* One paragraph summary */}
          <section style={{ marginBottom: '2rem' }}>
            <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Summary</h2>
            <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1.25rem' }}>
              <p style={{ margin: 0, lineHeight: 1.7, fontSize: '0.9375rem' }}>
                {result.one_paragraph_summary}
              </p>
            </div>
          </section>

          {/* Raw takeaways */}
          {result.raw_takeaways?.length > 0 && (
            <section style={{ marginBottom: '2rem' }}>
              <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>What changed today</h2>
              <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1rem 1.25rem' }}>
                {result.raw_takeaways.map((item: string, i: number) => {
                  const prefix = item.match(/^(CHANGE|CONFIRMATION|INVALIDATION|UNCLEAR)/)?.[0];
                  const prefixColor: Record<string, string> = {
                    CHANGE: '#60a5fa',
                    CONFIRMATION: '#4ade80',
                    INVALIDATION: '#f87171',
                    UNCLEAR: '#facc15',
                  };
                  return (
                    <div key={i} style={{ padding: '0.625rem 0', borderTop: i === 0 ? 'none' : '1px solid #1a1a1a', display: 'flex', gap: '0.75rem' }}>
                      {prefix && (
                        <span style={{
                          fontSize: '0.7rem',
                          fontWeight: 600,
                          color: prefixColor[prefix],
                          background: `${prefixColor[prefix]}22`,
                          padding: '2px 6px',
                          borderRadius: '4px',
                          flexShrink: 0,
                          alignSelf: 'flex-start',
                          marginTop: '2px',
                          letterSpacing: '0.03em',
                        }}>
                          {prefix}
                        </span>
                      )}
                      <p style={{ margin: 0, fontSize: '0.875rem', lineHeight: 1.6, color: '#d1d5db' }}>
                        {prefix ? item.replace(prefix, '').replace(/^[:\s]+/, '') : item}
                      </p>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Dominant narratives */}
          {result.dominant_narratives?.length > 0 && (
            <section style={{ marginBottom: '2rem' }}>
              <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Dominant narratives</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {result.dominant_narratives.map((n: any, i: number) => {
                  const stanceColor = n.stance === 'bullish' ? '#4ade80' : n.stance === 'bearish' ? '#f87171' : '#facc15';
                  return (
                    <div key={i} style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1.25rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem', gap: '1rem', flexWrap: 'wrap' }}>
                        <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, margin: 0 }}>{n.title}</h3>
                        <div style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
                          <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '999px', background: `${stanceColor}22`, color: stanceColor, fontWeight: 500 }}>
                            {n.stance}
                          </span>
                          <span style={{ fontSize: '0.75rem', padding: '2px 8px', borderRadius: '999px', background: '#1f1f1f', color: '#9ca3af' }}>
                            {n.confidence}/100
                          </span>
                        </div>
                      </div>
                      <p style={{ fontSize: '0.875rem', color: '#d1d5db', lineHeight: 1.6, margin: '0 0 1rem' }}>
                        {n.why_now}
                      </p>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
                        {n.key_catalysts?.length > 0 && (
                          <div>
                            <p style={{ fontSize: '0.75rem', color: '#6b7280', fontWeight: 500, margin: '0 0 0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Key catalysts</p>
                            {n.key_catalysts.map((c: string, j: number) => (
                              <p key={j} style={{ fontSize: '0.8125rem', color: '#9ca3af', margin: '0 0 0.25rem', paddingLeft: '0.75rem', borderLeft: '2px solid #333' }}>{c}</p>
                            ))}
                          </div>
                        )}
                        {n.what_would_change?.length > 0 && (
                          <div>
                            <p style={{ fontSize: '0.75rem', color: '#6b7280', fontWeight: 500, margin: '0 0 0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>What would change this</p>
                            {n.what_would_change.map((w: string, j: number) => (
                              <p key={j} style={{ fontSize: '0.8125rem', color: '#9ca3af', margin: '0 0 0.25rem', paddingLeft: '0.75rem', borderLeft: '2px solid #333' }}>{w}</p>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* Counter narratives + unknowns */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
            {result.counter_narratives?.length > 0 && (
              <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1.25rem' }}>
                <h2 style={{ fontSize: '0.875rem', fontWeight: 600, margin: '0 0 0.75rem', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Counter narratives</h2>
                {result.counter_narratives.map((c: string, i: number) => (
                  <p key={i} style={{ fontSize: '0.875rem', color: '#d1d5db', margin: '0 0 0.5rem', lineHeight: 1.5 }}>{c}</p>
                ))}
              </div>
            )}
            {result.unknowns?.length > 0 && (
              <div style={{ background: '#111', border: '1px solid #222', borderRadius: '12px', padding: '1.25rem' }}>
                <h2 style={{ fontSize: '0.875rem', fontWeight: 600, margin: '0 0 0.75rem', color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Unknowns / watchpoints</h2>
                {result.unknowns.map((u: string, i: number) => (
                  <p key={i} style={{ fontSize: '0.875rem', color: '#d1d5db', margin: '0 0 0.5rem', lineHeight: 1.5 }}>{u}</p>
                ))}
              </div>
            )}
          </div>

          {result.asof_utc && (
            <p style={{ fontSize: '0.75rem', color: '#4b5563' }}>
              Generated: {new Date(result.asof_utc).toLocaleString()}
            </p>
          )}
        </>
      )}

      {!result && !isRunning && (
        <div style={{ textAlign: 'center', padding: '4rem 2rem', color: '#4b5563' }}>
          <p style={{ fontSize: '0.9375rem', margin: '0 0 0.5rem' }}>No narrative snapshot found</p>
          <p style={{ fontSize: '0.875rem', margin: 0 }}>Hit "Synthesize narrative" to generate today's analysis</p>
        </div>
      )}

    </main>
  );
}