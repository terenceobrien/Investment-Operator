'use client';

import { useState } from 'react';
import { SkeletonBlock, SkeletonText } from '@/components/Skeleton';
import { T } from '@/lib/tokens';

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

function Chip({ text, tone }: { text: string; tone: 'signal' | 'risk' | 'meta' }) {
  const palette =
    tone === 'signal'
      ? { bg: `${T.up}12`, border: `${T.up}40`, text: T.up }
      : tone === 'risk'
        ? { bg: `${T.dn}10`, border: `${T.dn}40`, text: T.dn }
        : { bg: 'rgba(255,255,255,0.04)', border: T.border, text: T.textMuted };

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        background: palette.bg,
        border: `0.5px solid ${palette.border}`,
        padding: '7px 10px',
        fontFamily: T.sans,
        fontSize: '12.5px',
        color: palette.text,
        lineHeight: 1.55,
        marginBottom: tone === 'meta' ? 0 : '8px',
      }}
    >
      {text}
    </div>
  );
}

export default function NarrativeTab({ date, hasSnapshot }: { date: string; hasSnapshot: boolean }) {
  const [data, setData] = useState<NarrativeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generated, setGenerated] = useState(false);

  const generate = async () => {
    setLoading(true);
    setError(null);
    try {
      if (hasSnapshot) {
        const snap = await fetch(`/api/narrative/snapshot/${date}`);
        if (snap.ok) {
          const snapData = await snap.json();
          setData({
            date,
            narrative: {
              summary: snapData.one_paragraph_summary || '',
              key_signals: snapData.raw_takeaways || [],
              risks_and_uncertainties: snapData.counter_narratives || [],
              regime_verdict: snapData.market_tone?.tone_notes || '',
              outcome_note: '',
            },
            market_context: {
              forward_returns: { '1d': null, '5d': null, '21d': null },
              risk: { max_drawdown_5d: null, max_upside_5d: null },
            },
            generated: false,
            model: 'snapshot',
          });
          setGenerated(true);
          return;
        }
      }

      const res = await fetch(`/api/narrative/historical/${date}`);
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `Error ${res.status}`);
      }
      setData(await res.json());
      setGenerated(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const isSnapshot = data?.model === 'snapshot';

  return (
    <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: `0.5px solid ${T.borderSub}` }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted }}>
            {isSnapshot ? 'Live narrative from this day' : 'Market structure narrative'}
          </span>
          {isSnapshot && <Chip text="actual snapshot" tone="signal" />}
          {generated && !isSnapshot && <Chip text="generated from market structure" tone="meta" />}
        </div>

        {!generated && (
          <button
            onClick={generate}
            disabled={loading}
            style={{
              fontFamily: T.sans,
              fontSize: '11px',
              letterSpacing: '1px',
              textTransform: 'uppercase',
              color: loading ? T.textMuted : T.text,
              background: loading ? 'transparent' : 'rgba(255,255,255,0.06)',
              border: `0.5px solid ${loading ? T.border : 'rgba(255,255,255,0.15)'}`,
              padding: '4px 12px',
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            {hasSnapshot ? 'Load narrative' : 'Generate narrative'}
          </button>
        )}
      </div>

      {error && (
        <p style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.dn, margin: '0 0 12px' }}>{error}</p>
      )}

      {loading && (
        <div style={{ padding: '14px 0', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <SkeletonBlock width="34%" height={11} />
          <SkeletonText lines={3} widths={['96%', '92%', '74%']} lineHeight={11} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))', gap: '10px' }}>
            <SkeletonBlock height={84} />
            <SkeletonBlock height={84} />
          </div>
        </div>
      )}

      {data && !loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {data.narrative.regime_verdict && (
            <div style={{ background: 'rgba(255,255,255,0.02)', border: `0.5px solid ${T.border}`, padding: '10px 12px' }}>
              <p style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, margin: '0 0 4px' }}>
                Regime verdict
              </p>
              <p style={{ fontFamily: T.sans, fontSize: '13px', fontWeight: 500, margin: 0, color: T.text }}>
                {data.narrative.regime_verdict}
              </p>
            </div>
          )}

          {data.narrative.summary && (
            <div>
              <p style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, margin: '0 0 6px' }}>
                Narrative
              </p>
              <p style={{ fontFamily: T.sans, fontSize: '13.5px', lineHeight: 1.7, color: 'rgba(255,255,255,0.72)', margin: 0 }}>
                {data.narrative.summary}
              </p>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px,1fr))', gap: '14px' }}>
            {data.narrative.key_signals?.length > 0 && (
              <div>
                <p style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, margin: '0 0 6px' }}>
                  Key signals
                </p>
                {data.narrative.key_signals.map((s, i) => (
                  <Chip key={i} text={s} tone="signal" />
                ))}
              </div>
            )}
            {data.narrative.risks_and_uncertainties?.length > 0 && (
              <div>
                <p style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, margin: '0 0 6px' }}>
                  Risks and uncertainties
                </p>
                {data.narrative.risks_and_uncertainties.map((r, i) => (
                  <Chip key={i} text={r} tone="risk" />
                ))}
              </div>
            )}
          </div>

          {data.narrative.outcome_note && (
            <div style={{ background: `${T.accent}10`, border: `0.5px solid ${T.accent}40`, padding: '10px 12px' }}>
              <p style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.accent, margin: '0 0 4px' }}>
                How it played out
              </p>
              <p style={{ fontFamily: T.sans, fontSize: '12.5px', color: 'rgba(255,255,255,0.72)', margin: 0, lineHeight: 1.6 }}>
                {data.narrative.outcome_note}
              </p>
            </div>
          )}

          <button
            onClick={() => {
              setData(null);
              setGenerated(false);
            }}
            style={{
              background: 'transparent',
              border: 'none',
              color: T.textMuted,
              fontFamily: T.mono,
              fontSize: '11px',
              cursor: 'pointer',
              textAlign: 'left',
              padding: 0,
            }}
          >
            Reset
          </button>
        </div>
      )}
    </div>
  );
}
