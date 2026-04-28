import type { Metadata } from 'next';
import AppShell from '../components/AppShell';
import { T } from '@/lib/tokens';
import './globals.css';
import { ClerkProvider } from '@clerk/nextjs';

export const metadata: Metadata = {
  title: 'Helix',
  description: 'Quantitative market intelligence for active investors',
  icons: {
    icon: '/temper-favicon.svg',
    shortcut: '/temper-favicon.svg',
    apple: '/temper-favicon.svg',
  },
  openGraph: {
    title: 'Helix',
    description: 'Quantitative market intelligence for active investors',
    images: [{ url: '/og-temper.svg', width: 1200, height: 630, alt: 'Helix' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Helix',
    description: 'Quantitative market intelligence for active investors',
    images: ['/og-temper.svg'],
  },
};

// Clerk appearance — matches the dark terminal UI of the rest of the app.
// Uses only the `variables` and `elements` APIs (no @clerk/themes package needed).
const clerkAppearance = {
  variables: {
    colorPrimary:        '#9580d4',
    colorBackground:     '#0a0a10',
    colorInputBackground:'#111118',
    colorInputText:      'rgba(255,255,255,0.85)',
    colorText:           'rgba(255,255,255,0.85)',
    colorTextSecondary:  'rgba(255,255,255,0.42)',
    colorNeutral:        'rgba(255,255,255,0.42)',
    colorDanger:         '#e05555',
    colorSuccess:        '#4caf89',
    colorShimmer:        'rgba(149,128,212,0.12)',
    borderRadius:        '2px',
    fontFamily:          'Inter, system-ui, sans-serif',
    fontSize:            '13px',
  },
  elements: {
    // Outer card
    card: {
      background:  '#0a0a10',
      border:      '0.5px solid rgba(255,255,255,0.09)',
      boxShadow:   '0 24px 64px rgba(0,0,0,0.82)',
    },
    // Modal backdrop
    modalBackdrop: {
      background: 'rgba(0,0,0,0.72)',
      backdropFilter: 'blur(4px)',
    },
    // Header
    headerTitle: {
      color:       'rgba(255,255,255,0.88)',
      fontWeight:  '500',
      letterSpacing: '0.5px',
    },
    headerSubtitle: {
      color: 'rgba(255,255,255,0.42)',
    },
    // Form inputs
    formFieldInput: {
      background:  '#111118',
      border:      '0.5px solid rgba(255,255,255,0.12)',
      color:       'rgba(255,255,255,0.85)',
      outline:     'none',
    },
    formFieldLabel: {
      color:       'rgba(255,255,255,0.55)',
      fontSize:    '11px',
      letterSpacing: '0.8px',
      textTransform: 'uppercase',
    },
    // Primary button (Sign in / Continue)
    formButtonPrimary: {
      background:  'rgba(149,128,212,0.18)',
      border:      '0.5px solid rgba(149,128,212,0.45)',
      color:       'rgba(255,255,255,0.9)',
      fontFamily:  'Inter, system-ui, sans-serif',
      letterSpacing: '0.8px',
      textTransform: 'uppercase',
      fontSize:    '11px',
    },
    // Social / OAuth buttons
    socialButtonsBlockButton: {
      background:  '#111118',
      border:      '0.5px solid rgba(255,255,255,0.1)',
      color:       'rgba(255,255,255,0.7)',
    },
    socialButtonsBlockButtonText: {
      color:       'rgba(255,255,255,0.7)',
    },
    // Divider
    dividerLine: {
      background:  'rgba(255,255,255,0.08)',
    },
    dividerText: {
      color:       'rgba(255,255,255,0.3)',
    },
    // Footer links
    footerActionLink: {
      color:       '#9580d4',
    },
    footer: {
      background:  '#0a0a10',
    },
    // Internal nav links
    identityPreviewEditButton: {
      color:       '#9580d4',
    },
  },
} as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider appearance={clerkAppearance}>
      <html lang="en">
        <body style={{ margin: 0, background: T.pageBg, color: T.text }}>
          <AppShell>
            <div className="temper-page-shell" style={{ minHeight: 'calc(100vh - 88px)' }}>
              {children}
            </div>
            <footer
              style={{
                borderTop: `0.5px solid ${T.border}`,
                padding: '10px 24px 14px',
                fontFamily: T.mono,
                fontSize: '10px',
                fontWeight: 300,
                letterSpacing: '0.3px',
                color: T.textMuted,
                textAlign: 'center',
              }}
            >
              <div>
                Helix is for informational purposes only and does not constitute financial advice. Not affiliated with any broker or financial institution.{' '}
                <a href="/legal/helix_privacy_policy.docx" target="_blank" rel="noreferrer" style={{ color: T.textMuted, textDecoration: 'underline' }}>
                  Privacy Policy
                </a>{' '}
                ·{' '}
                <a href="/legal/helix_terms_of_service.docx" target="_blank" rel="noreferrer" style={{ color: T.textMuted, textDecoration: 'underline' }}>
                  Terms of Service
                </a>
              </div>
              <div style={{ marginTop: '4px' }}>
                Past performance does not guarantee future results.
              </div>
            </footer>
          </AppShell>
        </body>
      </html>
    </ClerkProvider>
  );
}