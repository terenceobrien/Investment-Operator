'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { SignInButton, UserButton, useAuth } from '@clerk/nextjs';
import { useEffect, useState } from 'react';
import { T } from '@/lib/tokens';

// ─────────────────────────────────────────────────────────────
// Sidebar navigation.
//
// This is a drop-in replacement for the horizontal NavBar. It keeps every
// existing route and the Clerk auth logic; it only changes the layout from a
// top bar to a fixed left rail (matching the Research OS prototype).
//
// It renders as a fixed-position rail. To make room for it, the app layout
// should add `padding-left: var(--helix-content-pad)` on the main content
// wrapper (see the note in layout.tsx below). The rail sets that CSS var
// itself so you only reference it in one place.
// ─────────────────────────────────────────────────────────────

type NavItem = {
  href: string;
  label: string;
  num?: string;      // ordinal shown on the left, encodes sequence
  external?: boolean;
};

// Primary workspace destinations, in workflow order.
const workspace: NavItem[] = [
  { href: '/macro', label: 'Macro & regime', num: '01' },
  { href: '/narrative', label: 'Narrative engine', num: '02' },
  { href: '/research-cycle', label: 'Research cycle', num: '03' },
  { href: '/portfolio', label: 'Portfolio monitor', num: '04' },
];

// Secondary destinations (kept from the old nav so nothing is lost).
const more: NavItem[] = [
  { href: '/state', label: 'Market state' },
  { href: '/markets', label: 'Prices' },
  { href: '/history', label: 'Market memory' },
  { href: '/strategy', label: 'Custom strategy' },
  { href: '/prediction-markets', label: 'Prediction markets' },
  { href: '/agent-system', label: 'Agent system' },
  { href: '/how-it-works', label: 'Methodology' },
  { href: '/#pricing', label: 'Pricing' },
];

function itemIsActive(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(href + '/');
}

export default function NavBar() {
  const pathname = usePathname();
  const { isSignedIn, isLoaded } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const railStyle: React.CSSProperties = {
    ['--helix-sidebar-w' as string]: T.sidebarWidth,
    position: 'fixed',
    top: 0,
    left: 0,
    bottom: 0,
    width: T.sidebarWidth,
    background: T.railBg,
    borderRight: `1px solid ${T.railBorder}`,
    display: 'flex',
    flexDirection: 'column',
    padding: '26px 20px',
    zIndex: 40,
    transform: mobileOpen ? 'translateX(0)' : undefined,
    fontFamily: T.sans,
  };

  return (
    <>
      {/* Mobile top strip with a menu toggle (rail hides under 900px). */}
      <div style={mobileBarStyle} className="helix-rail-mobilebar">
        <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: '10px', textDecoration: 'none' }}>
          <span style={brandMarkStyle}>H</span>
          <span style={{ color: T.railActive, fontWeight: 700, letterSpacing: '0.14em', fontSize: '14px' }}>HELIX</span>
        </Link>
        <button
          type="button"
          onClick={() => setMobileOpen((v) => !v)}
          style={mobileToggleStyle}
          aria-expanded={mobileOpen}
        >
          Menu
        </button>
      </div>

      <nav style={railStyle} className="helix-rail" aria-label="Primary">
        {/* Brand */}
        <Link
          href="/"
          style={{ display: 'flex', alignItems: 'center', gap: '13px', textDecoration: 'none', marginBottom: '40px' }}
          aria-label="Helix home"
        >
          <span style={brandMarkStyle}>H</span>
          <span>
            <span style={{ display: 'block', color: T.railActive, fontWeight: 700, letterSpacing: '0.18em', fontSize: '15px' }}>
              HELIX
            </span>
            <span style={{ display: 'block', color: T.railTextDim, fontSize: '10.5px', letterSpacing: '0.22em', marginTop: '3px' }}>
              RESEARCH OS
            </span>
          </span>
        </Link>

        <div style={railLabelStyle}>WORKSPACE</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {workspace.map((item) => {
            const active = itemIsActive(pathname, item.href);
            return (
              <Link key={item.href} href={item.href} style={railItemStyle(active)}>
                <span style={{ fontFamily: T.mono, fontSize: '12px', color: active ? T.railAccent : T.railTextDim }}>
                  {item.num}
                </span>
                {item.label}
              </Link>
            );
          })}
        </div>

        <div style={{ height: '1px', background: T.railBorder, margin: '26px 0' }} />

        <div style={railLabelStyle}>MORE</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
          {more.map((item) => {
            const active = itemIsActive(pathname, item.href);
            return (
              <Link key={item.label + item.href} href={item.href} style={railSubItemStyle(active)}>
                {item.label}
              </Link>
            );
          })}
        </div>

        {/* Footer: auth + status */}
        <div style={{ marginTop: 'auto', paddingTop: '22px' }}>
          {isLoaded && !isSignedIn && (
            <SignInButton mode="modal">
              <button type="button" style={signInStyle}>Sign in</button>
            </SignInButton>
          )}
          {isLoaded && isSignedIn && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
              <UserButton
                appearance={{
                  elements: {
                    avatarBox: { width: '32px', height: '32px', border: '1px solid rgba(79,163,165,0.35)' },
                  },
                }}
              />
              <span style={{ color: T.railTextDim, fontSize: '12px' }}>Account</span>
            </div>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: '9px', color: T.railTextDim, fontSize: '11px', letterSpacing: '0.12em', fontWeight: 600 }}>
            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: T.up, boxShadow: '0 0 0 3px rgba(22,138,90,0.18)' }} />
            DATA SYNCED
          </div>
        </div>
      </nav>

      {/* Backdrop for mobile drawer */}
      {mobileOpen && (
        <div
          onClick={() => setMobileOpen(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(11,31,51,0.4)', zIndex: 39 }}
          className="helix-rail-backdrop"
        />
      )}

      {/* Rail behavior: fixed on desktop, off-canvas drawer on mobile. */}
      <style>{`
        @media (max-width: 900px) {
          .helix-rail { transform: translateX(-100%); transition: transform 0.2s ease; box-shadow: 0 24px 60px rgba(11,31,51,0.5); }
          .helix-rail[style*="translateX(0)"] { transform: translateX(0) !important; }
        }
        @media (min-width: 901px) {
          .helix-rail-mobilebar, .helix-rail-backdrop { display: none !important; }
        }
      `}</style>
    </>
  );
}

