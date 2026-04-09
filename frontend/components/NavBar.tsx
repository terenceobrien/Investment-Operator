'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const links = [
  { href: '/', label: 'Market State' },
  { href: '/brief', label: 'Daily Brief' },
  { href: '/markets', label: 'Market Data' },
  { href: '/portfolio', label: 'Portfolio' },
  { href: '/narrative', label: 'Narrative' },
  { href: '/how-it-works', label: 'How it works' },
  { href: '/about', label: 'About' },
];

export default function NavBar() {
  const pathname = usePathname();

  return (
    <nav style={{
      position: 'sticky',
      top: 0,
      zIndex: 100,
      background: '#0a0a0a',
      borderBottom: '1px solid #1f1f1f',
      padding: '0 2rem',
      display: 'flex',
      alignItems: 'center',
      gap: '0',
      height: '52px',
    }}>
      {/* Logo */}
      <Link href="/" style={{
        fontSize: '1rem',
        fontWeight: 600,
        color: '#fff',
        textDecoration: 'none',
        marginRight: '2rem',
        flexShrink: 0,
        letterSpacing: '-0.02em',
      }}>
        AI Financial Operator
      </Link>

      {/* Nav links */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0',
        overflowX: 'auto',
        flex: 1,
      }}>
        {links.map(({ href, label }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              style={{
                fontSize: '0.875rem',
                color: active ? '#fff' : '#6b7280',
                textDecoration: 'none',
                padding: '0 1rem',
                height: '52px',
                display: 'flex',
                alignItems: 'center',
                borderBottom: active ? '2px solid #fff' : '2px solid transparent',
                whiteSpace: 'nowrap',
                transition: 'color 0.15s',
              }}
            >
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}