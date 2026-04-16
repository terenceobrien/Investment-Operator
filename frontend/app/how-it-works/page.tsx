'use client';

import { T, sx } from '@/lib/tokens';

function Section({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ borderBottom: `0.5px solid ${T.border}` }}>
      <div style={sx.sectionHd}>
        <span style={sx.sectionLabel}>{title}</span>
        {meta ? <span style={sx.sectionMeta}>{meta}</span> : null}
      </div>
      <div style={{ padding: '20px 24px' }}>{children}</div>
    </section>
  );
}

function Copy({ children }: { children: React.ReactNode }) {
  return (
    <p
      style={{
        fontFamily: T.sans,
        fontSize: '14px',
        color: 'rgba(255,255,255,0.72)',
        lineHeight: 1.75,
        margin: 0,
      }}
    >
      {children}
    </p>
  );
}

export default function HowItWorksPage() {
  return (
    <main style={sx.main}>
      <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
        <div style={sx.sectionHd}>
          <span style={sx.sectionLabel}>How it works</span>
          <span style={sx.sectionMeta}>Helix framework</span>
        </div>
      </div>

      <Section title="Sentiment score" meta="0–100 composite">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px,1fr))', gap: '18px' }}>
          <Copy>
            The sentiment score is a structured read of the tape, not a generic market opinion. Helix takes five component signals from the live market state engine and scores each one on a 0–10 scale before applying configurable weights.
          </Copy>
          <Copy>
            Those components measure whether risk appetite is improving, whether price trends are persistent, whether volatility is supportive or hostile, whether participation is broad enough to trust, and whether leadership is coherent across sectors and assets.
          </Copy>
          <Copy>
            The result is a single number that makes market posture easy to compare across days, but the component breakout remains visible so you can see what is actually driving the score.
          </Copy>
        </div>
      </Section>

      <Section title="Environment classification" meta="market regime framing">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px,1fr))', gap: '18px' }}>
          <Copy>
            Environment labels translate the raw signal stack into an actionable regime, such as trend day, risk-off headline risk, chop, or mixed conditions. This is intended to answer the practical question a PM would ask first: what kind of market is this?
          </Copy>
          <Copy>
            Classification is based on the interaction between score level, confidence, breadth, volatility conditions, and cross-asset confirmation. A strong number by itself is not enough. Helix is looking for alignment between the internals and the headline score.
          </Copy>
        </div>
      </Section>

      <Section title="Market memory" meta="historical analogues">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px,1fr))', gap: '18px' }}>
          <Copy>
            Market Memory finds historical days that most closely resemble the current state. Analogues are ranked by similarity using the current environment, total score, volatility regime, breadth, and score momentum rather than by simple date-based comparisons.
          </Copy>
          <Copy>
            For each comparable episode, Helix stores what happened next: forward returns, drawdowns, upside capture, and the path over the following sessions. The goal is not to predict a single outcome, but to surface the distribution of what usually followed when the market looked like this.
          </Copy>
          <Copy>
            This lets you treat history as conditional evidence. If today matches prior risk-off breaks, failed rallies, or rotation squeezes, the app can show how those setups tended to resolve and where the tail-risk profile was most asymmetric.
          </Copy>
        </div>
      </Section>

      <Section title="Narrative" meta="news, earnings, context">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px,1fr))', gap: '18px' }}>
          <Copy>
            The Narrative feature collects recent market news and earnings context, then synthesizes it into a structured summary of what is actually changing today. The design goal is to sound like a portfolio manager who already knows the background regime and is only updating the incremental story.
          </Copy>
          <Copy>
            Instead of treating every headline equally, the pipeline prioritizes novelty, recency, watchlist relevance, and whether the new evidence explains the observed market moves. That keeps the summary closer to “what changed” than “what has been happening for weeks.”
          </Copy>
        </div>
      </Section>

      <Section title="How to read it" meta="practical use">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px,1fr))', gap: '12px' }}>
          {[
            ['State', 'Use the score and environment to establish whether the tape is supportive, fragile, or noisy.'],
            ['Brief', 'Use the daily brief for the high-level macro and cross-asset setup.'],
            ['Memory', 'Use analogue distributions to judge whether the current setup historically rewarded risk-taking.'],
            ['Narrative', 'Use the narrative layer to understand what is newly driving price and where consensus may still be shifting.'],
          ].map(([label, body]) => (
            <div key={label} style={{ border: `0.5px solid ${T.border}`, background: T.sectionBg, padding: '14px 16px' }}>
              <div style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.label, marginBottom: '8px' }}>
                {label}
              </div>
              <div style={{ fontFamily: T.sans, fontSize: '13px', lineHeight: 1.65, color: 'rgba(255,255,255,0.72)' }}>
                {body}
              </div>
            </div>
          ))}
        </div>
      </Section>
    </main>
  );
}
