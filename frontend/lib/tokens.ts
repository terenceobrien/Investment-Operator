// Temper — shared design tokens
// Import this in every page: import { T, sx } from '@/lib/tokens'

export const T = {
  bg:        '#07070a',
  border:    'rgba(255,255,255,0.06)',
  borderSub: 'rgba(255,255,255,0.03)',
  sectionBg: 'rgba(255,255,255,0.018)',
  text:      'rgba(255,255,255,0.88)',
  textSub:   'rgba(255,255,255,0.28)',
  textMuted: 'rgba(255,255,255,0.18)',
  label:     'rgba(255,255,255,0.22)',
  up:        '#57a06a',
  dn:        '#b85555',
  wa:        '#9e7e35',
  mid:       'rgba(255,255,255,0.22)',
  accent:    '#9580d4',
  mono:      "'JetBrains Mono', monospace" as const,
  sans:      "'Inter', sans-serif" as const,
};

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
    fontSize: '9px',
    letterSpacing: '1.8px',
    textTransform: 'uppercase',
    color: T.label,
    fontWeight: 500,
  } as React.CSSProperties,

  sectionMeta: {
    fontFamily: T.mono,
    fontSize: '9px',
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
};

// Helpers
export function pct(val: number | undefined, decimals = 2): string {
  if (val === undefined || val === null) return '—';
  return `${val >= 0 ? '+' : ''}${val.toFixed(decimals)}%`;
}

export function signColor(val: number | undefined): string {
  if (val === undefined) return T.mid;
  return val >= 0 ? T.up : T.dn;
}