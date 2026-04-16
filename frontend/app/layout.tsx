import type { Metadata } from 'next';
import NavBar from '../components/NavBar';
import { T } from '@/lib/tokens';
import './globals.css';

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
    images: [
      {
        url: '/og-temper.svg',
        width: 1200,
        height: 630,
        alt: 'Helix',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Helix',
    description: 'Quantitative market intelligence for active investors',
    images: ['/og-temper.svg'],
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        style={{ margin: 0, background: T.bg, color: T.text }}
      >
        <NavBar />
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
          Helix is for informational purposes only and does not constitute financial advice. Not affiliated with any broker or financial institution.
        </footer>
      </body>
    </html>
  );
}
