'use client';

import { SignInButton } from '@clerk/nextjs';
import { T, sx } from '@/lib/tokens';

export default function AuthRequired({ isLoaded }: { isLoaded: boolean }) {
  return (
    <main style={sx.main}>
      <div style={sx.pageShell}>
        <section
          style={{
            ...sx.panel,
            minHeight: '320px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            padding: '48px 24px',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '14px' }}>
            <span
              style={{
                fontFamily: T.sans,
                fontSize: '12px',
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: T.textMuted,
                fontWeight: 650,
              }}
            >
              {isLoaded ? 'Sign in required' : 'Loading session'}
            </span>
            <p
              style={{
                margin: 0,
                maxWidth: '460px',
                fontFamily: T.sans,
                fontSize: '15px',
                lineHeight: 1.6,
                color: T.textSub,
              }}
            >
              {isLoaded
                ? 'Sign in to view live Helix market intelligence.'
                : 'Checking your Helix session before loading protected data.'}
            </p>
            {isLoaded ? (
              <SignInButton mode="modal">
                <button
                  style={{
                    marginTop: '4px',
                    border: 'none',
                    borderRadius: '12px',
                    background: T.navy,
                    color: '#fff',
                    padding: '10px 18px',
                    fontFamily: T.sans,
                    fontSize: '13px',
                    fontWeight: 650,
                    cursor: 'pointer',
                  }}
                >
                  Sign in
                </button>
              </SignInButton>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
