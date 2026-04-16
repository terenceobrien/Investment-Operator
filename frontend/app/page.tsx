import { T } from '@/lib/tokens';

export default function HomePage() {
  return (
    <>
      <style>{`
        @keyframes helixHomeDriftA {
          0% { transform: translate3d(-4%, -2%, 0) scale(1); opacity: 0.5; }
          50% { transform: translate3d(6%, 4%, 0) scale(1.08); opacity: 0.72; }
          100% { transform: translate3d(-4%, -2%, 0) scale(1); opacity: 0.5; }
        }

        @keyframes helixHomeDriftB {
          0% { transform: translate3d(6%, 0%, 0) scale(1.04); opacity: 0.34; }
          50% { transform: translate3d(-5%, -4%, 0) scale(0.96); opacity: 0.52; }
          100% { transform: translate3d(6%, 0%, 0) scale(1.04); opacity: 0.34; }
        }

        @keyframes helixHomeGridShift {
          0% { transform: translateY(0px); opacity: 0.16; }
          50% { transform: translateY(-12px); opacity: 0.26; }
          100% { transform: translateY(0px); opacity: 0.16; }
        }

        @keyframes helixHomePulse {
          0% { transform: scale(0.96); opacity: 0.18; }
          50% { transform: scale(1.03); opacity: 0.32; }
          100% { transform: scale(0.96); opacity: 0.18; }
        }

        @keyframes helixHomeShimmer {
          0% { transform: translateX(-120%); }
          100% { transform: translateX(140%); }
        }
      `}</style>

      <main
        style={{
          position: 'relative',
          minHeight: 'calc(100vh - 88px)',
          overflow: 'hidden',
          background: T.bg,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '48px 24px 72px',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'radial-gradient(circle at 50% 44%, rgba(149,128,212,0.18) 0%, rgba(149,128,212,0.08) 22%, rgba(7,7,10,0) 56%)',
            pointerEvents: 'none',
          }}
        />

        <div
          style={{
            position: 'absolute',
            top: '-12%',
            left: '-10%',
            width: '48vw',
            height: '48vw',
            minWidth: '320px',
            minHeight: '320px',
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(149,128,212,0.14) 0%, rgba(149,128,212,0.05) 40%, transparent 72%)',
            filter: 'blur(32px)',
            animation: 'helixHomeDriftA 12s ease-in-out infinite',
            pointerEvents: 'none',
          }}
        />

        <div
          style={{
            position: 'absolute',
            right: '-8%',
            bottom: '-18%',
            width: '42vw',
            height: '42vw',
            minWidth: '280px',
            minHeight: '280px',
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(149,128,212,0.12) 0%, rgba(149,128,212,0.04) 42%, transparent 74%)',
            filter: 'blur(40px)',
            animation: 'helixHomeDriftB 14s ease-in-out infinite',
            pointerEvents: 'none',
          }}
        />

        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage:
              'linear-gradient(rgba(255,255,255,0.028) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.028) 1px, transparent 1px)',
            backgroundSize: '56px 56px',
            maskImage: 'linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.9) 24%, rgba(0,0,0,0.9) 78%, transparent 100%)',
            animation: 'helixHomeGridShift 9s ease-in-out infinite',
            pointerEvents: 'none',
          }}
        />

        <div
          style={{
            position: 'absolute',
            width: '62vw',
            height: '62vw',
            maxWidth: '820px',
            maxHeight: '820px',
            borderRadius: '50%',
            border: '1px solid rgba(149,128,212,0.1)',
            boxShadow: '0 0 80px rgba(149,128,212,0.08), inset 0 0 60px rgba(149,128,212,0.04)',
            animation: 'helixHomePulse 8s ease-in-out infinite',
            pointerEvents: 'none',
          }}
        />

        <section
          style={{
            position: 'relative',
            zIndex: 2,
            width: '100%',
            maxWidth: '980px',
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          <div
            style={{
              position: 'relative',
              width: '100%',
              maxWidth: '860px',
              padding: '40px 36px 44px',
              border: `1px solid ${T.border}`,
              background:
                'linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.018) 100%)',
              boxShadow:
                '0 0 0 1px rgba(149,128,212,0.08) inset, 0 24px 80px rgba(0,0,0,0.45), 0 0 64px rgba(149,128,212,0.08)',
              overflow: 'hidden',
              backdropFilter: 'blur(8px)',
            }}
          >
            <div
              style={{
                position: 'absolute',
                inset: 0,
                background:
                  'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.08) 50%, transparent 100%)',
                width: '42%',
                animation: 'helixHomeShimmer 5.5s linear infinite',
                opacity: 0.28,
                pointerEvents: 'none',
              }}
            />

            <div
              style={{
                position: 'relative',
                zIndex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                textAlign: 'center',
                gap: '20px',
              }}
            >
              <div
                style={{
                  fontFamily: T.mono,
                  fontSize: '11px',
                  letterSpacing: '4px',
                  textTransform: 'uppercase',
                  color: 'rgba(255,255,255,0.36)',
                }}
              >
                Helix
              </div>

              <div
                style={{
                  width: '72px',
                  height: '72px',
                  border: '0.5px solid rgba(255,255,255,0.18)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: 'rgba(255,255,255,0.02)',
                  boxShadow: '0 0 36px rgba(149,128,212,0.18)',
                }}
              >
                <span
                  style={{
                    fontFamily: T.mono,
                    fontSize: '32px',
                    fontWeight: 400,
                    lineHeight: 1,
                    color: 'rgba(255,255,255,0.84)',
                  }}
                >
                  H
                </span>
              </div>

              <h1
                style={{
                  margin: 0,
                  maxWidth: '760px',
                  fontFamily: T.sans,
                  fontSize: 'clamp(32px, 6vw, 68px)',
                  lineHeight: 1.02,
                  letterSpacing: '-0.04em',
                  fontWeight: 500,
                  color: 'rgba(255,255,255,0.94)',
                  textWrap: 'balance',
                }}
              >
                Cutting edge market intelligence for active investors
              </h1>

              <div
                style={{
                  display: 'flex',
                  gap: '12px',
                  flexWrap: 'wrap',
                  justifyContent: 'center',
                  marginTop: '6px',
                }}
              >
                {['Macro regime', 'Market memory', 'Narrative state'].map((item) => (
                  <div
                    key={item}
                    style={{
                      fontFamily: T.mono,
                      fontSize: '10px',
                      letterSpacing: '1.6px',
                      textTransform: 'uppercase',
                      color: 'rgba(255,255,255,0.42)',
                      border: `1px solid ${T.borderSub}`,
                      padding: '8px 10px',
                      background: 'rgba(255,255,255,0.02)',
                    }}
                  >
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
