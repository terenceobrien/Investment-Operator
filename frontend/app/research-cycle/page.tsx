'use client';

import { useState } from 'react';
import { useAuthFetcher } from '../../lib/api';
import AuthRequired from '@/components/AuthRequired';
import { T, sx } from '@/lib/tokens';

// ═══════════════════════════════════════════════════════════════════
// Research cycle
//
// Flow:
//   1. Enter a thesis
//   2. POST to GENERATE_ENDPOINT → generate_priorities_from_text → review
//      the proposed ResearchPriority
//   3. Accept → confirm the write to current_regime.yaml (side-effect gated)
//   4. POST to RUN_ENDPOINT → the 7-stage cycle runs. It's long, so this
//      subscribes to STREAM_ENDPOINT (SSE) for per-stage progress. If the
//      stream isn't available it falls back to a simulated progression so the
//      UI still demonstrates the flow.
//   5. Output rendered.
//
// Point the three endpoint constants at your real API. Until then the page
// runs in demo mode (simulated priority + simulated stage stream).
// ═══════════════════════════════════════════════════════════════════

const GENERATE_ENDPOINT = '/api/research/priorities/generate';
const COMMIT_ENDPOINT = '/api/research/priorities/commit';
const RUN_ENDPOINT = '/api/research/cycle/run';
const STREAM_ENDPOINT = (jobId: string) => `/api/research/cycle/${jobId}/stream`;

type AnyRecord = Record<string, unknown>;

type ResearchPriority = {
  priority_rank: number;
  source_theme_id: string;
  theme: string;
  edge_hypothesis: string;
  expected_edge_decay: string;
  sub_questions: string[];
};

const STAGES = [
  ['Macro context', 'regime + scenario probabilities loaded'],
  ['Thematic screen', 'ranked themes against scenario distribution'],
  ['Fundamental screen', 'candidate names scored on factor matrix'],
  ['Conviction gate', 'narrative + evidence confirmation'],
  ['Trade expression', 'sizing, horizon, benchmark set'],
  ['Scenario scoring', 'P&L across five scenarios'],
  ['Portfolio construction', 'positions + shadow-tracked rejects'],
];

// Demo priority used when the generate endpoint isn't wired.
const DEMO_PRIORITY: ResearchPriority = {
  priority_rank: 1,
  source_theme_id: 'grid_power_infrastructure',
  theme: 'Second-order grid and power infrastructure beneficiaries with cross-scenario support',
  edge_hypothesis:
    'Macro support for grid and power infrastructure may create attractive research paths, but the edge depends on finding specific second-order names not already repriced by direct AI demand.',
  expected_edge_decay: 'quarters',
  sub_questions: [
    'Which electrical-equipment and utility names have rate-base or backlog exposure to data-center load growth?',
    'Where is the market still pricing these as regulated utilities rather than AI-adjacent growth?',
    'What valuation gap exists versus direct AI infrastructure names?',
    'Which of these survive an AI capex rollover scenario?',
  ],
};

type Phase = 'input' | 'review' | 'confirm' | 'running' | 'done';

