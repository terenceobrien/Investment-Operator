import { T } from '@/lib/tokens';

export default function LoadingScreen({ loaded }: { loaded: boolean }) {
  return (
    <div className={`helix-loading-screen${loaded ? ' helix-loading-screen--loaded' : ''}`}>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '18px',
        }}
      >
        <div
          style={{
            position: 'relative',
            width: '80px',
            height: '80px',
            border: `1px solid ${T.border}`,
            borderRadius: '18px',
            background: T.surface,
            boxShadow: T.shadowSoft,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            overflow: 'hidden',
          }}
        >
          <span
            style={{
              position: 'relative',
              zIndex: 1,
              fontFamily: T.mono,
              fontSize: '36px',
              fontWeight: 700,
              color: T.navy,
              lineHeight: 1,
            }}
          >
            H
          </span>
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '60%',
              height: '100%',
              background: 'linear-gradient(90deg, transparent 0%, rgba(79,163,165,0.2) 50%, transparent 100%)',
              animation: 'sweep 1.2s ease-in-out infinite',
            }}
          />
        </div>

        <div
          style={{
            fontFamily: T.sans,
            fontSize: '11px',
            letterSpacing: '4px',
            textTransform: 'uppercase',
            color: T.textMuted,
          }}
        >
          Helix
        </div>
      </div>
    </div>
  );
}
