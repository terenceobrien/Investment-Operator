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

// Clerk appearance — matches the light Helix product system.
// Uses only the `variables` and `elements` APIs (no @clerk/themes package needed).
const clerkAppearance = {
  variables: {
    colorPrimary:        '#4FA3A5',
    colorBackground:     '#FFFFFF',
    colorInputBackground:'#F8FAFB',
    colorInputText:      '#102033',
    colorText:           '#102033',
    colorTextSecondary:  '#5B6678',
    colorNeutral:        '#7B8798',
    colorDanger:         '#C94A4A',
    colorSuccess:        '#168A5A',
    colorShimmer:        'rgba(79,163,165,0.12)',
    borderRadius:        '12px',
    fontFamily:          'Inter, system-ui, sans-serif',
    fontSize:            '13px',
  },
  elements: {
    // Outer card
    card: {
      background:  '#FFFFFF',
      border:      '1px solid #D8DEE6',
      boxShadow:   '0 18px 50px rgba(15,31,51,0.12)',
    },
    // Modal backdrop
    modalBackdrop: {
      background: 'rgba(11,31,51,0.34)',
      backdropFilter: 'blur(4px)',
    },
    // Header
    headerTitle: {
      color:       '#0B1F33',
      fontWeight:  '500',
      letterSpacing: '0.5px',
    },
    headerSubtitle: {
      color: '#5B6678',
    },
    // Form inputs
    formFieldInput: {
      background:  '#F8FAFB',
      border:      '1px solid #D8DEE6',
      color:       '#102033',
      outline:     'none',
    },
    formFieldLabel: {
      color:       '#5B6678',
      fontSize:    '11px',
      letterSpacing: '0.8px',
      textTransform: 'uppercase',
    },
    // Primary button (Sign in / Continue)
    formButtonPrimary: {
      background:  '#0B1F33',
      border:      '1px solid #0B1F33',
      color:       '#FFFFFF',
      fontFamily:  'Inter, system-ui, sans-serif',
      letterSpacing: '0.8px',
      textTransform: 'uppercase',
      fontSize:    '11px',
    },
    // Social / OAuth buttons
    socialButtonsBlockButton: {
      background:  '#FFFFFF',
      border:      '1px solid #D8DEE6',
      color:       '#102033',
    },
    socialButtonsBlockButtonText: {
      color:       '#102033',
    },
    // Divider
    dividerLine: {
      background:  '#E8EDF2',
    },
    dividerText: {
      color:       '#7B8798',
    },
    // Footer links
    footerActionLink: {
      color:       '#2F7F82',
    },
    footer: {
      background:  '#FFFFFF',
    },
    // Internal nav links
    identityPreviewEditButton: {
      color:       '#2F7F82',
    },
  },
} as const;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider appearance={clerkAppearance}>
      <html lang="en">
        <body style={{ margin: 0, background: T.pageBg, color: T.text }}>
          <AppShell>
            <div className="temper-page-shell" style={{ minHeight: '100vh' }}>
              {children}
            </div>
            <footer
              style={{
                borderTop: `0.5px solid ${T.border}`,
                background: 'rgba(255,255,255,0.78)',
                padding: '22px 24px 24px',
                fontFamily: T.mono,
                fontSize: '11px',
                fontWeight: 300,
                letterSpacing: '0.3px',
                color: T.textMuted,
                textAlign: 'center',
              }}
            >
              <div>
                <strong style={{ color: T.text, fontFamily: T.sans, letterSpacing: '0.16em', textTransform: 'uppercase' }}>Helix</strong>
                {' '}is for informational purposes only and does not constitute financial advice.{' '}
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
