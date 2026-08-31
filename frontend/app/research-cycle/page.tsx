'use client';

import { useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { ApiRequestError, useAuthFetcher } from '../../lib/api';
import AuthRequired from '@/components/AuthRequired';
import { M } from '../lib/researchOsTheme';

const GENERATE_ENDPOINT = '/api/priorities/generate';
const APPROVE_ENDPOINT = '/api/priorities/approve';
const MANUAL_QUEUE_ENDPOINT = '/api/priorities/manual';
const RUN_ENDPOINT = '/api/research/cycle/run';
const STREAM_ENDPOINT = (jobId: string) => `/api/research/cycle/${jobId}/stream`;

type Evidence = {
  source_type?: string;
  claim: string;
  supports: boolean;
  computation: string;
  upstream_claims: string[];
  notes?: string;
};

type ResearchPriority = {
  schema_version?: string;
  created_at?: string;
  id?: string | null;
  theme: string;
  rationale: string;
  edge_hypothesis: string;
  sub_questions: string[];
  priority_rank: number;
  expected_edge_decay: string;
  supporting_evidence: Evidence[];
  source_theme_id?: string | null;
  source_scenario_ids?: string[];
  source?: string | null;
  source_macro_forecast_id?: string | null;
  source_thesis_text?: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
};

type GenerateResponse = {
  priority: ResearchPriority;
  raw_llm_output?: string | null;
};

type ApproveResponse = {
  success: boolean;
  manual_priorities_count: number;
};

type ManualQueueResponse = {
  manual_priorities_count: number;
  priorities: ResearchPriority[];
};

type ApiErrorDetail = {
  message: string;
  rawLlmOutput?: string | null;
  validationError?: string | null;
};

type Phase = 'compose' | 'review' | 'confirmed' | 'running' | 'done';
type BusyAction = 'generate' | 'approve' | 'run' | 'queue' | null;

const STAGES = [
  ['Macro context', 'regime + scenario probabilities loaded'],
  ['Thematic screen', 'ranked themes against scenario distribution'],
  ['Fundamental screen', 'candidate names scored on factor matrix'],
  ['Conviction gate', 'narrative + evidence confirmation'],
  ['Trade expression', 'sizing, horizon, benchmark set'],
  ['Scenario scoring', 'P&L across behavioral scenarios'],
  ['Portfolio construction', 'positions + shadow-tracked rejects'],
];

const MANUAL_CYCLE_COMMAND =
  'PYTHONPATH=backend python3 -m src.agent_system.orchestration.run_research_cycle --priority-source manual';

export default function ResearchCyclePage() {
  const authFetcher = useAuthFetcher();
  const [thesis, setThesis] = useState('');
  const [phase, setPhase] = useState<Phase>('compose');
  const [draftPriority, setDraftPriority] = useState<ResearchPriority | null>(null);
  const [generatedSourceText, setGeneratedSourceText] = useState('');
  const [evidenceText, setEvidenceText] = useState('[]');
  const [questionsText, setQuestionsText] = useState('');
  const [busyAction, setBusyAction] = useState<BusyAction>(null);
  const [generationError, setGenerationError] = useState<ApiErrorDetail | null>(null);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [cycleError, setCycleError] = useState<string | null>(null);
  const [manualQueue, setManualQueue] = useState<ResearchPriority[]>([]);
  const [showQueue, setShowQueue] = useState(false);
  const [manualCount, setManualCount] = useState<number | null>(null);
  const [stageState, setStageState] = useState<('queued' | 'running' | 'done')[]>(STAGES.map(() => 'queued'));

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  async function generate() {
    const cleaned = thesis.trim();
    if (!cleaned) return;
    setBusyAction('generate');
    setGenerationError(null);
    setApprovalError(null);
    setCycleError(null);
    try {
      const res = (await authFetcher.fetcher(GENERATE_ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ thesis_text: cleaned }),
      } as RequestInit)) as GenerateResponse;
      setDraftPriority(normalizePriority(res.priority));
      setGeneratedSourceText(cleaned);
      setQuestionsText((res.priority.sub_questions ?? []).join('\n'));
      setEvidenceText(JSON.stringify(res.priority.supporting_evidence ?? [], null, 2));
      setPhase('review');
    } catch (error) {
      setGenerationError(apiErrorDetail(error));
    } finally {
      setBusyAction(null);
    }
  }

  function updatePriorityField<K extends keyof ResearchPriority>(key: K, value: ResearchPriority[K]) {
    setDraftPriority((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  function editedPriority(): ResearchPriority | null {
    if (!draftPriority) return null;
    let evidence: Evidence[];
    try {
      const parsed = JSON.parse(evidenceText);
      if (!Array.isArray(parsed)) throw new Error('supporting_evidence must be a JSON array');
      evidence = parsed as Evidence[];
    } catch (error) {
      setApprovalError(error instanceof Error ? error.message : 'supporting_evidence JSON is invalid');
      return null;
    }
    const subQuestions = questionsText
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean);
    return {
      ...draftPriority,
      theme: draftPriority.theme.trim(),
      rationale: draftPriority.rationale.trim(),
      edge_hypothesis: draftPriority.edge_hypothesis.trim(),
      sub_questions: subQuestions,
      priority_rank: Number(draftPriority.priority_rank),
      expected_edge_decay: draftPriority.expected_edge_decay,
      supporting_evidence: evidence,
    };
  }

  async function approve() {
    const priority = editedPriority();
    if (!priority) return;
    setBusyAction('approve');
    setApprovalError(null);
    try {
      const res = (await authFetcher.fetcher(APPROVE_ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({
          priority,
          source_thesis_text: generatedSourceText,
        }),
      } as RequestInit)) as ApproveResponse;
      setManualCount(res.manual_priorities_count);
      setDraftPriority(priority);
      setPhase('confirmed');
      await loadManualQueue(true);
    } catch (error) {
      setApprovalError(apiErrorDetail(error).message);
    } finally {
      setBusyAction(null);
    }
  }

  async function loadManualQueue(openAfterLoad = true) {
    setBusyAction('queue');
    try {
      const res = (await authFetcher.fetcher(MANUAL_QUEUE_ENDPOINT)) as ManualQueueResponse;
      setManualQueue(res.priorities ?? []);
      setManualCount(res.manual_priorities_count);
      if (openAfterLoad) setShowQueue(true);
    } catch (error) {
      setApprovalError(apiErrorDetail(error).message);
    } finally {
      setBusyAction(null);
    }
  }

  async function runManualCycle() {
    setBusyAction('run');
    setCycleError(null);
    setPhase('running');
    setStageState(STAGES.map(() => 'queued'));
    try {
      const run = (await authFetcher.fetcher(RUN_ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ priority_source: 'manual' }),
      } as RequestInit)) as { job_id?: string };
      const jobId = safeStr(run.job_id);
      if (!jobId) throw new Error('Run endpoint did not return a job_id');
      setBusyAction(null);
      await subscribeToStream(jobId);
    } catch (error) {
      setBusyAction(null);
      setCycleError(apiErrorDetail(error).message);
      setPhase('confirmed');
    }
  }

  async function subscribeToStream(jobId: string) {
    let receivedDone = false;
    const handleMessage = (msg: { stage_index?: number; status?: string; done?: boolean; error?: string }) => {
      if (typeof msg.stage_index === 'number') {
        setStageState((prev) => {
          const next = [...prev];
          for (let i = 0; i < msg.stage_index!; i++) next[i] = 'done';
          next[msg.stage_index!] = (msg.status as 'running' | 'done') ?? 'running';
          return next;
        });
      }
      if (msg.error) setCycleError(msg.error);
      if (msg.done) {
        receivedDone = true;
        setStageState(STAGES.map(() => 'done'));
        setPhase('done');
      }
    };

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
        handleMessage(JSON.parse(data));
      }
    }

    if (!receivedDone) {
      throw new Error(`Cycle stream closed before completion for job ${jobId}`);
    }
  }

  const canGenerate = thesis.trim().length > 0 && busyAction !== 'generate';
  const canApprove =
    !!draftPriority?.theme.trim() &&
    !!draftPriority?.rationale.trim() &&
    !!draftPriority?.edge_hypothesis.trim() &&
    questionsText.split('\n').some((item) => item.trim()) &&
    !!draftPriority?.expected_edge_decay &&
    evidenceText.trim().length > 0 &&
    busyAction !== 'approve';

  const stepActive = (n: number) => {
    const map: Record<number, boolean> = {
      1: true,
      2: phase !== 'compose',
      3: phase === 'confirmed' || phase === 'running' || phase === 'done',
      4: phase === 'running' || phase === 'done',
    };
    return map[n];
  };

  return (
    <main style={{ minHeight: '100vh', background: M.canvas, color: M.canvasInk, fontFamily: M.sans }}>
      <div style={{ width: 'min(1180px, calc(100% - 48px))', margin: '0 auto', padding: '34px 0 76px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 18, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontFamily: M.mono, fontSize: '12px', letterSpacing: '0.22em', color: M.canvasInkFaint, marginBottom: '10px' }}>RESEARCH CYCLE &gt; MANUAL THESIS</div>
            <h1 style={{ fontFamily: M.serif, fontSize: '42px', fontWeight: 500, color: M.canvasInk, margin: 0, lineHeight: 1.02 }}>Current manual thesis</h1>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <StatusPill label={phase} />
            <StatusPill label={manualCount === null ? 'manual priority' : `${manualCount} saved`} />
          </div>
        </div>

        <StepShell n={1} title="Compose" active={stepActive(1)}>
          <textarea
            value={thesis}
            onChange={(event) => setThesis(event.target.value)}
            placeholder="Describe the investment thesis you want turned into a manual ResearchPriority..."
            style={textareaStyle(130)}
          />
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 14, flexWrap: 'wrap' }}>
            <button onClick={generate} disabled={!canGenerate} style={btnPrimary(!canGenerate)}>
              {busyAction === 'generate' ? 'Generating paid LLM call...' : 'Generate Priority'}
            </button>
            <span style={{ fontFamily: M.mono, fontSize: '11px', letterSpacing: '0.1em', color: busyAction === 'generate' ? M.warn : M.inkFaint }}>
              explicit action only; nothing runs while typing
            </span>
          </div>
          {generationError ? (
            <div style={{ ...warnBanner(), marginTop: 14 }}>
              <b>Generation failed.</b> {generationError.validationError ?? generationError.message}
              {generationError.rawLlmOutput ? <pre style={errorPre()}>{generationError.rawLlmOutput}</pre> : null}
            </div>
          ) : null}
        </StepShell>

        <StepShell n={2} title="Review and edit" active={stepActive(2)} status={draftPriority ? 'generated' : undefined}>
          {draftPriority ? (
            <div style={{ display: 'grid', gap: 14 }}>
              <Field label="Theme">
                <input value={draftPriority.theme} onChange={(event) => updatePriorityField('theme', event.target.value)} style={inputStyle()} />
              </Field>
              <Field label="Rationale">
                <textarea value={draftPriority.rationale} onChange={(event) => updatePriorityField('rationale', event.target.value)} style={textareaStyle(92)} />
              </Field>
              <Field label="Edge hypothesis">
                <textarea value={draftPriority.edge_hypothesis} onChange={(event) => updatePriorityField('edge_hypothesis', event.target.value)} style={textareaStyle(92)} />
              </Field>
              <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: 14 }}>
                <Field label="Priority rank">
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={draftPriority.priority_rank}
                    onChange={(event) => updatePriorityField('priority_rank', Number(event.target.value))}
                    style={inputStyle()}
                  />
                </Field>
                <Field label="Expected edge decay">
                  <select
                    value={draftPriority.expected_edge_decay}
                    onChange={(event) => updatePriorityField('expected_edge_decay', event.target.value)}
                    style={inputStyle()}
                  >
                    {['days', 'weeks', 'months', 'quarters'].map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Sub-questions">
                <textarea value={questionsText} onChange={(event) => setQuestionsText(event.target.value)} style={textareaStyle(110)} />
              </Field>
              <Field label="Supporting evidence">
                <textarea value={evidenceText} onChange={(event) => setEvidenceText(event.target.value)} style={{ ...textareaStyle(150), fontFamily: M.mono, fontSize: 12 }} />
              </Field>
              {approvalError ? <div style={warnBanner()}>{approvalError}</div> : null}
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <button onClick={approve} disabled={!canApprove} style={btnPrimary(!canApprove)}>
                  {busyAction === 'approve' ? 'Saving...' : 'Approve & Save'}
                </button>
                <button onClick={() => setPhase('compose')} style={btnGhost()}>Discard, edit thesis</button>
              </div>
            </div>
          ) : (
            <p style={mutedText()}>Generate a priority before review.</p>
          )}
        </StepShell>

        <StepShell n={3} title="Confirmed" active={stepActive(3)} status={phase === 'confirmed' || phase === 'running' || phase === 'done' ? 'manual priority' : undefined}>
          {phase === 'confirmed' || phase === 'running' || phase === 'done' ? (
            <div style={{ display: 'grid', gap: 14 }}>
              <div style={successBanner()}>
                Saved to manual_research_priorities.yaml. Manual cycle runs use the current manual priority only.
              </div>
              <pre style={yamlBox()}>{MANUAL_CYCLE_COMMAND}</pre>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <button onClick={runManualCycle} disabled={busyAction === 'run' || phase === 'running'} style={btnPrimary(busyAction === 'run' || phase === 'running')}>
                  {busyAction === 'run' ? 'Starting...' : 'Run research cycle with this priority'}
                </button>
                <button onClick={() => loadManualQueue(!showQueue)} disabled={busyAction === 'queue'} style={btnGhost()}>
                  {showQueue ? 'Refresh manual priority' : 'View current manual priority'}
                </button>
              </div>
              {cycleError ? <div style={warnBanner()}>{cycleError}</div> : null}
              {showQueue ? <ManualQueue priorities={manualQueue} /> : null}
            </div>
          ) : null}
        </StepShell>

        <StepShell n={4} title="Cycle progress" active={stepActive(4)} status={phase === 'done' ? 'complete' : phase === 'running' ? 'running...' : undefined}>
          {phase === 'running' || phase === 'done' ? (
            <div>
              {STAGES.map(([name, detail], i) => (
                <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderTop: i ? `1px solid ${M.line}` : 'none' }}>
                  <StageIcon state={stageState[i]} />
                  <span style={{ fontFamily: M.sans, fontSize: '13.5px', fontWeight: 600, color: M.ink }}>{name}</span>
                  <span style={{ marginLeft: 'auto', fontFamily: M.mono, fontSize: 12, color: M.inkFaint }}>
                    {stageState[i] === 'done' ? detail : stageState[i] === 'running' ? 'running...' : 'queued'}
                  </span>
                </div>
              ))}
              {phase === 'done' && draftPriority ? (
                <div style={{ ...successBanner(), marginTop: 14 }}>
                  Cycle complete. Priority &quot;{truncate(draftPriority.theme, 70)}&quot; ran with priority_source=&quot;manual&quot;.
                </div>
              ) : null}
            </div>
          ) : null}
        </StepShell>
      </div>
    </main>
  );
}

