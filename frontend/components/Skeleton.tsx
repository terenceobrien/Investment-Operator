'use client';

import { CSSProperties } from 'react';
import { sx, T } from '@/lib/tokens';

export function SkeletonBlock({
  width = '100%',
  height = 14,
  style,
}: {
  width?: number | string;
  height?: number | string;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        ...sx.skeleton,
        width,
        height,
        borderRadius: 2,
        ...style,
      }}
    />
  );
}

export function SkeletonText({
  lines = 3,
  widths,
  lineHeight = 12,
}: {
  lines?: number;
  widths?: Array<number | string>;
  lineHeight?: number;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {Array.from({ length: lines }).map((_, idx) => (
        <SkeletonBlock
          key={idx}
          height={lineHeight}
          width={widths?.[idx] ?? `${Math.max(52, 100 - idx * 12)}%`}
        />
      ))}
    </div>
  );
}

export function SkeletonMetricGrid({
  columns = 5,
  items = 5,
}: {
  columns?: number;
  items?: number;
}) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(auto-fit, minmax(${columns > 4 ? 180 : 220}px, 1fr))`,
      }}
    >
      {Array.from({ length: items }).map((_, idx) => (
        <div
          key={idx}
          style={{
            padding: '16px 24px',
            borderRight: `0.5px solid ${T.border}`,
            borderBottom: `0.5px solid ${T.borderSub}`,
            minHeight: '108px',
          }}
        >
          <SkeletonBlock width="42%" height={10} style={{ marginBottom: '16px' }} />
          <SkeletonBlock width="68%" height={30} style={{ marginBottom: '10px' }} />
          <SkeletonBlock width="54%" height={10} />
        </div>
      ))}
    </div>
  );
}

export function SkeletonRows({
  rows = 6,
  columns = 3,
}: {
  rows?: number;
  columns?: number;
}) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, idx) => (
        <div
          key={idx}
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
            gap: '16px',
            padding: '10px 24px',
            borderBottom: `0.5px solid ${T.borderSub}`,
          }}
        >
          {Array.from({ length: columns }).map((__, colIdx) => (
            <SkeletonBlock
              key={colIdx}
              height={12}
              width={colIdx === 0 ? '38%' : '68%'}
              style={{ justifySelf: colIdx === 0 ? 'start' : 'end' }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonPanel({
  titleWidth = '24%',
  metaWidth = '18%',
  children,
}: {
  titleWidth?: number | string;
  metaWidth?: number | string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ borderBottom: `0.5px solid ${T.border}` }}>
      <div style={sx.sectionHd}>
        <SkeletonBlock width={titleWidth} height={10} />
        <SkeletonBlock width={metaWidth} height={10} />
      </div>
      {children}
    </div>
  );
}
