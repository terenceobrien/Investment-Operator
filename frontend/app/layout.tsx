import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import NavBar from '../components/NavBar';
import './globals.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Temper',
  description: 'Quantitative market intelligence for active investors',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body
        className={inter.className}
        style={{ margin: 0, background: '#07070a', color: '#b8b8b4' }}
      >
        <NavBar />
        {children}
      </body>
    </html>
  );
}
