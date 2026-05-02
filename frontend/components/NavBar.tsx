'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { SignInButton, UserButton, useAuth } from '@clerk/nextjs';
import { useState } from 'react';

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
  return (
    <div className="helix-nav-group">
      <button className={`helix-nav-trigger${active ? ' helix-nav-trigger-active' : ''}`} type="button">
        {label}
        <span className="helix-nav-chevron">⌄</span>
      </button>
      <div className="helix-nav-menu">
        {links.map((link) => (
          <Link
            key={`${label}-${link.label}`}
            href={link.href}
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
        <span className="helix-live-pill">
          <span className="helix-live-dot" />
          {new Date().toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
          })}
        </span>

        {isLoaded && !isSignedIn && (
          <SignInButton mode="modal">
            <button className="helix-auth-button" type="button">
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

        <Link href="/narrative" className="helix-nav-cta">
          Analyze a Ticker
        </Link>
      </div>
    </nav>
  );
}
