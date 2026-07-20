'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import useSWR from 'swr';
import AuthRequired from '@/components/AuthRequired';
import {
  Card,
  Chip,
  Collapsible,
  EmptyState,
  MutedLabel,
  PAGE_SHELL,
} from '@/components/helix/primitives';
import { T, formatCurrency } from '@/lib/tokens';
import { useAuthFetcher, useAuthPostFetcher } from '@/lib/api';

type StageStatus = 'pending' | 'running' | 'complete' | 'failed' | 'skipped';

type StageState = {
  stage: string;
  status: StageStatus;
  started_at?: string | null;
  completed_at?: string | null;
  message?: string;
  progress_current?: number | null;
  progress_total?: number | null;
  error?: string | null;
};

type CycleStatus = {
  cycle_id: string;
  started_at: string;
  updated_at: string;
  completed_at?: string | null;
  overall_status: StageStatus;
  stages: StageState[];
  summary_counters?: Record<string, unknown>;
  fatal_error?: string | null;
  user_inputs_preview?: string[];
};

type RecentCycle = {
  cycle_id: string;
  started_at: string;
  completed_at?: string | null;
  overall_status: StageStatus;
  user_inputs_preview?: string[];
};

type CycleResults = {
  cycle_id: string;
  records_by_type: Record<string, SchemaRecord[]>;
  decision_log_entries?: Record<string, unknown>[];
};

type SchemaRecord = {
  id?: string;
  schema_type?: string;
  created_at?: string;
  payload_json?: unknown;
};

type SubmitCycleResponse = {
  cycle_id: string;
};

type ResearchPriorityPayload = {
  theme?: string;
  rationale?: string;
  edge_hypothesis?: string;
  sub_questions?: string[];
  priority_rank?: number;
  expected_edge_decay?: string;
};

type ConvictionPayload = {
  rating?: string;
  rule_applied?: string;
};

type InstrumentPayload = {
  ticker?: string;
  instrument_type?: string | null;
  direction?: string | null;
  description?: string | null;
};

type AlternativePayload = {
  instrument?: InstrumentPayload | null;
  why_rejected?: string | null;
};

type ExpressionPayload = {
  primary_instrument?: InstrumentPayload | null;
  rationale_for_instrument?: string | null;
  alternatives_considered?: AlternativePayload[];
  entry_logic?: string | null;
  exit_stop?: string | null;
  exit_target?: string | null;
  exit_time_stop?: string | null;
};

type ProposedSizingPayload = {
  base_size_pct?: number | null;
};

type FalsifierPayload = {
  condition?: string | null;
  description?: string | null;
};

type TradeIdeaPayload = {
  id?: string | null;
  underlying?: string | null;
  expression?: ExpressionPayload | null;
  proposed_sizing?: ProposedSizingPayload | null;
  combined_conviction?: ConvictionPayload | null;
  research_priority?: ResearchPriorityPayload | null;
  rejection_stage?: string | null;
  rejection_rule_fired?: string | null;
  rejection_reason?: string | null;
  invalidation_thesis?: string | null;
  trade_falsifiers?: FalsifierPayload[];
};

type SizingAdjustmentPayload = {
  step?: string;
  size_before?: number;
  size_after?: number;
  rationale?: string;
};

type PortfolioTradeDecisionPayload = {
  trade_id?: string;
  underlying?: string;
  priority_theme?: string | null;
  proposed_size_pct?: number;
  robustness_score?: number | null;
  robustness_quartile?: number | null;
  scenario_weighted_expected_return?: number | null;
  scenario_weight_source?: string | null;
  scenario_weights_used?: Record<string, number>;
  scenario_weight_warning?: string | null;
  final_size_pct?: number;
  sizing_adjustments?: SizingAdjustmentPayload[];
  decision?: string;
  rationale_summary?: string;
};

type PortfolioPlanPayload = {
  id?: string | null;
  cycle_id?: string;
  nav_unlevered_usd?: number;
  cash_usd?: number;
  trade_decisions?: PortfolioTradeDecisionPayload[];
  total_new_deployment_pct?: number;
  total_new_deployment_usd?: number;
  per_priority_deployment_pct?: Record<string, number>;
  binding_constraints?: string[];
};

const C = {
  bg: T.bg,
  panel: T.surface,
  panel2: T.surfaceMuted,
  panel3: T.surfaceMuted,
  border: T.borderSub,
  border2: T.border,
  text: T.text,
  sub: T.textSub,
  muted: T.textMuted,
  accent: T.accentDark,
  accentSoft: T.accentSoft,
  up: T.up,
  dn: T.dn,
  wa: T.wa,
};

