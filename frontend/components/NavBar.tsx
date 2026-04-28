'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { SignInButton, UserButton, useAuth } from '@clerk/nextjs';
import { T } from '@/lib/tokens';

const links = [
  { href: '/',          label: 'Home' },
  { href: '/state',     label: 'State' },
  { href: '/markets',   label: 'Prices' },
  { href: '/narrative', label: 'Narrative' },
  { href: '/prediction-markets', label: 'Narrative Insights' },
  { href: '/history',   label: 'Memory' },
  { href: '/portfolio', label: 'Portfolio' },
  { href: '/strategy', label: 'Custom Strategy' },
  { href: '/how-it-works', label: 'How it works' },
];

export default function NavBar() {
  const pathname = usePathname();
  const { isSignedIn, isLoaded } = useAuth();

  return (
    <nav style={{
      position: 'sticky',
      top: 0,
      zIndex: 100,
      background: T.bg,
      borderBottom: `1px solid rgba(255,255,255,0.09)`,
      boxShadow: '0 4px 28px rgba(0,0,0,0.72)',
      padding: '0 20px',
      display: 'flex',
      alignItems: 'center',
      gap: '16px',
      minHeight: '56px',
      overflowX: 'auto',
      scrollbarWidth: 'none',
    }}>

      {/* Logo */}
      <Link href="/" style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        gap: '11px',
        textDecoration: 'none',
        flexShrink: 0,
        marginRight: '4px',
      }}>
        {/* Glow bloom */}
        <div style={{
          position: 'absolute',
          left: '-52px',
          top: '50%',
          transform: 'translateY(-50%)',
          width: '140px',
          height: '140px',
          background: 'radial-gradient(circle, rgba(149,128,212,0.14) 0%, rgba(149,128,212,0.04) 45%, transparent 72%)',
          pointerEvents: 'none',
          zIndex: 0,
        }} />
        {/* Logo mark — H monogram */}
        <div style={{
          position: 'relative',
          zIndex: 1,
          width: '28px',
          height: '28px',
          border: `1px solid rgba(149,128,212,0.38)`,
          background: 'rgba(149,128,212,0.08)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}>
          <span style={{
            fontFamily: T.mono,
            fontSize: '15px',
            fontWeight: 500,
            color: 'rgba(255,255,255,0.93)',
            lineHeight: 1,
          }}>H</span>
        </div>
        {/* Wordmark */}
        <span style={{
          position: 'relative',
          zIndex: 1,
          fontFamily: T.sans,
          fontSize: '16px',
          fontWeight: 600,
          letterSpacing: '5px',
          textTransform: 'uppercase',
          color: 'rgba(255,255,255,0.88)',
        }}>
          Helix
        </span>
      </Link>

      {/* Nav links — centered */}
      <div style={{
        display: 'flex',
        alignItems: 'stretch',
        flex: 1,
        justifyContent: 'center',
        height: '100%',
        minWidth: 0,
        overflowX: 'auto',
        scrollbarWidth: 'none',
      }}>
        {links.map(({ href, label }, i) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              style={{
                fontFamily: T.sans,
                fontSize: '11.5px',
                letterSpacing: '1.2px',
                textTransform: 'uppercase',
                color: active ? 'rgba(149,128,212,0.95)' : 'rgba(255,255,255,0.46)',
                textDecoration: 'none',
                padding: '0 14px',
                display: 'flex',
                alignItems: 'center',
                background: active ? 'rgba(149,128,212,0.06)' : 'transparent',
                boxShadow: active ? 'inset 0 -2px 0 rgba(149,128,212,0.55)' : 'none',
                borderRight: `0.5px solid rgba(255,255,255,0.06)`,
                borderLeft: i === 0 ? `0.5px solid rgba(255,255,255,0.06)` : 'none',
                whiteSpace: 'nowrap',
                fontWeight: active ? 500 : 400,
                transition: 'color 0.12s, background 0.12s',
                flexShrink: 0,
              }}
            >
              {label}
            </Link>
          );
        })}
      </div>

      {/* Right: date + live indicator + auth */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexShrink: 0 }}>
        <span style={{
          fontFamily: T.mono,
          fontSize: '12px',
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
          fontSize: '11px',
          letterSpacing: '1.2px',
          textTransform: 'uppercase',
          color: 'rgba(100,185,120,0.8)',
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

        {/* Auth — sign in button or user avatar */}
        {isLoaded && !isSignedIn && (
          <SignInButton mode="modal">
            <button style={{
              fontFamily: T.sans,
              fontSize: '11px',
              letterSpacing: '1.2px',
              textTransform: 'uppercase',
              color: 'rgba(255,255,255,0.55)',
              background: 'transparent',
              border: '0.5px solid rgba(255,255,255,0.14)',
              padding: '5px 14px',
              cursor: 'pointer',
              fontWeight: 400,
              whiteSpace: 'nowrap',
            }}>
              Sign In
            </button>
          </SignInButton>
        )}

        {isLoaded && isSignedIn && (
          <UserButton
            appearance={{
              elements: {
                avatarBox: {
                  width: '26px',
                  height: '26px',
                  border: '0.5px solid rgba(149,128,212,0.35)',
                },
              },
            }}
          />
        )}
      </div>

    </nav>
  );
}