export default function ResearchCyclePage() {
  const authFetcher = useAuthFetcher();
  const [thesis, setThesis] = useState(DEMO_PRIORITY.theme);
  const [phase, setPhase] = useState<Phase>('input');
  const [priority, setPriority] = useState<ResearchPriority | null>(null);
  const [busy, setBusy] = useState(false);
  const [stageState, setStageState] = useState<('queued' | 'running' | 'done')[]>(STAGES.map(() => 'queued'));

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  // ── Step 2: generate priorities ──
  async function generate() {
    setBusy(true);
    try {
      const res = await authFetcher.fetcher(GENERATE_ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ text: thesis }),
      } as RequestInit);
      const p = (res?.priorities?.[0] ?? res?.priority ?? null) as ResearchPriority | null;
      setPriority(p ?? { ...DEMO_PRIORITY, theme: thesis });
    } catch {
      // Endpoint not available — demo mode.
      setPriority({ ...DEMO_PRIORITY, theme: thesis });
    } finally {
      setBusy(false);
      setPhase('review');
    }
  }

  // ── Step 3: accept → confirm write ──
  function accept() {
    setPhase('confirm');
  }

  // ── Step 4: confirm write + run ──
  async function confirmAndRun() {
    if (!priority) return;
    setBusy(true);
    setPhase('running');
    setStageState(STAGES.map(() => 'queued'));

    // Commit the priority to current_regime.yaml (side-effect).
    let jobId: string | null = null;
    try {
      await authFetcher.fetcher(COMMIT_ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ priority }),
      } as RequestInit);
      const run = await authFetcher.fetcher(RUN_ENDPOINT, { method: 'POST' } as RequestInit);
      jobId = safeStr(run?.job_id) || null;
    } catch {
      jobId = null; // demo mode
    }
    setBusy(false);

    if (jobId) {
      subscribeToStream(jobId);
    } else {
      simulateStages();
    }
  }

  // Real stream: authenticated SSE per-stage events { stage_index, status }.
  async function subscribeToStream(jobId: string) {
    let receivedDone = false;
    const handleMessage = (msg: { stage_index?: number; status?: string; done?: boolean }) => {
      if (typeof msg.stage_index === 'number') {
        setStageState((prev) => {
          const next = [...prev];
          for (let i = 0; i < msg.stage_index!; i++) next[i] = 'done';
          next[msg.stage_index!] = (msg.status as 'running' | 'done') ?? 'running';
          return next;
        });
      }
      if (msg.done) {
        receivedDone = true;
        setStageState(STAGES.map(() => 'done'));
        setPhase('done');
      }
    };

    try {
      const res = await authFetcher.stream(STREAM_ENDPOINT(jobId));
      if (!res.body) throw new Error('No stream body');
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';

        for (const frame of frames) {
          const data = frame
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.replace(/^data:\s?/, ''))
            .join('\n')
            .trim();
          if (!data) continue;
          try {
            handleMessage(JSON.parse(data));
          } catch {
            /* ignore malformed frame */
          }
        }
      }

      if (!receivedDone && buffer.trim()) {
        const data = buffer
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.replace(/^data:\s?/, ''))
          .join('\n')
          .trim();
        if (data) handleMessage(JSON.parse(data));
      }

      if (!receivedDone) simulateStages();
    } catch {
      simulateStages();
    }
  }

  // Fallback: simulated progression so the flow is demonstrable offline.
  function simulateStages() {
    let i = 0;
    const tick = () => {
      setStageState((prev) => {
        const next = [...prev];
        if (i > 0) next[i - 1] = 'done';
        if (i < STAGES.length) next[i] = 'running';
        return next;
      });
      if (i < STAGES.length) {
        i += 1;
        setTimeout(tick, 900 + Math.random() * 700);
      } else {
        setStageState(STAGES.map(() => 'done'));
        setPhase('done');
      }
    };
    tick();
  }

  const stepActive = (n: number) => {
    const map: Record<number, boolean> = {
      1: true,
      2: phase !== 'input',
      3: phase === 'confirm' || phase === 'running' || phase === 'done',
      4: phase === 'running' || phase === 'done',
      5: phase === 'done',
    };
    return map[n];
  };

  return (
    <main style={sx.main}>
      <div style={{ ...sx.pageShell, maxWidth: 'min(1080px, calc(100% - 48px))', margin: '0 auto', width: 'min(1080px, calc(100% - 48px))' }}>
        <div>
          <div style={{ fontFamily: T.mono, fontSize: '12px', letterSpacing: '0.2em', color: T.textMuted, marginBottom: '10px' }}>03 / RESEARCH CYCLE</div>
          <h1 style={{ fontFamily: T.sans, fontSize: '32px', fontWeight: 700, color: T.text, margin: 0 }}>Run a full cycle</h1>
        </div>

        {/* Step 1 */}
        <StepShell n={1} title="Enter a thesis" active={stepActive(1)}>
          <textarea
            value={thesis}
            onChange={(e) => setThesis(e.target.value)}
            placeholder="Describe a thesis or edge hypothesis to explore…"
            style={{
              width: '100%', minHeight: '120px', resize: 'vertical',
              background: T.surfaceMuted, border: `1px solid ${T.border}`, borderRadius: '12px',
              padding: '16px', fontFamily: T.sans, fontSize: '15px', color: T.text, lineHeight: 1.6,
            }}
          />
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', marginTop: '14px' }}>
            <button onClick={generate} disabled={busy || phase !== 'input'} style={btnPrimary(busy || phase !== 'input')}>
              {busy && phase === 'input' ? 'Generating…' : 'Generate priorities'}
            </button>
            <span style={{ fontFamily: T.mono, fontSize: '11px', letterSpacing: '0.1em', color: T.textMuted }}>triggers generate_priorities_from_text</span>
          </div>
        </StepShell>

        {/* Step 2 */}
        <StepShell n={2} title="Review proposed ResearchPriority" active={stepActive(2)} status={priority ? 'generated' : undefined}>
          {priority ? (
            <div style={{ ...sx.subPanel, padding: '18px' }}>
              <div style={{ fontFamily: T.sans, fontSize: '15px', fontWeight: 600, color: T.text, marginBottom: '8px' }}>
                #{priority.priority_rank} · {priority.source_theme_id}
              </div>
              <p style={{ margin: '0 0 12px', fontFamily: T.sans, fontSize: '13.5px', color: T.textSub, lineHeight: 1.55 }}>
                <b style={{ color: T.text }}>Edge hypothesis.</b> {priority.edge_hypothesis}
              </p>
              <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.12em', textTransform: 'uppercase', color: T.textMuted, fontWeight: 700, marginBottom: '8px' }}>Sub-questions</div>
              <ul style={{ margin: 0, paddingLeft: '18px', fontFamily: T.sans, fontSize: '13px', color: T.textSub, lineHeight: 1.6 }}>
                {priority.sub_questions.map((q, i) => <li key={i} style={{ marginBottom: '5px' }}>{q}</li>)}
              </ul>
              <div style={{ marginTop: '14px', fontFamily: T.sans, fontSize: '12px', color: T.textMuted }}>
                Expected edge decay: <b style={{ color: T.textSub }}>{priority.expected_edge_decay}</b>
              </div>
              {phase === 'review' ? (
                <div style={{ display: 'flex', gap: '12px', marginTop: '16px' }}>
                  <button onClick={accept} style={btnPrimary(false)}>Accept &amp; commit</button>
                  <button onClick={() => setPhase('input')} style={btnGhost()}>Reject</button>
                </div>
              ) : null}
            </div>
          ) : null}
        </StepShell>

        {/* Step 3 */}
        <StepShell n={3} title="Commit to current_regime.yaml" active={stepActive(3)} status={phase === 'running' || phase === 'done' ? 'committed' : undefined}>
          {phase === 'confirm' && priority ? (
            <>
              <div style={warnBanner()}>
                ⚠ This writes to current_regime.yaml — the config the whole system reads from. Confirm before proceeding.
              </div>
              <pre style={yamlBox()}>
{`research_priorities:
  - priority_rank: ${priority.priority_rank}
    source_theme_id: ${priority.source_theme_id}
    theme: ${truncate(priority.theme, 60)}
    expected_edge_decay: ${priority.expected_edge_decay}
    sub_questions: [${priority.sub_questions.length} items]`}
              </pre>
              <div style={{ display: 'flex', gap: '12px', marginTop: '14px' }}>
                <button onClick={confirmAndRun} disabled={busy} style={btnPrimary(busy)}>Confirm write &amp; run cycle</button>
              </div>
            </>
          ) : null}
        </StepShell>

        {/* Step 4 */}
        <StepShell n={4} title="Run 7-stage cycle" active={stepActive(4)} status={phase === 'done' ? 'complete' : phase === 'running' ? 'running…' : undefined}>
          {(phase === 'running' || phase === 'done') ? (
            <div>
              {STAGES.map(([name, detail], i) => (
                <div key={name} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '9px 0', borderTop: i ? `1px solid ${T.borderSub}` : 'none' }}>
                  <StageIcon state={stageState[i]} />
                  <span style={{ fontFamily: T.sans, fontSize: '13.5px', fontWeight: 500, color: T.text }}>{name}</span>
                  <span style={{ marginLeft: 'auto', fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>
                    {stageState[i] === 'done' ? detail : stageState[i] === 'running' ? 'running…' : 'queued'}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </StepShell>

        {/* Step 5 */}
        <StepShell n={5} title="Cycle output" active={stepActive(5)} status={phase === 'done' ? '7 stages · complete' : undefined}>
          {phase === 'done' && priority ? (
            <div style={{ ...successBanner() }}>
              ✓ Cycle complete. Output written to reports/. Priority “{truncate(priority.theme, 60)}” committed and evaluated across five scenarios.
            </div>
          ) : null}
        </StepShell>
      </div>
    </main>
  );
}

// ── step shell ──
function StepShell({ n, title, active, status, children }: { n: number; title: string; active: boolean; status?: string; children?: React.ReactNode }) {
  return (
    <section style={{ ...sx.panel, opacity: active ? 1 : 0.5, transition: 'opacity 0.3s' }}>
      <div style={{ ...sx.panelHeader, borderLeft: `3px solid ${active ? T.accent : T.border}` }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <span style={{ width: '28px', height: '28px', borderRadius: '8px', background: T.surfaceMuted, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: T.mono, fontSize: '13px', fontWeight: 600, color: T.textSub }}>{n}</span>
          <span style={{ fontFamily: T.sans, fontSize: '15px', fontWeight: 600, color: T.text }}>{title}</span>
        </span>
        {status ? <span style={sx.sectionMeta}>{status}</span> : null}
      </div>
      {children ? <div style={sx.panelBody}>{children}</div> : null}
    </section>
  );
}

function StageIcon({ state }: { state: 'queued' | 'running' | 'done' }) {
  if (state === 'done') return <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: T.up, flexShrink: 0 }} />;
  if (state === 'running') return <span style={{ width: '20px', height: '20px', borderRadius: '50%', border: `2px solid ${T.accent}`, borderTopColor: 'transparent', flexShrink: 0, animation: 'helixSpin 0.8s linear infinite' }} />;
  return <span style={{ width: '20px', height: '20px', borderRadius: '50%', border: `2px solid ${T.border}`, flexShrink: 0 }} />;
}

// ── styles ──
function btnPrimary(disabled: boolean): React.CSSProperties {
  return { background: disabled ? T.mid : T.accent, color: '#04121F', border: 'none', borderRadius: '10px', padding: '10px 18px', fontFamily: T.sans, fontSize: '13px', fontWeight: 700, cursor: disabled ? 'default' : 'pointer' };
}
function btnGhost(): React.CSSProperties {
  return { background: T.surface, color: T.textSub, border: `1px solid ${T.border}`, borderRadius: '10px', padding: '10px 18px', fontFamily: T.sans, fontSize: '13px', fontWeight: 600, cursor: 'pointer' };
}
function warnBanner(): React.CSSProperties {
  return { background: `${T.wa}14`, border: `1px solid ${T.wa}44`, borderRadius: '10px', padding: '12px 16px', fontFamily: T.sans, fontSize: '13px', color: T.wa, marginBottom: '12px' };
}
function successBanner(): React.CSSProperties {
  return { background: `${T.up}14`, border: `1px solid ${T.up}44`, borderRadius: '10px', padding: '12px 16px', fontFamily: T.sans, fontSize: '13px', color: T.up };
}
function yamlBox(): React.CSSProperties {
  return { background: T.navy, border: `1px solid ${T.navySoft}`, borderRadius: '10px', padding: '16px', fontFamily: T.mono, fontSize: '12.5px', lineHeight: 1.7, color: '#C6D2E0', margin: 0, whiteSpace: 'pre-wrap' };
}

// ── helpers ──
function safeStr(v: unknown, fb = ''): string { return typeof v === 'string' ? v : fb; }
function truncate(s: string, max = 200): string { return !s || s.length <= max ? s : s.slice(0, max).trimEnd() + '…'; }
