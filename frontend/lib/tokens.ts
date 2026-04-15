// Temper — shared design tokens
// Import this in every page: import { T, sx } from '@/lib/tokens'

export const T = {
  bg:        '#08080c',
  border:    'rgba(255,255,255,0.07)',
  borderSub: 'rgba(255,255,255,0.04)',
  sectionBg: 'rgba(255,255,255,0.024)',
  text:      'rgba(255,255,255,0.92)',
  textSub:   'rgba(255,255,255,0.52)',
  textMuted: 'rgba(255,255,255,0.36)',
  label:     'rgba(255,255,255,0.44)',
  up:        '#57a06a',
  dn:        '#b85555',
  wa:        '#9e7e35',
  mid:       'rgba(255,255,255,0.22)',
  accent:    '#9580d4',
  mono:      "'JetBrains Mono', monospace" as const,
  sans:      "'Inter', sans-serif" as const,

  // ── new spacing tokens ──
  cardBg:    'rgba(255,255,255,0.028)',
  cardBdr:   'rgba(255,255,255,0.07)',
  radius:    '10px',
  gap:       '16px',
};

export const MOBILE = 768;

// Reusable style fragments
export const sx = {
  sectionHd: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 28px',           // was 8px 24px — more vertical breathing room
    background: T.sectionBg,
    borderBottom: `1px solid ${T.border}`,  // was 0.5px — slightly more visible
  } as React.CSSProperties,

  sectionLabel: {
    fontFamily: T.sans,
    fontSize: '11px',
    letterSpacing: '1.6px',
    textTransform: 'uppercase',
    color: T.label,
    fontWeight: 500,
  } as React.CSSProperties,

  sectionMeta: {
    fontFamily: T.mono,
    fontSize: '11px',
    fontWeight: 300,
    color: T.textMuted,
    letterSpacing: '0.5px',
  } as React.CSSProperties,

  monoVal: {
    fontFamily: T.mono,
    fontWeight: 300,
    letterSpacing: '-0.5px',
  } as React.CSSProperties,

  main: {
    background: T.bg,
    minHeight: '100vh',
    maxWidth: '1600px',
    margin: '0 auto',               // center content on wide screens
  } as React.CSSProperties,

  skeleton: {
    background: 'rgba(255,255,255,0.06)',
    animation: 'temperPulse 1.8s ease-in-out infinite',
  } as React.CSSProperties,

  // ── new card style for grouped content ──
  card: {
    background: T.cardBg,
    border: `1px solid ${T.cardBdr}`,
    borderRadius: T.radius,
    overflow: 'hidden',
  } as React.CSSProperties,

  // ── new divider — softer than a full border ──
  divider: {
    borderBottom: `1px solid ${T.borderSub}`,
  } as React.CSSProperties,
};

// Helpers — unchanged
export function pct(val: number | undefined, decimals = 2): string {
  if (val === undefined || val === null) return '—';
  return formatAccountingPct(val, decimals);
}

export function signColor(val: number | undefined): string {
  if (val === undefined) return T.mid;
  return val >= 0 ? T.up : T.dn;
}

export function formatNumber(val: number | undefined | null, decimals = 2): string {
  if (val === undefined || val === null || Number.isNaN(val)) return '—';
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(val);
}

export function formatAccountingNumber(val: number | undefined | null, decimals = 2): string {
  if (val === undefined || val === null || Number.isNaN(val)) return '—';
  const abs = formatNumber(Math.abs(val), decimals);
  return val < 0 ? `(${abs})` : abs;
}

export function formatAccountingPct(val: number | undefined | null, decimals = 2): string {
  if (val === undefined || val === null || Number.isNaN(val)) return '—';
  const abs = `${formatNumber(Math.abs(val), decimals)}%`;
  return val < 0 ? `(${abs})` : abs;
}

export function formatCurrency(val: number | undefined | null, decimals = 2): string {
  if (val === undefined || val === null || Number.isNaN(val)) return '—';
  const abs = `$${formatNumber(Math.abs(val), decimals)}`;
  return val < 0 ? `(${abs})` : abs;
}

export function formatRelativeAge(input?: string | number | Date | null): string {
  if (!input) return 'Updated —';
  const ts = new Date(input).getTime();
  if (Number.isNaN(ts)) return 'Updated —';
  const diff = Math.max(0, Date.now() - ts);
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(minutes / 60);
  if (minutes <= 0) return 'Updated just now';
  if (minutes < 60) return `Updated ${minutes}m ago`;
  return `Updated ${hours}h ago`;
}

export function freshnessColor(input?: string | number | Date | null): string {
  if (!input) return T.textMuted;
  const ts = new Date(input).getTime();
  if (Number.isNaN(ts)) return T.textMuted;
  const diff = Date.now() - ts;
  if (diff > 2 * 60 * 60 * 1000) return T.dn;
  if (diff > 30 * 60 * 1000) return T.wa;
  return T.textMuted;
}