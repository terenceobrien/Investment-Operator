// Helix — shared design tokens
// Import this in every page: import { T, sx } from '@/lib/tokens'

export const T = {
  bg:        '#F3F5F7',
  pageBg:    '#F3F5F7',
  surface:   '#FFFFFF',
  surfaceMuted: '#F8FAFB',
  navy:      '#0B1F33',
  navySoft:  '#16324F',
  border:    '#D8DEE6',
  borderSub: '#E8EDF2',
  sectionBg: '#F8FAFB',
  text:      '#102033',
  textSub:   '#5B6678',
  textMuted: '#7B8798',
  label:     '#5B6678',
  up:        '#168A5A',
  dn:        '#C94A4A',
  wa:        '#B7791F',
  mid:       '#A3ADBA',
  accent:    '#4FA3A5',
  accentDark:'#2F7F82',
  accentSoft:'#E7F4F4',
  mono:      "'SFMono-Regular', 'Roboto Mono', 'JetBrains Mono', ui-monospace, monospace" as const,
  sans:      "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" as const,

  // ── new spacing tokens ──
  cardBg:    '#FFFFFF',
  cardBdr:   '#D8DEE6',
  radius:    '18px',
  gap:       '16px',
  shadowSoft:'0 18px 50px rgba(15, 31, 51, 0.08)',
};

export const MOBILE = 768;

// Reusable style fragments
export const sx = {
  sectionHd: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 24px',
    background: T.sectionBg,
    borderLeft: `3px solid ${T.accent}`,
    borderBottom: `1px solid ${T.borderSub}`,
  } as React.CSSProperties,

  sectionLabel: {
    fontFamily: T.sans,
    fontSize: '13px',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: T.label,
    fontWeight: 700,
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
    color: T.text,
  } as React.CSSProperties,

  pageShell: {
    width: 'min(1280px, calc(100% - 48px))',
    margin: '0 auto',
    padding: '32px 0 72px',
    display: 'flex',
    flexDirection: 'column',
    gap: '28px',
  } as React.CSSProperties,

  panel: {
    background: T.surface,
    border: `1px solid ${T.border}`,
    borderRadius: T.radius,
    overflow: 'hidden',
    boxShadow: T.shadowSoft,
  } as React.CSSProperties,

  panelHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
    padding: '14px 18px',
    background: T.sectionBg,
    borderLeft: `3px solid ${T.accent}`,
    borderBottom: `1px solid ${T.borderSub}`,
  } as React.CSSProperties,

  panelBody: {
    padding: '18px',
  } as React.CSSProperties,

  subPanel: {
    background: T.surfaceMuted,
    border: `1px solid ${T.borderSub}`,
    borderRadius: T.radius,
    overflow: 'hidden',
  } as React.CSSProperties,

  subPanelHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
    padding: '12px 16px',
    background: T.surfaceMuted,
    borderBottom: `1px solid ${T.borderSub}`,
  } as React.CSSProperties,

  skeleton: {
    background: 'linear-gradient(90deg, #E8EDF2 0%, #F8FAFB 50%, #E8EDF2 100%)',
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
