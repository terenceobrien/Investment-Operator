'use client';

import { T, sx } from '@/lib/tokens';
import { useAuthFetcher } from '../../lib/api';

export default function MacroPage() {
  const authFetcher = useAuthFetcher();
  return (
    <main style={sx.main}>
      <div style={sx.pageShell}>
        <div
          style={{
            padding: '64px 24px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <span
            style={{
              fontFamily: T.sans,
              fontSize: '11px',
              letterSpacing: '1.6px',
              textTransform: 'uppercase',
              color: T.textMuted,
            }}
          >
            Content moved
          </span>
          <p
            style={{
              fontFamily: T.sans,
              fontSize: '14px',
              color: T.textSub,
              margin: 0,
              textAlign: 'center',
            }}
          >
            Themes and macro regime are now on the{' '}
            <a href="/state" style={{ color: T.accent, textDecoration: 'none' }}>
              State
            </a>{' '}
            page.
          </p>
        </div>
      </div>
    </main>
  );
}
