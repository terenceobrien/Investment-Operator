'use client';

import { useMemo, useState } from 'react';
import useSWR from 'swr';
import AuthRequired from '@/components/AuthRequired';
import { T, formatAccountingPct, formatRelativeAge, sx } from '@/lib/tokens';
import { useAuthFetcher, useAuthPostFetcher } from '@/lib/api';

type AgentSystemSummary = {
  has_data: boolean;
  latest_cycle_id?: string;
  last_run_at?: string;
  accepted?: number;
  rejected?: number;
  candidates_considered?: number;
  accepted_underlyings?: string[];
  rejected_underlyings?: string[];
  storage_path?: string;
  message?: string;
  dev_endpoint_enabled?: boolean;
};

type PortfolioConstraintSummary = {
  allowed: boolean;
  hard_block: boolean;
  reasoning: string;
};

type DecisionLogEntry = {
  timestamp: string;
  cycle_id: string;
  candidate: string;
  decision: 'accepted' | 'rejected' | string;
  conviction_rating: string;
  rule_applied: string;
  weakest_link: string;
  summary: string;
  trade_idea_id?: string;
  portfolio_constraint?: PortfolioConstraintSummary;
  review_notes?: string;
};

type TradeIdeaListItem = {
  id: string;
  created_at: string;
  underlying: string;
  conviction_rating: string;
  rule_applied: string;
  weakest_link: string;
  is_accepted: boolean;
  rejection_reason?: string | null;
  rejection_stage?: string | null;
  expected_holding_period?: string | null;
  primary_instrument?: string | null;
  direction?: string | null;
  base_size_pct?: number | null;
  max_loss_estimate_pct?: number | null;
  thesis?: string | null;
  invalidation_thesis?: string | null;
  falsifiers_count?: number;
};

type TradeIdeaDetail = {
  trade_idea: Record<string, unknown>;
  decision_log_entry?: DecisionLogEntry | null;
};

const cap = (value?: string | null) => {
  if (!value) return '—';
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
};

const pct = (value?: number | null) => {
  if (value === undefined || value === null) return '—';
  return formatAccountingPct(value * 100, 1);
};

function StatusBadge({ accepted }: { accepted: boolean }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        borderRadius: '999px',
        padding: '4px 9px',
        background: accepted ? `${T.up}12` : `${T.dn}10`,
        border: `1px solid ${accepted ? `${T.up}35` : `${T.dn}28`}`,
        color: accepted ? T.up : T.dn,
        fontFamily: T.sans,
        fontSize: '11px',
        fontWeight: 700,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
      }}
    >
      {accepted ? 'Accepted' : 'Rejected'}
    </span>
  );
}

function SummaryCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div style={{ ...sx.subPanel, padding: '16px 18px' }}>
      <div style={{ ...sx.sectionMeta, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '8px' }}>
        {label}
      </div>
      <div style={{ fontFamily: T.sans, fontSize: '26px', lineHeight: 1, fontWeight: 650, color: T.navy }}>
        {value}
      </div>
      {sub ? (
        <div style={{ marginTop: '8px', fontFamily: T.sans, fontSize: '12px', lineHeight: 1.45, color: T.textMuted }}>
          {sub}
        </div>
      ) : null}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <section style={sx.panel}>
      <div style={{ ...sx.panelBody, paddingTop: '42px', paddingBottom: '42px', textAlign: 'center' }}>
        <div style={{ fontFamily: T.sans, fontSize: '14px', color: T.textSub, lineHeight: 1.6 }}>
          {message}
        </div>
        <div style={{ marginTop: '8px', fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>
          Run <span style={{ color: T.navy }}>python -m agent_system.orchestration.run_research_cycle</span> locally, or enable the dev endpoint.
        </div>
      </div>
    </section>
  );
}

