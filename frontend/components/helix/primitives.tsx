'use client';

import { useState } from 'react';
import { T } from '@/lib/tokens';

export const PAGE_SHELL: React.CSSProperties = {
  width: 'min(1280px, calc(100% - 48px))',
  margin: '0 auto',
  padding: '32px 0 64px',
  display: 'flex',
  flexDirection: 'column',
  gap: '32px',
};

export const SNAPSHOT_GRID: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 7fr) minmax(320px, 3fr)',
  gap: '32px',
};

export const MAIN_GRID: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1.95fr) minmax(340px, 1.05fr)',
  gap: '32px',
};

export function Card({
  title,
  meta,
  children,
  prominent = false,
  padded = true,
}: {
  title?: string;
  meta?: React.ReactNode;
  children: React.ReactNode;
  prominent?: boolean;
  padded?: boolean;
}) {
  return (
    <section
      style={{
        background: T.surface,
        border: `1px solid ${prominent ? T.border : T.borderSub}`,
        borderRadius: '20px',
        boxShadow: prominent ? T.shadowSoft : '0 8px 22px rgba(11,31,51,0.04)',
        overflow: 'hidden',
      }}
    >
      {title ? (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '14px',
            padding: '18px 22px',
            borderBottom: `1px solid ${T.borderSub}`,
          }}
        >
          <span
            style={{
              fontFamily: T.sans,
              fontSize: '15px',
              letterSpacing: 0,
              textTransform: 'none',
              color: T.navy,
              fontWeight: 650,
            }}
          >
            {title}
          </span>
          {meta ? (
            <span style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>
              {meta}
            </span>
          ) : null}
        </div>
      ) : null}
      <div style={{ padding: padded ? '20px' : 0 }}>{children}</div>
    </section>
  );
}

export function Chip({ label, color }: { label: string; color?: string }) {
  const c = color ?? T.textMuted;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        fontFamily: T.sans,
        fontSize: '10.5px',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        fontWeight: 600,
        color: c,
        background: `${c}14`,
        border: `1px solid ${c}33`,
        padding: '3px 9px',
        borderRadius: '999px',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
}

export function MutedLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: T.sans,
        fontSize: '10px',
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: T.textMuted,
        marginBottom: '6px',
        fontWeight: 600,
      }}
    >
      {children}
    </div>
  );
}

export function Collapsible({
  label,
  children,
  defaultOpen = false,
  count,
}: {
  label: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  count?: number;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: '100%',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '8px 0',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontFamily: T.sans,
          fontSize: '12px',
          color: T.textSub,
          fontWeight: 600,
        }}
      >
        <span style={{ fontSize: '9px', color: T.textMuted, width: 12 }}>
          {open ? '▾' : '▸'}
        </span>
        {label}
        {typeof count === 'number' ? (
          <span style={{ color: T.textMuted, fontFamily: T.mono, fontSize: '11px' }}>
            · {count}
          </span>
        ) : null}
      </button>
      {open ? <div style={{ paddingTop: '8px' }}>{children}</div> : null}
    </div>
  );
}

export function EmptyState({ msg, small = false }: { msg: string; small?: boolean }) {
  return (
    <div style={{ padding: small ? '12px' : '24px 12px', textAlign: 'center' }}>
      <span style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textMuted }}>
        {msg}
      </span>
    </div>
  );
}