const stageLabels: Record<string, string> = {
  macro_agent: 'Macro agent',
  thematic_agent: 'Thematic agent',
  fundamental_screen: 'Fundamental screen',
  conviction_gate: 'Conviction gate',
  trade_expression: 'Trade expression',
  scenario_scoring: 'Scenario scoring',
  portfolio_construction: 'Portfolio construction',
};

const statusColor: Record<StageStatus, string> = {
  pending: C.muted,
  running: C.accent,
  complete: C.up,
  failed: C.dn,
  skipped: C.muted,
};

const shell: React.CSSProperties = {
  minHeight: '100vh',
  background: C.bg,
  color: C.text,
  fontFamily: T.sans,
};

const page: React.CSSProperties = {
  ...PAGE_SHELL,
  width: 'min(1320px, calc(100% - 48px))',
  gap: '20px',
};

const label: React.CSSProperties = {
  fontFamily: T.sans,
  fontSize: '10px',
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: C.muted,
  fontWeight: 600,
};

const mono: React.CSSProperties = {
  fontFamily: T.mono,
  fontSize: '12px',
  color: C.sub,
};

const panel: React.CSSProperties = {
  background: C.panel,
  border: `1px solid ${C.border}`,
  borderRadius: '14px',
  overflow: 'hidden',
  boxShadow: '0 8px 22px rgba(11,31,51,0.04)',
};

const button: React.CSSProperties = {
  border: `1px solid ${C.border2}`,
  background: C.panel2,
  color: C.text,
  borderRadius: '10px',
  padding: '9px 12px',
  fontFamily: T.sans,
  fontSize: '12px',
  fontWeight: 750,
  cursor: 'pointer',
};

function usePageVisible() {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const onVisibility = () => setVisible(document.visibilityState !== 'hidden');
    onVisibility();
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);
  return visible;
}