function TradeTable({
  title,
  items,
  mode,
  onSelect,
}: {
  title: string;
  items: TradeIdeaListItem[];
  mode: 'accepted' | 'rejected';
  onSelect: (id: string) => void;
}) {
  return (
    <section style={sx.panel}>
      <div style={sx.panelHeader}>
        <span style={sx.sectionLabel}>{title}</span>
        <span style={sx.sectionMeta}>{items.length} ideas</span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: mode === 'accepted' ? '1040px' : '920px' }}>
          <thead>
            <tr>
              {(mode === 'accepted'
                ? ['Underlying', 'Conviction', 'Rule applied', 'Size', 'Direction', 'Holding period', 'Max loss', 'Invalidation thesis', 'Falsifiers']
                : ['Underlying', 'Conviction', 'Rule applied', 'Weakest link', 'Rejection stage', 'Rejection reason']
              ).map((h) => (
                <th key={h} style={{ padding: '12px 14px', textAlign: 'left', borderBottom: `1px solid ${T.borderSub}`, fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase', color: T.textMuted }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} onClick={() => onSelect(item.id)} style={{ cursor: 'pointer' }}>
                <td style={tdStrong}>{item.underlying}</td>
                <td style={td}><StatusBadge accepted={item.is_accepted} /></td>
                <td style={tdMono}>{item.rule_applied}</td>
                {mode === 'accepted' ? (
                  <>
                    <td style={tdMono}>{pct(item.base_size_pct)}</td>
                    <td style={td}>{cap(item.direction)}</td>
                    <td style={td}>{item.expected_holding_period ?? '—'}</td>
                    <td style={tdMono}>{pct(item.max_loss_estimate_pct)}</td>
                    <td style={{ ...td, maxWidth: '320px' }}>{item.invalidation_thesis ?? '—'}</td>
                    <td style={tdMono}>{item.falsifiers_count ?? 0}</td>
                  </>
                ) : (
                  <>
                    <td style={td}>{cap(item.weakest_link)}</td>
                    <td style={td}>{cap(item.rejection_stage)}</td>
                    <td style={{ ...td, maxWidth: '520px' }}>{item.rejection_reason ?? '—'}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const td: React.CSSProperties = {
  padding: '13px 14px',
  borderBottom: `1px solid ${T.borderSub}`,
  fontFamily: T.sans,
  fontSize: '12.5px',
  lineHeight: 1.45,
  color: T.textSub,
  verticalAlign: 'top',
};

const tdStrong: React.CSSProperties = {
  ...td,
  color: T.navy,
  fontWeight: 750,
  letterSpacing: '0.02em',
};

const tdMono: React.CSSProperties = {
  ...td,
  fontFamily: T.mono,
  fontSize: '11.5px',
  color: T.text,
};

function DecisionLog({ decisions }: { decisions: DecisionLogEntry[] }) {
  return (
    <section style={sx.panel}>
      <div style={sx.panelHeader}>
        <span style={sx.sectionLabel}>Decision log</span>
        <span style={sx.sectionMeta}>Most recent entries</span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '980px' }}>
          <thead>
            <tr>
              {['Time', 'Candidate', 'Decision', 'Conviction', 'Rule', 'Portfolio allowed?', 'Constraint reasoning'].map((h) => (
                <th key={h} style={{ padding: '12px 14px', textAlign: 'left', borderBottom: `1px solid ${T.borderSub}`, fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase', color: T.textMuted }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {decisions.slice(0, 24).map((entry, idx) => (
              <tr key={`${entry.trade_idea_id ?? entry.candidate}-${entry.timestamp}-${idx}`}>
                <td style={tdMono}>{formatRelativeAge(entry.timestamp)}</td>
                <td style={tdStrong}>{entry.candidate}</td>
                <td style={td}><StatusBadge accepted={entry.decision === 'accepted'} /></td>
                <td style={td}>{cap(entry.conviction_rating)}</td>
                <td style={tdMono}>{entry.rule_applied}</td>
                <td style={td}>{entry.portfolio_constraint?.allowed ? 'Yes' : 'No'}</td>
                <td style={{ ...td, maxWidth: '420px' }}>{entry.portfolio_constraint?.reasoning ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DetailPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const authFetcher = useAuthFetcher();
  const { data, isLoading, error } = useSWR<TradeIdeaDetail>(
    authFetcher.isReady ? `/api/agent-system/trade-ideas/${id}` : null,
    authFetcher,
    { revalidateOnFocus: false }
  );

  const trade = data?.trade_idea;
  const fundamental = trade?.fundamental as Record<string, unknown> | undefined;
  const narrative = trade?.narrative as Record<string, unknown> | undefined;
  const currentNarrative = narrative?.current_narrative as Record<string, unknown> | undefined;
  const researchPriority = trade?.research_priority as Record<string, unknown> | undefined;

  return (
    <section style={sx.panel}>
      <div style={sx.panelHeader}>
        <span style={sx.sectionLabel}>Audit trail</span>
        <button type="button" onClick={onClose} style={ghostButton}>Close</button>
      </div>
      <div style={{ ...sx.panelBody, display: 'grid', gap: '16px' }}>
        {isLoading ? <div style={td}>Loading detail…</div> : null}
        {error ? <div style={{ ...td, color: T.dn }}>Unable to load trade detail.</div> : null}
        {trade ? (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px,1fr))', gap: '12px' }}>
              <MiniBlock label="Thesis statement" value={String(fundamental?.thesis_statement ?? '—')} />
              <MiniBlock label="Narrative summary" value={String(currentNarrative?.summary ?? '—')} />
              <MiniBlock label="Research priority" value={String(researchPriority?.theme ?? '—')} />
              <MiniBlock label="Invalidation thesis" value={String(trade.invalidation_thesis ?? trade.rejection_reason ?? '—')} />
            </div>
            <details style={{ ...sx.subPanel, padding: '14px 16px' }}>
              <summary style={{ cursor: 'pointer', fontFamily: T.sans, fontSize: '12px', fontWeight: 700, color: T.navy }}>
                Raw JSON
              </summary>
              <pre style={{ margin: '14px 0 0', overflowX: 'auto', fontFamily: T.mono, fontSize: '11px', lineHeight: 1.6, color: T.textSub }}>
                {JSON.stringify(data, null, 2)}
              </pre>
            </details>
          </>
        ) : null}
      </div>
    </section>
  );
}

function MiniBlock({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ ...sx.subPanel, padding: '14px 16px' }}>
      <div style={{ ...sx.sectionMeta, textTransform: 'uppercase', letterSpacing: '0.09em', marginBottom: '8px' }}>
        {label}
      </div>
      <div style={{ fontFamily: T.sans, fontSize: '13px', lineHeight: 1.6, color: T.textSub }}>
        {value}
      </div>
    </div>
  );
}

const ghostButton: React.CSSProperties = {
  border: `1px solid ${T.border}`,
  background: T.surface,
  borderRadius: '11px',
  color: T.navy,
  padding: '8px 12px',
  fontFamily: T.sans,
  fontSize: '12px',
  fontWeight: 700,
  cursor: 'pointer',
};

export default function AgentSystemPage() {
  const authFetcher = useAuthFetcher();
  const postFetcher = useAuthPostFetcher();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const canFetch = authFetcher.isReady;

  const summary = useSWR<AgentSystemSummary>(canFetch ? '/api/agent-system/summary' : null, authFetcher, { revalidateOnFocus: false });
  const trades = useSWR<TradeIdeaListItem[]>(canFetch ? '/api/agent-system/trade-ideas' : null, authFetcher, { revalidateOnFocus: false });
  const decisions = useSWR<DecisionLogEntry[]>(canFetch ? '/api/agent-system/decisions' : null, authFetcher, { revalidateOnFocus: false });

  const accepted = useMemo(() => (trades.data ?? []).filter((item) => item.is_accepted), [trades.data]);
  const rejected = useMemo(() => (trades.data ?? []).filter((item) => !item.is_accepted), [trades.data]);

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  const refreshAll = async () => {
    await Promise.all([summary.mutate(), trades.mutate(), decisions.mutate()]);
  };

  const runStubCycle = async () => {
    setRunning(true);
    setRunError(null);
    try {
      await postFetcher('/api/agent-system/run-stub-cycle', {});
      await refreshAll();
    } catch (err) {
      setRunError(err instanceof Error ? err.message : 'Unable to run stub cycle');
    } finally {
      setRunning(false);
    }
  };

  const hasData = summary.data?.has_data;

  return (
    <main style={sx.main}>
      <div style={sx.pageShell}>
        <section style={sx.panel}>
          <div style={{ ...sx.panelHeader, alignItems: 'flex-start' }}>
            <div>
              <span style={sx.sectionLabel}>Agent System Review</span>
              <p style={{ margin: '8px 0 0', fontFamily: T.sans, fontSize: '14px', color: T.textSub }}>
                Inspect accepted and rejected research outputs from the Helix agent spine.
              </p>
            </div>
            <button type="button" onClick={runStubCycle} disabled={running} style={{ ...ghostButton, opacity: running ? 0.6 : 1 }}>
              {running ? 'Running…' : 'Run stub cycle'}
            </button>
          </div>
          {runError ? (
            <div style={{ padding: '10px 18px', borderTop: `1px solid ${T.borderSub}`, fontFamily: T.sans, fontSize: '12px', color: T.wa }}>
              {runError}
            </div>
          ) : null}
        </section>

        {summary.isLoading || trades.isLoading || decisions.isLoading ? (
          <section style={sx.panel}>
            <div style={{ ...sx.panelBody, fontFamily: T.sans, color: T.textMuted }}>Loading agent-system records…</div>
          </section>
        ) : null}

        {summary.error || trades.error || decisions.error ? (
          <section style={sx.panel}>
            <div style={{ ...sx.panelBody, color: T.dn, fontFamily: T.sans }}>Error loading agent-system outputs.</div>
          </section>
        ) : null}

        {summary.data && !hasData ? (
          <EmptyState message={summary.data.message ?? 'No agent-system data found.'} />
        ) : null}

        {summary.data && hasData ? (
          <>
            <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))', gap: '14px' }}>
              <SummaryCard label="Latest cycle" value={(summary.data.latest_cycle_id ?? '—').slice(0, 8)} sub={summary.data.latest_cycle_id} />
              <SummaryCard label="Last run" value={formatRelativeAge(summary.data.last_run_at)} sub={summary.data.last_run_at} />
              <SummaryCard label="Accepted" value={summary.data.accepted ?? 0} sub={(summary.data.accepted_underlyings ?? []).join(', ') || '—'} />
              <SummaryCard label="Rejected" value={summary.data.rejected ?? 0} sub={(summary.data.rejected_underlyings ?? []).join(', ') || '—'} />
              <SummaryCard label="Candidates" value={summary.data.candidates_considered ?? 0} sub="Latest cycle" />
              <SummaryCard label="Storage" value="JSONL" sub={summary.data.storage_path ?? 'data/agent_system'} />
            </section>

            <TradeTable title="Accepted trade ideas" items={accepted} mode="accepted" onSelect={setSelectedId} />
            <TradeTable title="Rejected trade ideas" items={rejected} mode="rejected" onSelect={setSelectedId} />
            <DecisionLog decisions={decisions.data ?? []} />
            {selectedId ? <DetailPanel id={selectedId} onClose={() => setSelectedId(null)} /> : null}
          </>
        ) : null}
      </div>
    </main>
  );
}
