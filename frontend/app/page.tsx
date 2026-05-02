import Link from 'next/link';
import type { ReactNode } from 'react';

const Icon = ({ children }: { children: ReactNode }) => (
  <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
);

function ValueIcon({ type }: { type: 'book' | 'trend' | 'target' | 'doc' | 'brain' | 'eye' | 'database' | 'shield' | 'shieldCheck' }) {
  const paths = {
    shield: (
      <>
        <path d="M12 3 4.5 6v6c0 4.5 3 8.4 7.5 9.5 4.5-1.1 7.5-5 7.5-9.5V6L12 3Z" />
      </>
    ),
    shieldCheck: (
      <>
        <path d="M12 3 4.5 6v6c0 4.5 3 8.4 7.5 9.5 4.5-1.1 7.5-5 7.5-9.5V6L12 3Z" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
    book: (
      <>
        <path d="M4 5.5c2.6 0 4.6.6 6 1.8v11.2c-1.4-1.2-3.4-1.8-6-1.8V5.5Z" />
        <path d="M20 5.5c-2.6 0-4.6.6-6 1.8v11.2c1.4-1.2 3.4-1.8 6-1.8V5.5Z" />
      </>
    ),
    trend: (
      <>
        <path d="M4 18V6" />
        <path d="M4 18h16" />
        <path d="m7 15 4-5 3 3 5-7" />
        <path d="M16 6h3v3" />
      </>
    ),
    target: (
      <>
        <circle cx="12" cy="12" r="7" />
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v3" />
        <path d="M12 19v3" />
        <path d="M2 12h3" />
        <path d="M19 12h3" />
      </>
    ),
    doc: (
      <>
        <path d="M7 3h7l4 4v14H7V3Z" />
        <path d="M14 3v5h5" />
        <path d="M9.5 12h5" />
        <path d="M9.5 16h6.5" />
      </>
    ),
    brain: (
      <>
        <path d="M9 5.5a3 3 0 0 0-4 2.8 3.1 3.1 0 0 0 1 2.3 3.4 3.4 0 0 0 0 5.7A3.2 3.2 0 0 0 9 20" />
        <path d="M15 5.5a3 3 0 0 1 4 2.8 3.1 3.1 0 0 1-1 2.3 3.4 3.4 0 0 1 0 5.7A3.2 3.2 0 0 1 15 20" />
        <path d="M9 5.5V20" />
        <path d="M15 5.5V20" />
        <path d="M9 11h6" />
      </>
    ),
    eye: (
      <>
        <path d="M2.5 12s3.4-6 9.5-6 9.5 6 9.5 6-3.4 6-9.5 6-9.5-6-9.5-6Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
    database: (
      <>
        <ellipse cx="12" cy="5" rx="7" ry="3" />
        <path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5" />
        <path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
      </>
    ),
  };

  return <Icon>{paths[type]}</Icon>;
}

function ProductPreview() {
  return (
    <div className="helix-preview" aria-label="Static Helix product preview">
      <div className="helix-preview-topbar">
        <div className="helix-preview-id">
          <span className="helix-brand-mark">H</span>
          <strong>AAPL</strong>
          <small>Apple Inc.</small>
          <span aria-hidden="true">☆</span>
        </div>
        <div className="helix-preview-controls">
          <span className="helix-preview-pill">3M ▾</span>
          <span className="helix-preview-pill">Add to Watchlist</span>
        </div>
      </div>

      <div className="helix-preview-grid">
        <article className="helix-preview-card">
          <div className="helix-preview-card-header">
            <h3>Narrative Snapshot</h3>
            <span className="helix-preview-badge">Current Regime</span>
          </div>
          <p className="helix-narrative-stage">
            Early Optimism<br />Growth Re-acceleration
          </p>
          <svg className="helix-cycle" viewBox="0 0 240 120" fill="none">
            <path d="M20 96 C48 38, 92 22, 124 38 C158 55, 174 100, 222 96" stroke="#D8DEE6" strokeWidth="3" />
            {[
              [20, 96, '#2F7F82'], [50, 62, '#E7F4F4'], [84, 38, '#E7F4F4'],
              [118, 35, '#4FA3A5'], [152, 51, '#E7F4F4'], [176, 76, '#F5E8CF'],
              [194, 96, '#F5E8CF'], [218, 98, '#F7D8D8'],
            ].map(([cx, cy, fill], idx) => (
              <circle key={idx} cx={cx} cy={cy} r="8" fill={String(fill)} stroke="#2F7F82" strokeWidth={idx === 0 || idx === 3 ? 2 : 1} />
            ))}
            <text x="18" y="113" fill="#102033" fontSize="10">Optimism</text>
            <text x="98" y="20" fill="#5B6678" fontSize="10">Euphoria</text>
            <text x="182" y="113" fill="#5B6678" fontSize="10">Fear</text>
          </svg>
          <p className="helix-preview-note">
            Narrative is in Early Optimism. Participation broadening with improving fundamentals and renewed inflows.
          </p>
          <a href="#" className="helix-preview-link">View full cycle ›</a>
        </article>

        <article className="helix-preview-card">
          <div className="helix-preview-card-header">
            <h3>Evidence Board</h3>
            <span className="helix-preview-link">View all</span>
          </div>
          <div className="helix-evidence-list">
            {[
              ['News & Research', 'Earnings beat, AI features, services growth.', 24],
              ['Company Filings', 'Strong FCF, margin expansion, share repurchases.', 8],
              ['Sentiment & Flows', 'Analyst upgrades and positive revisions.', 15],
            ].map(([title, body, count]) => (
              <div className="helix-evidence-item" key={String(title)}>
                <span className="helix-evidence-icon">⌁</span>
                <span>
                  <span className="helix-evidence-title">{title}</span>
                  <span className="helix-evidence-body">{body}</span>
                </span>
                <span className="helix-evidence-count">{count} •</span>
              </div>
            ))}
          </div>
          <a href="#" className="helix-preview-link helix-preview-footer-link">Open Evidence Board ›</a>
        </article>

        <article className="helix-preview-card">
          <div className="helix-preview-card-header">
            <h3>Price &amp; Timeframe</h3>
            <span className="helix-preview-link">View chart</span>
          </div>
          <div className="helix-price-value">
            <strong>$183.42</strong>
            <span>+4.21 (+2.35%)</span>
          </div>
          <small style={{ color: 'var(--text-subtle)' }}>As of May 2, 2026 4:00 PM ET</small>
          <svg className="helix-spark" viewBox="0 0 260 96" fill="none">
            <path d="M0 74 C16 58, 25 48, 40 51 C58 55, 63 32, 80 37 C98 43, 103 30, 120 35 C137 40, 145 28, 160 33 C179 40, 178 62, 195 58 C212 54, 213 34, 231 31 C243 29, 250 20, 260 16" stroke="#4FA3A5" strokeWidth="3" />
            <path d="M0 74 C16 58, 25 48, 40 51 C58 55, 63 32, 80 37 C98 43, 103 30, 120 35 C137 40, 145 28, 160 33 C179 40, 178 62, 195 58 C212 54, 213 34, 231 31 C243 29, 250 20, 260 16 L260 96 L0 96Z" fill="url(#sparkFill)" />
            <defs>
              <linearGradient id="sparkFill" x1="130" y1="16" x2="130" y2="96" gradientUnits="userSpaceOnUse">
                <stop stopColor="#4FA3A5" stopOpacity="0.18" />
                <stop offset="1" stopColor="#4FA3A5" stopOpacity="0" />
              </linearGradient>
            </defs>
          </svg>
          <div className="helix-price-metrics">
            <div><span>Trend</span><strong style={{ color: 'var(--positive)' }}>Up ↗</strong></div>
            <div><span>Volatility (20D)</span><strong>22.6%</strong></div>
            <div><span>52W Range</span><strong>$142.11 – $199.62</strong></div>
            <div><span>Market Cap</span><strong>$2.82T</strong></div>
          </div>
          <a href="#" className="helix-preview-link helix-preview-footer-link">Open Price Context ›</a>
        </article>
      </div>
    </div>
  );
}

export default function HomePage() {
  return (
    <main className="helix-home">
      <div className="helix-home-container">
        <section className="helix-hero">
          <div>
            <span className="helix-chip">Narrative + Price Intelligence</span>
            <h1 className="helix-hero-title">
              <span>A new layer of</span>
              <span>market understanding</span>
            </h1>
            <p className="helix-hero-copy">
              Helix transforms information overload into a structured view of market narratives, price evolution, and
              potential inefficiencies — for any stock, sector, or theme.
            </p>
            <div className="helix-hero-actions">
              <Link href="/narrative" className="helix-button-primary">Explore Helix</Link>
              <Link href="/how-it-works" className="helix-button-secondary">
                See How it Works
                <span className="helix-button-play" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="currentColor" stroke="none">
                    <path d="M8 5v14l11-7L8 5Z" />
                  </svg>
                </span>
              </Link>
            </div>
            <div className="helix-trust-row">
              <div className="helix-trust-item">
                <span className="helix-trust-icon"><ValueIcon type="database" /></span>
                <span>Institutional-grade sources</span>
              </div>
              <div className="helix-trust-item">
                <span className="helix-trust-icon"><ValueIcon type="eye" /></span>
                <span>Transparent methodology</span>
              </div>
              <div className="helix-trust-item">
                <span className="helix-trust-icon"><ValueIcon type="target" /></span>
                <span>Designed for active research</span>
              </div>
            </div>
          </div>
          <ProductPreview />
        </section>

        <section className="helix-value-strip" aria-label="Helix value pillars">
          {[
            ['Understand the Narrative', 'See the market story, its stage in the cycle, and the evidence shaping it.', 'book'],
            ['See How Price is Responding', 'Track price, flows, and sentiment across key timeframes and events.', 'trend'],
            ['Spot Possible Inefficiencies', 'Identify gaps between narrative, fundamentals, and price action.', 'target'],
          ].map(([title, body, icon]) => (
            <article className="helix-value-card" key={title}>
              <span className="helix-value-icon"><ValueIcon type={icon as 'book' | 'trend' | 'target'} /></span>
              <div>
                <h2>{title}</h2>
                <p>{body}</p>
              </div>
            </article>
          ))}
        </section>

        <section className="helix-workflow">
          <h2 className="helix-section-title">A repeatable framework for better decisions</h2>
          <div className="helix-workflow-grid">
            {[
              ['Inputs', 'We aggregate signals across news, filings, sentiment, flows, and price action.', 'database'],
              ['Evidence', 'Helix organizes what matters, separating signal from noise.', 'doc'],
              ['Interpretation', 'Our models map the narrative cycle, explain price behavior, and highlight drivers.', 'brain'],
              ['Watchpoints', 'We surface key risks, catalysts, and invalidation levels to monitor.', 'eye'],
            ].map(([title, body, icon], idx) => (
              <article className="helix-step" key={title}>
                <span className="helix-step-number">{idx + 1}</span>
                <span className="helix-workflow-icon"><ValueIcon type={icon as 'database' | 'doc' | 'brain' | 'eye'} /></span>
                <div>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="helix-feature-grid" id="pricing">
          {[
            ['Narrative Map', 'See the full landscape of market narratives and how they evolve over time.', 'book'],
            ['Price Confirmation', 'Validate narratives with real price behavior across multiple timeframes.', 'trend'],
            ['Inefficiency Detection', 'Identify gaps between beliefs and price that may create opportunity.', 'target'],
            ['Cycle Positioning', 'Understand where a stock or theme may sit in the expectation cycle.', 'brain'],
          ].map(([title, body, icon]) => (
            <article className="helix-feature-card" key={title}>
              <span className="helix-feature-icon"><ValueIcon type={icon as 'book' | 'trend' | 'target' | 'brain'} /></span>
              <h3>{title}</h3>
              <p>{body}</p>
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}