function fmtDate(input?: string | null) {
  if (!input) return '—';
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function fmtDuration(start?: string | null, end?: string | null) {
  if (!start || !end) return '—';
  const a = new Date(start).getTime();
  const b = new Date(end).getTime();
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return '—';
  const seconds = Math.round((b - a) / 1000);
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes ? `${minutes}m ${rest}s` : `${rest}s`;
}

function fmtPct(value?: number | null, decimals = 1) {
  if (value === undefined || value === null || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(decimals)}%`;
}

function fmtDecimal(value?: number | null, decimals = 3) {
  if (value === undefined || value === null || Number.isNaN(value)) return '—';
  return value.toFixed(decimals);
}

function fmtScenarioWeights(weights?: Record<string, number>) {
  const entries = Object.entries(weights ?? {});
  if (!entries.length) return '—';
  return entries.map(([scenario, weight]) => `${humanize(scenario)} ${fmtPct(weight, 0)}`).join(' · ');
}

function humanize(value?: string | null) {
  if (!value) return '—';
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function truncate(value: string, max = 90) {
  return value.length > max ? `${value.slice(0, max - 1).trim()}…` : value;
}

function stageProgress(stage: StageState) {
  if (stage.progress_current != null && stage.progress_total != null) {
    return `${stage.progress_current} of ${stage.progress_total}`;
  }
  if (stage.progress_current != null) return String(stage.progress_current);
  return '';
}

function describeApiError(err: unknown) {
  const message = err instanceof Error ? err.message : String(err ?? '');
  if (message.includes('401')) return 'Unauthorized. Clerk auth failed.';
  if (message.includes('403')) {
    return 'Agent-system endpoints are blocked. Enable local dev access or sign in.';
  }
  return message || 'Request failed.';
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function recordsOf<T extends Record<string, unknown>>(
  results: CycleResults | undefined,
  schemaType: string,
): T[] {
  return (
    results?.records_by_type?.[schemaType]
      ?.map((r) => r.payload_json)
      .filter(isObject) as T[] | undefined
  ) ?? [];
}

function latestRecord<T>(records: T[]): T | null {
  return records.length ? records[records.length - 1] : null;
}

function isAcceptedTrade(trade: TradeIdeaPayload) {
  return Boolean(trade?.expression) && !trade?.rejection_stage;
}

function tradeId(trade: TradeIdeaPayload, idx: number) {
  return String(trade.id ?? trade.underlying ?? idx);
}

function numberFrom(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function stringArrayFrom(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function quartileColor(value?: number | null) {
  if (value === 1) return C.dn;
  if (value === 4) return C.up;
  if (value === 2) return C.wa;
  return C.accent;
}

function Section({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card title={title} meta={meta}>
      {children}
    </Card>
  );
}

function Badge({ text, tone = 'neutral' }: { text: string; tone?: 'neutral' | 'good' | 'bad' | 'warn' | 'accent' }) {
  const color =
    tone === 'good' ? C.up : tone === 'bad' ? C.dn : tone === 'warn' ? C.wa : tone === 'accent' ? C.accent : C.sub;
  return <Chip label={text} color={color} />;
}

function RecentCycles({
  cycles,
  activeCycleId,
  onSelect,
}: {
  cycles: RecentCycle[];
  activeCycleId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <Card title="Recent cycles" meta={`${cycles.length} loaded`} padded={false}>
      <div
        style={{
          display: 'flex',
          gap: '10px',
          overflowX: 'auto',
          padding: '14px',
        }}
      >
        {cycles.length === 0 ? (
          <EmptyState msg="No cycles yet. Type inputs to start one." small />
        ) : null}
        {cycles.map((cycle) => {
          const active = cycle.cycle_id === activeCycleId;
          const firstInput = cycle.user_inputs_preview?.[0] ?? 'No input preview';
          return (
            <button
              key={cycle.cycle_id}
              type="button"
              onClick={() => onSelect(cycle.cycle_id)}
              style={{
                flex: '0 0 220px',
                minHeight: '96px',
                textAlign: 'left',
                border: `1px solid ${active ? C.accent : C.border}`,
                borderLeft: `4px solid ${statusColor[cycle.overall_status]}`,
                background: active ? C.accentSoft : 'transparent',
                borderRadius: '14px',
                padding: '12px',
                cursor: 'pointer',
                color: C.text,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                <span style={{ ...mono, color: C.text }}>{fmtDate(cycle.started_at)}</span>
                <span style={{ ...mono, color: statusColor[cycle.overall_status] }}>
                  {cycle.overall_status}
                </span>
              </div>
              <div style={{ marginTop: '7px', color: C.sub, fontSize: '12px', lineHeight: 1.4 }}>
                {truncate(firstInput, 58)}
              </div>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function SubmitForm({ onSubmitted }: { onSubmitted: (id: string) => void }) {
  const postFetcher = useAuthPostFetcher();
  const [rows, setRows] = useState(['']);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const cleanInputs = rows.map((row) => row.trim()).filter(Boolean);
  const canSubmit = cleanInputs.length > 0 && !submitting && postFetcher.isReady;

  const update = (idx: number, value: string) => {
    setRows((prev) => prev.map((row, i) => (i === idx ? value.slice(0, 500) : row)));
  };

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const response = (await postFetcher('/api/cycles/submit', {
        user_inputs: cleanInputs,
      })) as SubmitCycleResponse;
      onSubmitted(response.cycle_id);
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Section title="Run a cycle" meta="free-text inputs">
      <div style={{ display: 'grid', gap: '10px' }}>
        {error ? (
          <div style={{ border: `1px solid ${C.dn}55`, background: `${C.dn}12`, color: C.dn, padding: '10px 12px', borderRadius: '12px', fontSize: '12px' }}>
            {error}
          </div>
        ) : null}
        {rows.map((row, idx) => (
          <div key={idx} style={{ display: 'grid', gridTemplateColumns: '1fr 36px', gap: '8px' }}>
            <div>
              <input
                value={row}
                onChange={(e) => update(idx, e.target.value)}
                placeholder="Dovish pivot beneficiaries"
                style={{
                  width: '100%',
                  height: '40px',
                  borderRadius: '10px',
                  border: `1px solid ${C.border2}`,
                  background: C.panel2,
                  color: C.text,
                  padding: '0 12px',
                  fontFamily: T.sans,
                  fontSize: '13px',
                  outline: 'none',
                }}
              />
              {row.length > 400 ? (
                <div style={{ ...mono, marginTop: '5px', color: row.length >= 500 ? C.dn : C.wa }}>
                  {row.length}/500
                </div>
              ) : null}
            </div>
            <button
              type="button"
              disabled={rows.length === 1}
              onClick={() => setRows((prev) => prev.filter((_, i) => i !== idx))}
              style={{ ...button, opacity: rows.length === 1 ? 0.35 : 1, padding: 0 }}
              aria-label="Remove input"
            >
              X
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <button
            type="button"
            disabled={rows.length >= 10}
            onClick={() => setRows((prev) => (prev.length < 10 ? [...prev, ''] : prev))}
            style={{ ...button, opacity: rows.length >= 10 ? 0.4 : 1 }}
          >
            + Add input
          </button>
          <span style={{ ...mono, color: C.muted }}>
            Estimated cost: ~$3-5 per input (~${cleanInputs.length * 3}-{cleanInputs.length * 5 || 5} total)
          </span>
        </div>
        <button
          type="button"
          disabled={!canSubmit}
          onClick={submit}
          style={{
            ...button,
            width: '160px',
            background: canSubmit ? T.navy : C.panel2,
            color: canSubmit ? T.surface : C.muted,
            borderColor: canSubmit ? T.navy : C.border2,
          }}
        >
          {submitting ? 'Submitting...' : 'Submit'}
        </button>
      </div>
    </Section>
  );
}

function StageTimeline({ status }: { status: CycleStatus }) {
  const [expanded, setExpanded] = useState(false);
  const done = status.overall_status === 'complete';
  const failed = status.overall_status === 'failed';
  const total = fmtDuration(status.started_at, status.completed_at);
  const completeCount = status.stages.filter((s) => s.status === 'complete' || s.status === 'skipped').length;

  if (done && !expanded) {
    return (
      <Section title="Stage progress">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          style={{ ...button, width: '100%', textAlign: 'left' }}
        >
          {completeCount} stages complete · {total} total · expand
        </button>
      </Section>
    );
  }

  return (
    <Section title="Stage progress" meta={failed ? 'failed' : status.overall_status}>
      <div style={{ display: 'grid', gap: '10px' }}>
        {done ? (
          <button type="button" onClick={() => setExpanded(false)} style={{ ...button, width: '120px' }}>
            Collapse
          </button>
        ) : null}
        {status.stages.map((stage) => {
          const progress = stageProgress(stage);
          const running = stage.status === 'running';
          return (
            <div
              key={stage.stage}
              style={{
                display: 'grid',
                gridTemplateColumns: '18px minmax(150px, 0.8fr) minmax(220px, 1.4fr) auto',
                gap: '12px',
                alignItems: 'start',
                padding: '12px',
                border: `1px solid ${C.border}`,
                borderRadius: '14px',
                background: C.panel2,
              }}
            >
              <span
                style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '50%',
                  marginTop: '5px',
                  background: statusColor[stage.status],
                  boxShadow: running ? `0 0 0 7px ${C.accentSoft}` : 'none',
                  animation: running ? 'agentPulse 1.6s ease-in-out infinite' : 'none',
                }}
              />
              <div>
                <div style={{ ...label, color: C.text }}>{stageLabels[stage.stage] ?? humanize(stage.stage)}</div>
                <div style={{ ...mono, marginTop: '4px' }}>
                  {fmtDate(stage.started_at)} {stage.completed_at ? `→ ${fmtDate(stage.completed_at)}` : ''}
                </div>
              </div>
              <div style={{ color: stage.error ? C.dn : C.sub, fontSize: '12.5px', lineHeight: 1.5 }}>
                {stage.error || stage.message || '—'}
              </div>
              <div style={{ ...mono, color: statusColor[stage.status], textTransform: 'uppercase' }}>
                {progress || stage.status}
              </div>
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function InputsPanel({ status }: { status: CycleStatus }) {
  const [expanded, setExpanded] = useState(false);
  const inputs = status.user_inputs_preview ?? [];
  if (!inputs.length) return null;
  return (
    <div style={{ ...panel, padding: '12px 14px', color: C.sub, fontSize: '12px' }}>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        style={{
          display: 'flex',
          width: '100%',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '12px',
          border: 0,
          background: 'transparent',
          color: C.sub,
          padding: 0,
          textAlign: 'left',
          cursor: 'pointer',
        }}
      >
        <span style={label}>Inputs</span>
        <span style={{ ...mono, color: C.muted }}>{expanded ? 'Collapse' : 'Expand'}</span>
      </button>
      {expanded ? (
        <div style={{ display: 'grid', gap: '8px', marginTop: '10px' }}>
          {inputs.map((item, idx) => (
            <div key={`${idx}-${item}`} style={{ background: C.panel2, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '10px 12px', lineHeight: 1.5 }}>
              {item}
            </div>
          ))}
        </div>
      ) : (
        <div style={{ marginTop: '8px', lineHeight: 1.5 }} title={inputs.join('\n')}>
          {inputs.map((item) => truncate(item, 80)).join('  /  ')}
        </div>
      )}
    </div>
  );
}

function PrioritySection({ tradeIdeas }: { tradeIdeas: TradeIdeaPayload[] }) {
  const priority = tradeIdeas.find((trade) => trade?.research_priority)?.research_priority;
  if (!priority) return null;
  return (
    <Section title="Research priority" meta={`rank ${priority.priority_rank ?? '—'} · ${priority.expected_edge_decay ?? '—'}`}>
      <h1 style={{ margin: 0, fontSize: '25px', lineHeight: 1.16, color: C.text, fontWeight: 760 }}>
        {priority.theme}
      </h1>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px', marginTop: '18px' }}>
        <div>
          <div style={label}>Rationale</div>
          <p style={{ color: C.sub, fontSize: '13px', lineHeight: 1.65 }}>{priority.rationale}</p>
        </div>
        <div>
          <div style={label}>Edge hypothesis</div>
          <p style={{ color: C.text, fontSize: '13px', lineHeight: 1.65 }}>{priority.edge_hypothesis}</p>
        </div>
      </div>
      {priority.sub_questions?.length ? (
        <ol style={{ margin: '10px 0 0', paddingLeft: '22px', color: C.sub, fontSize: '12.5px', lineHeight: 1.6 }}>
          {priority.sub_questions.map((question: string) => (
            <li key={question}>{question}</li>
          ))}
        </ol>
      ) : null}
    </Section>
  );
}

function StatStrip({ status, portfolioPlan }: { status?: CycleStatus; portfolioPlan: PortfolioPlanPayload | null }) {
  const counters = status?.summary_counters ?? {};
  const hasDecisions = counters.accepted != null || counters.rejected != null || portfolioPlan;
  if (!hasDecisions) return null;
  const constraints = portfolioPlan?.binding_constraints ?? stringArrayFrom(counters.portfolio_binding_constraints);
  return (
    <Section title="Cycle summary">
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
        <Metric label="Accepted" value={String(numberFrom(counters.accepted) ?? '—')} />
        <Metric label="Rejected" value={String(numberFrom(counters.rejected) ?? '—')} />
        <Metric label="Deployment" value={fmtPct(portfolioPlan?.total_new_deployment_pct ?? numberFrom(counters.portfolio_total_deployment_pct))} />
        <Metric label="Constraints" value={String(constraints.length)} />
      </div>
      {constraints.length ? (
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '12px' }}>
          {constraints.map((constraint: string) => <Badge key={constraint} text={constraint} tone="warn" />)}
        </div>
      ) : null}
    </Section>
  );
}

function Metric({ label: text, value }: { label: string; value: string }) {
  return (
    <div style={{ background: C.panel2, border: `1px solid ${C.border}`, borderRadius: '14px', padding: '14px' }}>
      <MutedLabel>{text}</MutedLabel>
      <div style={{ marginTop: '7px', fontFamily: T.mono, fontSize: '24px', color: C.text }}>{value}</div>
    </div>
  );
}

function AcceptedTrades({ trades, portfolioPlan }: { trades: TradeIdeaPayload[]; portfolioPlan: PortfolioPlanPayload | null }) {
  if (!trades.length) return null;
  const decisions = portfolioPlan?.trade_decisions ?? [];
  const byUnderlying = new Map(
    decisions
      .filter((decision): decision is PortfolioTradeDecisionPayload & { underlying: string } => Boolean(decision.underlying))
      .map((decision) => [decision.underlying, decision]),
  );
  return (
    <Section title="Accepted trades" meta={`${trades.length} trade${trades.length === 1 ? '' : 's'}`}>
      <div style={{ display: 'grid', gap: '10px' }}>
        {trades.map((trade, idx) => (
          <TradeCard
            key={tradeId(trade, idx)}
            trade={trade}
            portfolioDecision={trade.underlying ? byUnderlying.get(trade.underlying) : undefined}
          />
        ))}
      </div>
    </Section>
  );
}

function TradeCard({ trade, portfolioDecision }: { trade: TradeIdeaPayload; portfolioDecision?: PortfolioTradeDecisionPayload }) {
  const expression = trade.expression ?? {};
  const instrument = expression.primary_instrument ?? {};
  const sizing = trade.proposed_sizing ?? {};
  const finalSize = portfolioDecision?.final_size_pct ?? sizing.base_size_pct;
  const decision = portfolioDecision?.decision ? humanize(portfolioDecision.decision) : 'Accepted';
  const adjustments = portfolioDecision?.sizing_adjustments ?? [];
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: '14px', background: C.panel2 }}>
      <div
        style={{
          width: '100%',
          display: 'grid',
          gridTemplateColumns: 'minmax(80px, 0.6fr) minmax(220px, 1.8fr) minmax(110px, 0.8fr) minmax(120px, 0.7fr)',
          gap: '14px',
          alignItems: 'center',
          color: C.text,
          padding: '14px',
          textAlign: 'left',
        }}
      >
        <div style={{ fontFamily: T.mono, fontSize: '26px', color: C.text }}>{trade.underlying}</div>
        <div>
          <div style={{ fontSize: '13px', color: C.text, lineHeight: 1.4 }}>
            {instrument.description ?? instrument.ticker ?? '—'}
          </div>
          <div style={{ ...mono, marginTop: '5px' }}>
            {humanize(trade.combined_conviction?.rating)} · {trade.combined_conviction?.rule_applied ?? '—'}
          </div>
        </div>
        <Badge text={decision} tone={decision.includes('Rejected') ? 'bad' : decision.includes('Reduced') ? 'warn' : 'good'} />
        <div style={{ textAlign: 'right' }}>
          <div style={{ ...label, color: C.muted }}>{portfolioDecision ? 'Final size' : 'Proposed size'}</div>
          <div style={{ fontFamily: T.mono, color: C.text, fontSize: '18px' }}>{fmtPct(finalSize)}</div>
        </div>
      </div>
      <div style={{ borderTop: `1px solid ${C.border}`, padding: '0 14px 14px' }}>
        <Collapsible label="Details">
          <div style={{ display: 'grid', gap: '12px' }}>
            <LabeledProse label="Instrument rationale" value={expression.rationale_for_instrument} />
          <LabeledProse label="Entry" value={expression.entry_logic} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
            <LabeledProse label="Stop" value={expression.exit_stop} />
            <LabeledProse label="Target" value={expression.exit_target} />
          </div>
          <LabeledProse label="Time stop" value={expression.exit_time_stop} />
          <LabeledProse label="Invalidation thesis" value={trade.invalidation_thesis} />
          {trade.trade_falsifiers?.length ? (
            <div>
              <div style={label}>Falsifiers</div>
              <ol style={{ margin: '8px 0 0', paddingLeft: '20px', color: C.sub, fontSize: '12.5px', lineHeight: 1.55 }}>
                {trade.trade_falsifiers.map((f, idx) => (
                  <li key={`${f.condition ?? idx}-${idx}`}>
                    {f.condition ?? f.description ?? JSON.stringify(f)}
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
          {expression.alternatives_considered?.length ? (
            <div>
              <MutedLabel>Alternatives considered</MutedLabel>
              <div style={{ display: 'grid', gap: '8px' }}>
                {expression.alternatives_considered.map((alt, idx) => {
                  const altInstrument = alt.instrument;
                  const description = altInstrument?.description
                    || altInstrument?.instrument_type
                    || altInstrument?.ticker
                    || 'Alternative expression';
                  return (
                    <div key={`${description}-${idx}`} style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '10px 12px' }}>
                      <div style={{ color: C.text, fontSize: '12.5px', lineHeight: 1.45 }}>
                        {description}
                      </div>
                      <div style={{ color: C.sub, fontSize: '12px', lineHeight: 1.5, marginTop: '4px' }}>
                        {alt.why_rejected ?? 'No rejection rationale provided.'}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}
          {portfolioDecision ? (
            <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: '12px', padding: '12px', display: 'grid', gap: '8px' }}>
              <MutedLabel>Robustness</MutedLabel>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ fontFamily: T.mono, color: C.text, fontSize: '15px' }}>
                  {fmtDecimal(portfolioDecision.robustness_score)}
                </span>
                {portfolioDecision.robustness_quartile != null ? (
                  <Chip
                    label={`Q${portfolioDecision.robustness_quartile}`}
                    color={quartileColor(portfolioDecision.robustness_quartile)}
                  />
                ) : null}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px' }}>
                <div>
                  <div style={label}>Scenario-weighted exp. return</div>
                  <div style={{ fontFamily: T.mono, color: C.text }}>{fmtPct(portfolioDecision.scenario_weighted_expected_return)}</div>
                </div>
                <div>
                  <div style={label}>Scenario weight source</div>
                  <div style={{ fontFamily: T.mono, color: C.text }}>{humanize(portfolioDecision.scenario_weight_source)}</div>
                </div>
              </div>
              <div style={{ color: C.sub, fontSize: '12px', lineHeight: 1.45 }}>
                {fmtScenarioWeights(portfolioDecision.scenario_weights_used)}
              </div>
              {portfolioDecision.scenario_weight_warning ? (
                <div style={{ color: C.wa, fontSize: '12px', lineHeight: 1.45 }}>
                  {portfolioDecision.scenario_weight_warning}
                </div>
              ) : null}
              {adjustments.map((adj) => (
                <div
                  key={`${adj.step}-${adj.size_before}-${adj.size_after}`}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'minmax(120px, 0.6fr) minmax(120px, 0.5fr) minmax(220px, 1fr)',
                    gap: '10px',
                    color: C.sub,
                    fontSize: '12px',
                    lineHeight: 1.45,
                  }}
                >
                  <span style={{ color: C.text }}>{humanize(adj.step)}</span>
                  <span style={{ fontFamily: T.mono }}>{fmtPct(adj.size_before)} → {fmtPct(adj.size_after)}</span>
                  <span>{adj.rationale}</span>
                </div>
              ))}
            </div>
          ) : null}
          </div>
        </Collapsible>
      </div>
    </div>
  );
}

function LabeledProse({ label: text, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div>
      <MutedLabel>{text}</MutedLabel>
      <p style={{ margin: '7px 0 0', color: C.sub, fontSize: '12.5px', lineHeight: 1.58 }}>{value}</p>
    </div>
  );
}

function RejectedCandidates({ trades }: { trades: TradeIdeaPayload[] }) {
  if (!trades.length) return null;
  return (
    <Section title={`Rejected candidates (${trades.length})`}>
      <Collapsible label="Rejected candidates" count={trades.length}>
        <div style={{ display: 'grid', gap: '8px', marginTop: '12px' }}>
          {trades.map((trade, idx) => (
            <div key={tradeId(trade, idx)} style={{ display: 'grid', gridTemplateColumns: 'minmax(70px, 0.4fr) minmax(160px, 0.8fr) minmax(220px, 1.8fr)', gap: '12px', padding: '10px 0', borderBottom: `1px solid ${C.border}` }}>
              <div style={{ fontFamily: T.mono, color: C.text }}>{trade.underlying}</div>
              <div style={mono}>{humanize(trade.rejection_stage)} · {trade.rejection_rule_fired ?? '—'}</div>
              <div style={{ color: C.sub, fontSize: '12.5px', lineHeight: 1.45 }}>{trade.rejection_reason ?? '—'}</div>
            </div>
          ))}
        </div>
      </Collapsible>
    </Section>
  );
}

function PortfolioPlanSection({ plan, terminalText }: { plan: PortfolioPlanPayload | null; terminalText?: unknown }) {
  const [mode, setMode] = useState<'detail' | 'terminal'>('detail');
  if (!plan) return null;
  const perPriorityDeployment = plan.per_priority_deployment_pct ?? {};
  return (
    <Section title="Portfolio plan" meta={plan.cycle_id}>
      <div style={{ display: 'flex', gap: '8px', marginBottom: '14px' }}>
        <button type="button" onClick={() => setMode('detail')} style={{ ...button, background: mode === 'detail' ? C.accentSoft : C.panel2 }}>
          Detail view
        </button>
        <button type="button" onClick={() => setMode('terminal')} style={{ ...button, background: mode === 'terminal' ? C.accentSoft : C.panel2 }}>
          Terminal view
        </button>
      </div>
      {mode === 'terminal' ? (
        <pre style={{ margin: 0, overflowX: 'auto', color: C.sub, fontFamily: T.mono, fontSize: '12px', lineHeight: 1.55 }}>
          {typeof terminalText === 'string' && terminalText ? terminalText : JSON.stringify(plan, null, 2)}
        </pre>
      ) : (
        <div style={{ display: 'grid', gap: '14px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px' }}>
            <Metric label="NAV" value={formatCurrency(plan.nav_unlevered_usd, 0)} />
            <Metric label="Cash" value={formatCurrency(plan.cash_usd, 0)} />
            <Metric label="Deployment $" value={formatCurrency(plan.total_new_deployment_usd, 0)} />
            <Metric label="Deployment %" value={fmtPct(plan.total_new_deployment_pct)} />
          </div>
          {Object.keys(perPriorityDeployment).length ? (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {Object.entries(perPriorityDeployment).map(([priority, value]) => (
                  <tr key={priority}>
                    <td style={{ padding: '9px 0', color: C.sub, fontSize: '12.5px', borderBottom: `1px solid ${C.border}` }}>{priority}</td>
                    <td style={{ padding: '9px 0', textAlign: 'right', fontFamily: T.mono, color: C.text, borderBottom: `1px solid ${C.border}` }}>{fmtPct(value as number)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {plan.binding_constraints?.length ? (
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
              {plan.binding_constraints.map((constraint: string) => <Badge key={constraint} text={constraint} tone="warn" />)}
            </div>
          ) : null}
        </div>
      )}
    </Section>
  );
}

function FailedCycle({ status }: { status?: CycleStatus }) {
  if (status?.overall_status !== 'failed') return null;
  return (
    <Section title="Failed cycle" meta="fatal error">
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', color: C.dn, fontFamily: T.mono, fontSize: '12px', lineHeight: 1.55 }}>
        {status.fatal_error ?? 'Cycle failed without a fatal_error payload.'}
      </pre>
    </Section>
  );
}

function ActiveCycleView({
  cycleId,
  status,
  results,
}: {
  cycleId: string;
  status?: CycleStatus;
  results?: CycleResults;
}) {
  const tradeIdeas = recordsOf(results, 'TradeIdea');
  const portfolioPlan = latestRecord(recordsOf(results, 'PortfolioPlan'));
  const accepted = tradeIdeas.filter(isAcceptedTrade);
  const rejected = tradeIdeas.filter((trade) => !isAcceptedTrade(trade));
  const terminalText = status?.summary_counters?._portfolio_summary_text;

  return (
    <div style={{ display: 'grid', gap: '16px' }}>
      {status ? <InputsPanel status={status} /> : null}
      {status ? <StageTimeline status={status} /> : (
        <Section title="Stage progress" meta={cycleId}>
          <div style={{ color: C.sub, fontSize: '13px' }}>Waiting for status file…</div>
        </Section>
      )}
      <PrioritySection tradeIdeas={tradeIdeas} />
      <StatStrip status={status} portfolioPlan={portfolioPlan} />
      <AcceptedTrades trades={accepted} portfolioPlan={portfolioPlan} />
      <RejectedCandidates trades={rejected} />
      <PortfolioPlanSection plan={portfolioPlan} terminalText={terminalText} />
      <FailedCycle status={status} />
    </div>
  );
}

function AgentSystemClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const authFetcher = useAuthFetcher();
  const visible = usePageVisible();
  const cycleId = searchParams.get('cycle');
  const completionRefetchedRef = useRef<string | null>(null);

  const recent = useSWR<{ cycles: RecentCycle[] }>(
    authFetcher.isReady ? '/api/cycles/recent?limit=10' : null,
    authFetcher,
    {
      refreshInterval: (data) => (
        visible && data?.cycles?.some((cycle) => cycle.overall_status === 'running') ? 5000 : 0
      ),
      revalidateOnFocus: true,
    }
  );

  const status = useSWR<CycleStatus>(
    authFetcher.isReady && cycleId ? `/api/cycles/${cycleId}/status` : null,
    authFetcher,
    {
      refreshInterval: (data) => (visible && data?.overall_status === 'running' ? 2000 : 0),
      revalidateOnFocus: true,
    }
  );

  const results = useSWR<CycleResults>(
    authFetcher.isReady && cycleId ? `/api/cycles/${cycleId}/results` : null,
    authFetcher,
    {
      refreshInterval: () => (visible && status.data?.overall_status === 'running' ? 10000 : 0),
      revalidateOnFocus: true,
    }
  );

  useEffect(() => {
    if (!cycleId || !status.data) return;
    if (
      (status.data.overall_status === 'complete' || status.data.overall_status === 'failed') &&
      completionRefetchedRef.current !== cycleId
    ) {
      completionRefetchedRef.current = cycleId;
      void results.mutate();
      void recent.mutate();
    }
  }, [cycleId, recent, results, status.data]);

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  const cycles = recent.data?.cycles ?? [];
  const statusError = status.error ? describeApiError(status.error) : null;
  const resultsError = results.error ? describeApiError(results.error) : null;

  return (
    <main style={shell}>
      <style>{`
        @keyframes agentPulse {
          0% { opacity: 0.45; transform: scale(0.92); }
          50% { opacity: 1; transform: scale(1); }
          100% { opacity: 0.45; transform: scale(0.92); }
        }
      `}</style>
      <div style={page}>
        <header style={{ marginBottom: '22px' }}>
          <div style={{ ...label, color: C.accent }}>Agent system</div>
          <div style={{ marginTop: '8px', color: C.sub, fontSize: '13px' }}>
            research cycle: input → priorities → trades → plan
          </div>
        </header>

        <div style={{ display: 'grid', gap: '18px' }}>
          <RecentCycles
            cycles={cycles}
            activeCycleId={cycleId}
            onSelect={(id) => router.push(`/agent-system?cycle=${encodeURIComponent(id)}`)}
          />

          <div style={{ display: 'grid', gap: '18px' }}>
            {!cycleId ? (
              <SubmitForm onSubmitted={(id) => router.push(`/agent-system?cycle=${encodeURIComponent(id)}`)} />
            ) : (
              <>
                <div style={{ ...panel, padding: '12px 14px', display: 'flex', justifyContent: 'space-between', gap: '14px', alignItems: 'center' }}>
                  <div>
                    <div style={label}>Active cycle</div>
                    <div style={{ ...mono, marginTop: '4px', color: C.text }}>{cycleId}</div>
                  </div>
                  <button type="button" style={button} onClick={() => router.push('/agent-system')}>
                    New cycle
                  </button>
                </div>
                {statusError ? (
                  <div style={{ ...panel, padding: '14px', color: C.dn, fontSize: '13px' }}>{statusError}</div>
                ) : null}
                {resultsError ? (
                  <div style={{ ...panel, padding: '14px', color: C.wa, fontSize: '13px' }}>{resultsError}</div>
                ) : null}
                <ActiveCycleView cycleId={cycleId} status={status.data} results={results.data} />
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

export default function AgentSystemPage() {
  return (
    <Suspense
      fallback={
        <main style={shell}>
          <div style={page}>
            <div style={{ ...panel, padding: '18px', color: C.sub, fontFamily: T.sans }}>
              Loading agent system...
            </div>
          </div>
        </main>
      }
    >
      <AgentSystemClient />
    </Suspense>
  );
}