function ManualQueue({ priorities }: { priorities: ResearchPriority[] }) {
  if (!priorities.length) return <div style={warnBanner()}>Manual priority file is empty.</div>;
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {priorities.map((priority) => (
        <div key={`${priority.priority_rank}-${priority.theme}`} style={{ background: M.well, border: `1px solid ${M.line}`, borderRadius: 10, padding: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline' }}>
            <div style={{ fontFamily: M.serif, fontSize: 18, color: M.ink }}>{priority.theme}</div>
            <div style={{ fontFamily: M.mono, fontSize: 11, color: M.inkFaint }}>rank {priority.priority_rank}</div>
          </div>
          <div style={{ marginTop: 6, fontFamily: M.sans, fontSize: 12.5, color: M.inkDim }}>
            approved {priority.approved_at ? new Date(priority.approved_at).toLocaleString() : 'date unavailable'}
          </div>
        </div>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label style={{ display: 'grid', gap: 7 }}>
      <span style={{ fontFamily: M.mono, fontSize: 10.5, letterSpacing: '0.12em', textTransform: 'uppercase', color: M.inkFaint, fontWeight: 700 }}>{label}</span>
      {children}
    </label>
  );
}

function StepShell({ n, title, active, status, children }: { n: number; title: string; active: boolean; status?: string; children?: ReactNode }) {
  return (
    <section style={{ background: M.card, border: `1px solid ${active ? M.line2 : M.line}`, borderRadius: 16, overflow: 'hidden', boxShadow: M.shadow, opacity: active ? 1 : 0.48, transition: 'opacity 0.3s, border-color 0.3s' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '17px 22px', borderBottom: `1px solid ${M.line}`, background: 'linear-gradient(180deg, rgba(255,255,255,0.025), rgba(255,255,255,0))' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span style={{ width: 30, height: 30, borderRadius: '50%', background: active ? M.accentSoft : M.well, border: `1px solid ${active ? M.accent : M.line}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: M.mono, fontSize: 12, fontWeight: 600, color: active ? M.accentBright : M.inkFaint }}>{String(n).padStart(2, '0')}</span>
          <span style={{ fontFamily: M.serif, fontSize: 20, fontWeight: 500, color: M.ink }}>{title}</span>
        </span>
        {status ? <span style={{ fontFamily: M.mono, fontSize: 10.5, letterSpacing: '0.1em', color: M.inkFaint, textTransform: 'uppercase' }}>{status}</span> : null}
      </div>
      {children ? <div style={{ padding: 22 }}>{children}</div> : null}
    </section>
  );
}

function StageIcon({ state }: { state: 'queued' | 'running' | 'done' }) {
  if (state === 'done') return <span style={{ width: 20, height: 20, borderRadius: '50%', background: M.pos, flexShrink: 0 }} />;
  if (state === 'running') return <span style={{ width: 20, height: 20, borderRadius: '50%', border: `2px solid ${M.accent}`, borderTopColor: 'transparent', flexShrink: 0, animation: 'helixSpin 0.8s linear infinite' }} />;
  return <span style={{ width: 20, height: 20, borderRadius: '50%', border: `2px solid ${M.line2}`, flexShrink: 0 }} />;
}

function btnPrimary(disabled: boolean): CSSProperties {
  return { background: disabled ? M.line2 : M.accent, color: disabled ? M.inkFaint : '#06172A', border: 'none', borderRadius: 10, padding: '10px 18px', fontFamily: M.mono, fontSize: 12, letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 700, cursor: disabled ? 'default' : 'pointer' };
}

function btnGhost(): CSSProperties {
  return { background: M.well, color: M.inkDim, border: `1px solid ${M.line}`, borderRadius: 10, padding: '10px 18px', fontFamily: M.mono, fontSize: 12, letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 600, cursor: 'pointer' };
}

function inputStyle(): CSSProperties {
  return { width: '100%', background: M.well, border: `1px solid ${M.line}`, borderRadius: 10, padding: '11px 13px', fontFamily: M.sans, fontSize: 14, color: M.ink, outline: 'none' };
}

function textareaStyle(minHeight: number): CSSProperties {
  return { width: '100%', minHeight, resize: 'vertical', background: M.well, border: `1px solid ${M.line}`, borderRadius: 12, padding: 14, fontFamily: M.sans, fontSize: 14, color: M.ink, lineHeight: 1.55, outline: 'none' };
}

function warnBanner(): CSSProperties {
  return { background: `${M.warn}18`, border: `1px solid ${M.warn}55`, borderRadius: 10, padding: '12px 16px', fontFamily: M.sans, fontSize: 13, color: M.warn };
}

function successBanner(): CSSProperties {
  return { background: `${M.pos}18`, border: `1px solid ${M.pos}55`, borderRadius: 10, padding: '12px 16px', fontFamily: M.sans, fontSize: 13, color: M.pos };
}

function yamlBox(): CSSProperties {
  return { background: M.well, border: `1px solid ${M.line}`, borderRadius: 10, padding: 16, fontFamily: M.mono, fontSize: 12.5, lineHeight: 1.7, color: M.inkDim, margin: 0, whiteSpace: 'pre-wrap' };
}

function errorPre(): CSSProperties {
  return { ...yamlBox(), marginTop: 10, color: M.inkDim, maxHeight: 220, overflow: 'auto' };
}

function mutedText(): CSSProperties {
  return { margin: 0, fontFamily: M.sans, fontSize: 13, color: M.inkFaint };
}

function StatusPill({ label }: { label: string }) {
  return (
    <span style={{
      fontFamily: M.mono,
      fontSize: 10.5,
      letterSpacing: '0.12em',
      textTransform: 'uppercase',
      color: M.accentBright,
      background: M.accentSoft,
      border: `1px solid ${M.line2}`,
      borderRadius: 999,
      padding: '7px 11px',
      fontWeight: 600,
    }}>{label}</span>
  );
}

function normalizePriority(priority: ResearchPriority): ResearchPriority {
  return {
    ...priority,
    sub_questions: priority.sub_questions ?? [],
    supporting_evidence: priority.supporting_evidence ?? [],
    source_theme_id: priority.source_theme_id ?? 'free_text',
  };
}

function apiErrorDetail(error: unknown): ApiErrorDetail {
  if (error instanceof ApiRequestError) {
    const detail = nestedDetail(error.detail);
    return {
      message: strField(detail, 'error') || error.message,
      rawLlmOutput: strField(detail, 'raw_llm_output'),
      validationError: strField(detail, 'validation_error'),
    };
  }
  if (error instanceof Error) return { message: error.message };
  return { message: 'Unknown API error' };
}

function nestedDetail(payload: unknown): Record<string, unknown> | null {
  if (!isRecord(payload)) return null;
  const detail = payload.detail;
  if (isRecord(detail)) return detail;
  return payload;
}

function strField(payload: Record<string, unknown> | null, key: string): string | null {
  const value = payload?.[key];
  return typeof value === 'string' ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function safeStr(v: unknown, fb = ''): string { return typeof v === 'string' ? v : fb; }
function truncate(s: string, max = 200): string { return !s || s.length <= max ? s : `${s.slice(0, max).trimEnd()}...`; }
