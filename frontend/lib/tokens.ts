// Temper — shared design tokens
// Import this in every page: import { T, sx } from '@/lib/tokens'

export const T = {
  bg:        '#07070a',
  border:    'rgba(255,255,255,0.06)',
  borderSub: 'rgba(255,255,255,0.03)',
  sectionBg: 'rgba(255,255,255,0.018)',
  text:      'rgba(255,255,255,0.95)',
  textSub:   'rgba(255,255,255,0.55)',
  textMuted: 'rgba(255,255,255,0.40)',
  label:     'rgba(255,255,255,0.50)',
  up:        '#57a06a',
  dn:        '#b85555',
  wa:        '#9e7e35',
  mid:       'rgba(255,255,255,0.22)',
  accent:    '#9580d4',
  mono:      "'JetBrains Mono', monospace" as const,
  sans:      "'Inter', sans-serif" as const,
};

export const MOBILE = 768;

// Reusable style fragments
export const sx = {
  sectionHd: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '8px 24px',
    background: T.sectionBg,
    borderBottom: `0.5px solid ${T.border}`,
  } as React.CSSProperties,

  sectionLabel: {
    fontFamily: T.sans,
    fontSize: '11px',
    letterSpacing: '1.8px',
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
  } as React.CSSProperties,

  skeleton: {
    background: 'rgba(255,255,255,0.06)',
    animation: 'temperPulse 1.8s ease-in-out infinite',
  } as React.CSSProperties,
};

// Helpers
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
