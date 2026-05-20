'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { SignInButton, UserButton, useAuth } from '@clerk/nextjs';
import { useEffect, useRef, useState } from 'react';

type MenuLink = {
  href: string;
  label: string;
  description?: string;
};

const productLinks: MenuLink[] = [
  { href: '/', label: 'Overview', description: 'Helix home and product preview' },
  { href: '/narrative', label: 'Narrative Engine', description: 'Reality, story, price, and gaps' },
  { href: '/state', label: 'Market State', description: 'Regime score and signal layers' },
  { href: '/markets', label: 'Prices', description: 'Ticker context and sector behavior' },
  { href: '/portfolio', label: 'Portfolio', description: 'Position and concentration snapshot' },
  { href: '/history', label: 'Memory', description: 'Historical analogues and forward paths' },
];

const featureLinks: MenuLink[] = [
  { href: '/narrative', label: 'Narrative Map', description: 'What the market currently believes' },
  { href: '/narrative', label: 'Price Confirmation', description: 'Multi-timeframe validation' },
  { href: '/narrative', label: 'Inefficiency Map', description: 'Gaps between facts, story, and price' },
  { href: '/narrative', label: 'Cycle Positioning', description: 'Expectation cycle and watchpoints' },
  { href: '/history', label: 'Market Memory', description: 'Comparable historical setups' },
  { href: '/strategy', label: 'Custom Strategy', description: 'Backtest configurable regime logic' },
];

const resourceLinks: MenuLink[] = [
  { href: '/prediction-markets', label: 'Narrative Insights', description: 'Prediction-market context' },
  { href: '/agent-system', label: 'Agent System Review', description: 'Internal execution spine audit' },
  { href: '/how-it-works', label: 'Methodology', description: 'How the framework is organized' },
  { href: '/how-it-works', label: 'Disclaimers', description: 'What Helix does and does not claim' },
];

function isActive(pathname: string, links: MenuLink[]) {
  return links.some((link) => pathname === link.href);
}

function NavGroup({
  label,
  links,
  pathname,
}: {
  label: string;
  links: MenuLink[];
  pathname: string;
}) {
  const active = isActive(pathname, links);
  const [open, setOpen] = useState(false);
  const groupRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <div
      ref={groupRef}
      className={`helix-nav-group${open ? ' helix-nav-group-open' : ''}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onBlur={(event) => {
        if (!groupRef.current?.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
        }
      }}
    >
      <button
        className={`helix-nav-trigger${active ? ' helix-nav-trigger-active' : ''}`}
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onFocus={() => setOpen(true)}
      >
        {label}
        <span className="helix-nav-chevron">⌄</span>
      </button>
      <div
        className="helix-nav-menu"
        style={open ? { opacity: 1, pointerEvents: 'auto', transform: 'translateX(-50%) translateY(0)' } : undefined}
      >
        {links.map((link) => (
          <Link
            key={`${label}-${link.label}`}
            href={link.href}
            onClick={() => setOpen(false)}
            className={`helix-nav-menu-link${pathname === link.href ? ' helix-nav-menu-link-active' : ''}`}
          >
            {link.label}
            {link.description ? <span>{link.description}</span> : null}
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function NavBar() {
  const pathname = usePathname();
  const { isSignedIn, isLoaded } = useAuth();
  const [open, setOpen] = useState(false);

  return (
    <nav className={`helix-nav${open ? ' helix-nav-open' : ''}`}>
      <Link href="/" className="helix-brand" aria-label="Helix home">
        <span className="helix-brand-mark">H</span>
        <span className="helix-brand-word">Helix</span>
      </Link>

      <button
        className="helix-nav-toggle"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        Menu
      </button>

      <div className="helix-nav-main">
        <NavGroup label="Product" links={productLinks} pathname={pathname} />
        <NavGroup label="Features" links={featureLinks} pathname={pathname} />
        <Link
          href="/how-it-works"
          className={`helix-nav-link${pathname === '/how-it-works' ? ' helix-nav-link-active' : ''}`}
        >
          How It Works
        </Link>
        <Link href="/#pricing" className="helix-nav-link">
          Pricing
        </Link>
        <NavGroup label="Resources" links={resourceLinks} pathname={pathname} />
      </div>

      <div className="helix-nav-right">
        {isLoaded && !isSignedIn && (
          <SignInButton mode="modal">
            <button className="helix-nav-signin" type="button">
              Sign In
            </button>
          </SignInButton>
        )}

        {isLoaded && isSignedIn && (
          <UserButton
            appearance={{
              elements: {
                avatarBox: {
                  width: '34px',
                  height: '34px',
                  border: '1px solid rgba(79,163,165,0.35)',
                },
              },
            }}
          />
        )}
      </div>
    </nav>
  );
}
