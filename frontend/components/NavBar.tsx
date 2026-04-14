'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { T } from '@/lib/tokens';

const links = [
  { href: '/',          label: 'State' },
  { href: '/brief',     label: 'Brief' },
  { href: '/markets',   label: 'Markets' },
  { href: '/portfolio', label: 'Portfolio' },
  { href: '/narrative', label: 'Narrative' },
  { href: '/history',   label: 'Memory' },
];

export default function NavBar() {
  const pathname = usePathname();

  return (
    <nav style={{
      position: 'sticky',
      top: 0,
      zIndex: 100,
      background: T.bg,
      borderBottom: `0.5px solid ${T.border}`,
      padding: '0 24px',
      display: 'flex',
      alignItems: 'center',
      height: '44px',
    }}>

      {/* Logo */}
      <Link href="/" style={{
        display: 'flex',
        alignItems: 'center',
        gap: '9px',
        textDecoration: 'none',
        flexShrink: 0,
        marginRight: '0',
      }}>
        {/* Logo mark — T in a box */}
        <div style={{
          width: '22px',
          height: '22px',
          border: `0.5px solid rgba(255,255,255,0.2)`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}>
          <span style={{
            fontFamily: T.mono,
            fontSize: '11px',
            fontWeight: 400,
            color: 'rgba(255,255,255,0.8)',
            lineHeight: 1,
          }}>T</span>
        </div>
        {/* Wordmark */}
        <span style={{
          fontFamily: T.sans,
          fontSize: '12px',
          fontWeight: 500,
          letterSpacing: '3px',
          textTransform: 'uppercase',
          color: 'rgba(255,255,255,0.7)',
        }}>
          Temper
        </span>
      </Link>

      {/* Nav links — centered */}
      <div style={{
        display: 'flex',
        alignItems: 'stretch',
        flex: 1,
        justifyContent: 'center',
        height: '100%',
      }}>
        {links.map(({ href, label }, i) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              style={{
                fontFamily: T.sans,
                fontSize: '10px',
                letterSpacing: '1.2px',
                textTransform: 'uppercase',
                color: active ? 'rgba(255,255,255,0.75)' : 'rgba(255,255,255,0.22)',
                textDecoration: 'none',
                padding: '0 13px',
                display: 'flex',
                alignItems: 'center',
                background: active ? 'rgba(255,255,255,0.04)' : 'transparent',
                borderRight: `0.5px solid ${T.border}`,
                borderLeft: i === 0 ? `0.5px solid ${T.border}` : 'none',
                whiteSpace: 'nowrap',
                fontWeight: active ? 500 : 400,
                transition: 'color 0.12s',
              }}
            >
              {label}
            </Link>
          );
        })}
      </div>

      {/* Right: date + live indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexShrink: 0 }}>
        <span style={{
          fontFamily: T.mono,
          fontSize: '10px',
          fontWeight: 300,
          letterSpacing: '0.5px',
          color: T.textMuted,
        }}>
          {new Date().toISOString().slice(0, 10)}
        </span>
        <span style={{
          display: 'flex',
          alignItems: 'center',
          gap: '5px',
          fontFamily: T.sans,
          fontSize: '9px',
          letterSpacing: '1.2px',
          textTransform: 'uppercase',
          color: 'rgba(100,185,120,0.65)',
          fontWeight: 400,
        }}>
          <span style={{
            width: '4px',
            height: '4px',
            borderRadius: '50%',
            background: '#64b978',
            display: 'inline-block',
          }} />
          Live
        </span>
      </div>

    </nav>
  );
}