// ── styles ──────────────────────────────────────────────────
const brandMarkStyle: React.CSSProperties = {
  width: '42px',
  height: '42px',
  borderRadius: '50%',
  border: `1.5px solid ${T.railBorder}`,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: T.railAccent,
  fontFamily: 'Georgia, serif',
  fontSize: '19px',
  flexShrink: 0,
};

const railLabelStyle: React.CSSProperties = {
  fontSize: '10.5px',
  letterSpacing: '0.24em',
  color: T.railTextDim,
  fontWeight: 600,
  marginBottom: '14px',
};

function railItemStyle(active: boolean): React.CSSProperties {
  return {
    display: 'flex',
    alignItems: 'center',
    gap: '14px',
    padding: '12px 14px',
    borderRadius: '11px',
    fontSize: '14.5px',
    fontWeight: 500,
    textDecoration: 'none',
    color: active ? T.railActive : T.railText,
    background: active ? T.railBgElev : 'transparent',
    border: `1px solid ${active ? T.railAccent : 'transparent'}`,
    boxShadow: active ? `0 0 0 1px ${T.railAccent}, 0 10px 28px -14px rgba(79,163,165,0.6)` : undefined,
  };
}

function railSubItemStyle(active: boolean): React.CSSProperties {
  return {
    display: 'block',
    padding: '9px 14px',
    borderRadius: '9px',
    fontSize: '13.5px',
    fontWeight: 500,
    textDecoration: 'none',
    color: active ? T.railActive : T.railTextDim,
    background: active ? T.railBgElev : 'transparent',
  };
}

const signInStyle: React.CSSProperties = {
  width: '100%',
  background: T.railAccent,
  color: '#04121F',
  border: 'none',
  borderRadius: '10px',
  padding: '10px 0',
  fontFamily: T.sans,
  fontSize: '13px',
  fontWeight: 700,
  cursor: 'pointer',
  marginBottom: '16px',
};

const mobileBarStyle: React.CSSProperties = {
  position: 'sticky',
  top: 0,
  zIndex: 41,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '12px 18px',
  background: T.railBg,
  borderBottom: `1px solid ${T.railBorder}`,
};

const mobileToggleStyle: React.CSSProperties = {
  background: 'transparent',
  color: T.railText,
  border: `1px solid ${T.railBorder}`,
  borderRadius: '8px',
  padding: '7px 14px',
  fontSize: '13px',
  fontWeight: 600,
  cursor: 'pointer',
};
