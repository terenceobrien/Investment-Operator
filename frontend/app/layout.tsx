import type { Metadata } from 'next';
import { Geist } from 'next/font/google';
import NavBar from '../components/NavBar';
import './globals.css';

const geist = Geist({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'AI Financial Operator',
  description: 'Quantitative market intelligence for active investors',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={geist.className} style={{ margin: 0, background: '#0a0a0a', color: '#fff' }}>
        <NavBar />
        {children}
      </body>
    </html>
  );
}