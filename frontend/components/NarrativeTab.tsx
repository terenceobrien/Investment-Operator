// components/NarrativeTab.tsx
// Drop into frontend/components/NarrativeTab.tsx
// Used inside the expanded analogue row in app/history/page.tsx

'use client';

import { useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001';

interface NarrativeData {
  date: string;
  narrative: {
    summary: string;
    key_signals: string[];
    risks_and_uncertainties: string[];
    regime_verdict: string;
    outcome_note: string;
  };
  market_context: {
    forward_returns: { '1d': number | null; '5d': number | null; '21d': number | null };
    risk: { max_drawdown_5d: number | null; max_upside_5d: number | null };
  };
  generated: boolean;
  model: string;
}

function SignalBadge({ text, type }: { text: string; type: 'signal' | 'risk' }) {
  const color = type === 'signal'
    ? { bg: '#0c2a1a', border: '#166534', text: '#4ade80' }
    : { bg: '#1c0a0a', border: '#7f1d1d', text: '#f87171' };
  return (
    <div style={{
      background: color.bg,
      border: `1px solid ${color.border}`,
      borderRadius: '6px',
      padding: '0.5rem 0.75rem',
      fontSize: '0.8125rem',
      color: color.text,
      lineHeight: 1.5,
      marginBottom: '0.5rem',
    }}>
      {text}
    </div>
  );
}

function OutcomeVerdict({ fwd5d }: { fwd5d: number | null }) {
  if (fwd5d === null) return null;
  const positive = fwd5d >= 0;
  return (
    <span style={{
      fontSize: '0.7rem',
      fontWeight: 600,
      padding: '2px 8px',
      borderRadius: '999px',
      background: positive ? '#0c2a1a' : '#1c0a0a',
      color: positive ? '#4ade80' : '#f87171',
      marginLeft: '8px',
    }}>
      {positive ? `▲ +${fwd5d.toFixed(2)}% (5d)` : `▼ ${fwd5d.toFixed(2)}% (5d)`}
    </span>
  );
}

export default function NarrativeTab({ date, hasSnapshot }: {
  date: string;
  hasSnapshot: boolean;
}) {
  const [data, setData] = useState<NarrativeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generated, setGenerated] = useState(false);

  const generate = async () => {
    setLoading(true);
    setError(null);
    try {
      // Try live snapshot first if available
      if (hasSnapshot) {
        const snap = await fetch(`${API_URL}/api/narrative/snapshot/${date}`);
        if (snap.ok) {
          const snapData = await snap.json();
          // Wrap snapshot in same shape as generated narrative
          setData({
            date,
            narrative: {
              summary: snapData.one_paragraph_summary || '',
              key_signals: snapData.raw_takeaways || [],
              risks_and_uncertainties: snapData.counter_narratives || [],
              regime_verdict: snapData.market_tone?.tone_notes || '',
              outcome_note: '',
            },
            market_context: { forward_returns: { '1d': null, '5d': null, '21d': null }, risk: { max_drawdown_5d: null, max_upside_5d: null } },
            generated: false,
            model: 'snapshot',
          });
          setGenerated(true);
          return;
        }
      }

      // Fall back to generated narrative from market structure
      const res = await fetch(`${API_URL}/api/narrative/historical/${date}`);
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `Error ${res.status}`);
      }
      const result = await res.json();
      setData(result);
      setGenerated(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const fwd5d = data?.market_context?.forward_returns?.['5d'] ?? null;
  const isSnapshot = data?.model === 'snapshot';

  return (
    <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid #1a1a1a' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <p style={{ fontSize: '0.7rem', color: '#6b7280', fontWeight: 500, margin: 0, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {isSnapshot ? 'Live narrative from this day' : 'Market structure narrative'}
          </p>
          {isSnapshot && (
            <span style={{ fontSize: '0.65rem', padding: '1px 6px', background: '#0c2a1a', color: '#4ade80', borderRadius: '999px', border: '1px solid #166534' }}>
              actual snapshot
            </span>
          )}
          {generated && !isSnapshot && (
            <span style={{ fontSize: '0.65rem', padding: '1px 6px', background: '#111', color: '#6b7280', borderRadius: '999px', border: '1px solid #333' }}>
              AI generated from market data
            </span>
          )}
          {fwd5d !== null && <OutcomeVerdict fwd5d={fwd5d} />}
        </div>

        {!generated && (
          <button
            onClick={generate}
            disabled={loading}
            style={{
              padding: '4px 12px',
              background: loading ? '#111' : '#fff',
              color: loading ? '#6b7280' : '#000',
              border: 'none',
              borderRadius: '6px',
              fontSize: '0.75rem',
              fontWeight: 500,
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? 'Generating...' : hasSnapshot ? 'Load narrative' : 'Generate narrative'}
          </button>
        )}
      </div>

      {error && (
        <p style={{ fontSize: '0.8125rem', color: '#f87171', margin: '0 0 0.75rem' }}>{error}</p>
      )}

      {loading && (
        <div style={{ padding: '1rem', background: '#111', borderRadius: '8px', textAlign: 'center' }}>
          <p style={{ fontSize: '0.8125rem', color: '#6b7280', margin: 0 }}>
            {hasSnapshot ? 'Loading snapshot...' : 'Generating market narrative from structure data...'}
          </p>
          <p style={{ fontSize: '0.75rem', color: '#4b5563', margin: '4px 0 0' }}>
            {!hasSnapshot && 'This takes ~3 seconds and is cached after first load'}
          </p>
        </div>
      )}

      {data && !loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>

          {/* Regime verdict */}
          {data.narrative.regime_verdict && (
            <div style={{ background: '#111', border: '1px solid #222', borderRadius: '8px', padding: '0.625rem 0.875rem' }}>
              <p style={{ fontSize: '0.7rem', color: '#6b7280', margin: '0 0 3px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Regime verdict</p>
              <p style={{ fontSize: '0.875rem', fontWeight: 500, margin: 0, fontStyle: 'italic' }}>{data.narrative.regime_verdict}</p>
            </div>
          )}

          {/* Summary */}
          {data.narrative.summary && (
            <div>
              <p style={{ fontSize: '0.7rem', color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Narrative</p>
              <p style={{ fontSize: '0.875rem', lineHeight: 1.7, color: '#d1d5db', margin: 0 }}>{data.narrative.summary}</p>
            </div>
          )}

          {/* Signals + risks side by side */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem' }}>
            {data.narrative.key_signals?.length > 0 && (
              <div>
                <p style={{ fontSize: '0.7rem', color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Key signals</p>
                {data.narrative.key_signals.map((s, i) => (
                  <SignalBadge key={i} text={s} type="signal" />
                ))}
              </div>
            )}
            {data.narrative.risks_and_uncertainties?.length > 0 && (
              <div>
                <p style={{ fontSize: '0.7rem', color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Risks & uncertainties</p>
                {data.narrative.risks_and_uncertainties.map((r, i) => (
                  <SignalBadge key={i} text={r} type="risk" />
                ))}
              </div>
            )}
          </div>

          {/* Outcome note */}
          {data.narrative.outcome_note && (
            <div style={{ background: '#0a1628', border: '1px solid #1e3a5f', borderRadius: '8px', padding: '0.625rem 0.875rem' }}>
              <p style={{ fontSize: '0.7rem', color: '#60a5fa', margin: '0 0 3px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>How it played out</p>
              <p style={{ fontSize: '0.8125rem', color: '#bfdbfe', margin: 0, lineHeight: 1.5 }}>{data.narrative.outcome_note}</p>
            </div>
          )}

          {/* Regenerate option */}
          <button
            onClick={() => { setData(null); setGenerated(false); }}
            style={{ background: 'transparent', border: 'none', color: '#4b5563', fontSize: '0.75rem', cursor: 'pointer', textAlign: 'left', padding: 0 }}
          >
            ↺ Regenerate
          </button>
        </div>
      )}
    </div>
  );
}
