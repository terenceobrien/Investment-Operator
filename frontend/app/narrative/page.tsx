'use client';

import { useEffect, useState } from 'react';
import useSWR from 'swr';
import { useAuth } from '@clerk/nextjs';
import { useAuthFetcher } from '../../lib/api';
import { T, sx } from '@/lib/tokens';

// ─────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────
type AnyRecord = Record<string, unknown>;

// ─────────────────────────────────────────────────────────────
// Generic helpers
// ─────────────────────────────────────────────────────────────
function safeArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}
function safeStr(v: unknown, fallback = ''): string {
  return typeof v === 'string' ? v : fallback;
}
function safeNum(v: unknown): number | null {
  const n = Number(v);
  return isFinite(n) ? n : null;
}
function truncate(s: string, max = 200): string {
  if (!s || s.length <= max) return s;
  return s.slice(0, max).trimEnd() + '…';
}
function firstNonEmpty(...vals: unknown[]): string {
  for (const v of vals) if (typeof v === 'string' && v.trim()) return v.trim();
  return '';
}
function formatPct(v: unknown): string {
  const n = safeNum(v);
  if (n === null) return '—';
  const abs = Math.abs(n).toFixed(2) + '%';
  return n < 0 ? `(${abs})` : `+${abs}`;
}
function pctColor(v: unknown): string {
  const n = safeNum(v);
  if (n === null) return T.textMuted;
  return n > 0 ? T.up : n < 0 ? T.dn : T.textMuted;
}
function parsePrefixedText(text: string): Record<string, string> {
  const prefixes = ['REALITY', 'STORY', 'PRICE', 'TIMEFRAME', 'GAP', 'ARCHETYPE', 'FALSIFIER'];
  const out: Record<string, string> = {};
  const rest = text;
  for (const p of prefixes) {
    const re = new RegExp(`${p}[:\\s]+([\\s\\S]*?)(?=${prefixes.filter(x => x !== p).join('|')}|$)`, 'i');
    const m = rest.match(re);
    if (m?.[1]?.trim()) out[p] = m[1].trim();
  }
  return out;
}
function ledgersFromMeta(meta: AnyRecord): AnyRecord {
  return (meta?.information_ledgers as AnyRecord) ?? {};
}
function findPriceLedgerEntry(priceLedger: unknown[], type: string): AnyRecord | null {
  for (const entry of priceLedger) {
    const e = entry as AnyRecord;
    if (e.type === type || e.kind === type) return e;
  }
  return null;
}
function priceLedgerItems(entry: AnyRecord | null): unknown[] {
  if (!entry) return [];
  const items = entry.items as AnyRecord | undefined;
  if (!items) return [];
  return safeArray(items.all ?? items.items ?? []);
}
function getReturn1D(asset: AnyRecord): number | null {
  const rets = asset.returns as Record<string, unknown> | undefined;
  if (rets) return safeNum(rets['1D']);
  return safeNum(asset.return);
}
function getReturns(asset: AnyRecord): Record<string, number | null> {
  const rets = asset.returns as Record<string, unknown> | undefined;
  if (rets) {
    const out: Record<string, number | null> = {};
    for (const [k, v] of Object.entries(rets)) out[k] = safeNum(v);
    return out;
  }
  const r = safeNum(asset.return);
  return { '1D': r };
}

// ─────────────────────────────────────────────────────────────
// Data extraction helpers
// ─────────────────────────────────────────────────────────────
function extractRegimeSnapshot(data: AnyRecord) {
  const meta = (data._meta ?? {}) as AnyRecord;
  const narratives = safeArray<AnyRecord>(data.dominant_narratives);
  const takeaways = safeArray<string>(data.raw_takeaways);
  const summary = safeStr(data.one_paragraph_summary);

  const archetype = firstNonEmpty(
    narratives.find(n => safeStr(n.archetype))?.archetype,
    takeaways.find(t => /ARCHETYPE/i.test(t))?.replace(/.*ARCHETYPE[:\s]*/i, '').split('\n')[0],
  );
  const gap = firstNonEmpty(
    narratives.find(n => safeStr(n.gap))?.gap,
    takeaways.find(t => /GAP/i.test(t))?.replace(/.*GAP[:\s]*/i, '').split('\n')[0],
  );
  const confidence = firstNonEmpty(
    safeStr(narratives[0]?.confidence),
    meta.confidence as string,
  );
  const stance = firstNonEmpty(safeStr(narratives[0]?.stance));

  return { summary, archetype, gap, confidence, stance };
}

function extractLedgerCounts(data: AnyRecord) {
  const meta = (data._meta ?? {}) as AnyRecord;
  const lc = (meta.ledger_counts ?? {}) as AnyRecord;
  const ledgers = ledgersFromMeta(meta);
  const get = (key: string) =>
    safeNum(lc[key]) ?? safeArray(safeArray<AnyRecord>(ledgers[key] as unknown)).length ?? 0;
  return {
    total: safeNum(meta.total_items_in_bundle) ?? 0,
    selected: safeNum(meta.items_selected_for_llm) ?? 0,
    fundamental: get('fundamental_ledger'),
    policy: get('policy_ledger'),
    narrative: get('narrative_ledger'),
    price: get('price_ledger'),
    alternative: get('alternative_views_ledger'),
    uncategorized: get('uncategorized'),
    filtered: safeNum((meta.filtered_items_summary as AnyRecord)?.count) ?? 0,
  };
}

function getRealityEvidence(data: AnyRecord): AnyRecord[] {
  const meta = (data._meta ?? {}) as AnyRecord;
  const ledgers = ledgersFromMeta(meta);
  return [
    ...safeArray<AnyRecord>(ledgers.policy_ledger as unknown),
    ...safeArray<AnyRecord>(ledgers.fundamental_ledger as unknown).filter(i => !i.is_duplicate_fundamental),
  ].slice(0, 6);
}

function getStoryEvidence(data: AnyRecord): AnyRecord[] {
  const meta = (data._meta ?? {}) as AnyRecord;
  const ledgers = ledgersFromMeta(meta);
  return safeArray<AnyRecord>(ledgers.narrative_ledger as unknown).slice(0, 6);
}

function getPriceLedgerEntries(data: AnyRecord): unknown[] {
  const meta = (data._meta ?? {}) as AnyRecord;
  const ledgers = ledgersFromMeta(meta);
  return safeArray(ledgers.price_ledger as unknown);
}

function extractDetectedGap(data: AnyRecord): string {
  const narratives = safeArray<AnyRecord>(data.dominant_narratives);
  const takeaways = safeArray<string>(data.raw_takeaways);
  const fromNarrative = narratives.map(n => safeStr(n.gap)).find(g => g);
  const fromTakeaway = takeaways.find(t => /GAP/i.test(t))
    ?.replace(/.*GAP[:\s]*/i, '').split('\n')[0];
  const fromSummary = safeStr(data.one_paragraph_summary).match(/gap[^.]*\./i)?.[0];
  return firstNonEmpty(fromNarrative, fromTakeaway, fromSummary);
}

function extractInefficiencyRows(data: AnyRecord) {
  return safeArray<AnyRecord>(data.dominant_narratives).map(n => ({
    subject: safeStr(n.title),
    gap: safeStr(n.gap) || firstNonEmpty(...safeArray<string>(n.key_catalysts).slice(0, 1)),
    archetype: safeStr(n.archetype),
    confidence: safeStr(n.confidence),
    falsifier: safeArray<string>(n.what_would_change)[0] ?? '',
  })).filter(r => r.subject);
}

function extractCycleRows(data: AnyRecord) {
  const cps = safeArray<AnyRecord>((data as AnyRecord).cycle_positioning as unknown)
    .concat(safeArray<AnyRecord>((data._meta as AnyRecord)?.cycle_positioning as unknown));
  return cps;
}

function extractCounterNarratives(data: AnyRecord): string[] {
  return safeArray<string>(data.counter_narratives).filter(Boolean);
}

function extractFalsifiers(data: AnyRecord): string[] {
  const fromNarratives = safeArray<AnyRecord>(data.dominant_narratives)
    .flatMap(n => safeArray<string>(n.what_would_change));
  const fromTakeaways = safeArray<string>(data.raw_takeaways)
    .filter(t => /FALSIFIER|INVALIDATION/i.test(t))
    .map(t => t.replace(/^(FALSIFIER|INVALIDATION)[:\s]*/i, '').trim());
  return [...fromTakeaways, ...fromNarratives].filter(Boolean).slice(0, 8);
}

function extractWatchpoints(data: AnyRecord): string[] {
  return safeArray<string>(data.unknowns).filter(Boolean);
}

function normalizeDominantThemes(data: AnyRecord) {
  return safeArray<AnyRecord>(data.dominant_narratives).map(n => {
    const whyNow = safeStr(n.why_now);
    const parsed = parsePrefixedText(whyNow);
    const keyCatalysts = safeArray<string>(n.key_catalysts);
    const whatWouldChange = safeArray<string>(n.what_would_change);
    return {
      title: safeStr(n.title),
      stance: safeStr(n.stance),
      confidence: n.confidence,
      reality: parsed.REALITY || firstNonEmpty(...keyCatalysts.slice(0, 1)),
      story: parsed.STORY || whyNow,
      price: parsed.PRICE || safeStr(n.price_action),
      timeframe: parsed.TIMEFRAME,
      gap: parsed.GAP || safeStr(n.gap),
      archetype: parsed.ARCHETYPE || safeStr(n.archetype),
      falsifier: parsed.FALSIFIER || whatWouldChange[0] || '',
      allFalsifiers: whatWouldChange,
      catalysts: keyCatalysts,
    };
  });
}

// ─────────────────────────────────────────────────────────────
// UI primitives
// ─────────────────────────────────────────────────────────────
const STANCE_COLOR: Record<string, string> = {
  bullish: T.up,
  bearish: T.dn,
  neutral: T.wa,
  cautious: T.wa,
  mixed: T.wa,
};

function NarrativePanel({ title, meta, children }: { title: string; meta?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section style={sx.panel}>
      <div style={sx.panelHeader}>
        <span style={sx.sectionLabel}>{title}</span>
        {meta ? <span style={sx.sectionMeta}>{meta}</span> : null}
      </div>
      <div style={sx.panelBody}>{children}</div>
    </section>
  );
}

function Badge({ label, color }: { label: string; color?: string }) {
  const c = color ?? T.textMuted;
  return (
    <span style={{
      fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px',
      textTransform: 'uppercase' as const, fontWeight: 500,
      color: c, background: `${c}18`, border: `0.5px solid ${c}40`,
      padding: '2px 8px', whiteSpace: 'nowrap' as const, flexShrink: 0,
    }}>
      {label}
    </span>
  );
}

function MutedLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1.2px', textTransform: 'uppercase' as const, color: T.textMuted, marginBottom: '6px', fontWeight: 500 }}>
      {children}
    </div>
  );
}

function Pill({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' as const, gap: '2px' }}>
      <span style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase' as const, color: T.textMuted }}>{label}</span>
      <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textSub }}>{value ?? '—'}</span>
    </div>
  );
}

function MetricChip({ label, value, dim }: { label: string; value: string | number; dim?: boolean }) {
  return (
    <div style={{
      padding: '10px 14px', background: 'rgba(16,32,51,0.018)',
      border: `1px solid ${T.borderSub}`, borderRadius: '6px',
      display: 'flex', flexDirection: 'column' as const, gap: '4px', minWidth: '80px',
    }}>
      <span style={{ fontFamily: T.mono, fontSize: '18px', fontWeight: 300, color: dim ? T.textMuted : T.text }}>{value}</span>
      <span style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.8px', textTransform: 'uppercase' as const, color: T.textMuted }}>{label}</span>
    </div>
  );
}

function Collapsible({ label, children, defaultOpen = false }: { label: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ borderTop: `1px solid ${T.borderSub}`, marginTop: '12px' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', background: 'none', border: 'none', cursor: 'pointer',
          padding: '10px 0', display: 'flex', alignItems: 'center', gap: '8px',
          fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px',
          textTransform: 'uppercase' as const, color: T.textMuted, fontWeight: 500,
        }}
      >
        <span style={{ fontSize: '9px', opacity: 0.6 }}>{open ? '▼' : '▶'}</span>
        {label}
      </button>
      {open ? <div style={{ paddingBottom: '8px' }}>{children}</div> : null}
    </div>
  );
}

function EmptyState({ msg }: { msg: string }) {
  return (
    <div style={{ padding: '20px', textAlign: 'center' as const }}>
      <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>{msg}</span>
    </div>
  );
}

function BulletRow({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', marginBottom: '8px' }}>
      <div style={{ width: '1px', background: T.border, flexShrink: 0, marginTop: '4px', height: '14px' }} />
      <div style={{ fontFamily: T.sans, fontSize: '13px', color: T.textSub, lineHeight: 1.55 }}>{children}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Header / Controls
// ─────────────────────────────────────────────────────────────
function NarrativeHeaderControls({
  tickers, setTickers, trigger, isTriggering, isRunning, elapsedSeconds,
  jobStatus, result,
}: {
  tickers: string; setTickers: (v: string) => void; trigger: () => void;
  isTriggering: boolean; isRunning: boolean; elapsedSeconds: number;
  jobStatus: AnyRecord | null; result: AnyRecord | null;
}) {
  const meta = result ? (result._meta as AnyRecord) : null;
  const lc = (meta?.ledger_counts as AnyRecord) ?? {};
  const ledgerCount = Object.keys(lc).filter(k => !k.includes('uncategorized')).length;
  const hasPrice = (safeNum(lc.price_ledger) ?? 0) > 0;
  const total = safeNum(meta?.total_items_in_bundle);

  return (
    <section style={sx.panel}>
      <div style={sx.panelHeader}>
        <span style={sx.sectionLabel}>Narrative Synthesis</span>
        {result?.asof_utc ? (
          <span style={sx.sectionMeta}>
            {new Date(result.asof_utc as string).toLocaleString()}
          </span>
        ) : null}
      </div>
      <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <span style={{ fontFamily: T.sans, fontSize: '11px', letterSpacing: '1px', textTransform: 'uppercase', color: T.label, flexShrink: 0 }}>
            Watch tickers
          </span>
          <input
            value={tickers}
            onChange={e => setTickers(e.target.value)}
            style={{
              flex: '1 1 320px', fontFamily: T.mono, fontSize: '12.5px', fontWeight: 300,
              color: 'rgba(16,32,51,0.75)', background: 'rgba(16,32,51,0.03)',
              border: `0.5px solid ${T.border}`, padding: '8px 10px', outline: 'none',
            }}
          />
          <button
            onClick={trigger}
            disabled={isTriggering || isRunning}
            style={{
              fontFamily: T.sans, fontSize: '12px', letterSpacing: '1px',
              textTransform: 'uppercase', fontWeight: 500, flexShrink: 0, whiteSpace: 'nowrap',
              color: isRunning ? T.textMuted : 'rgba(16,32,51,0.8)',
              background: isRunning ? 'transparent' : 'rgba(16,32,51,0.06)',
              border: `0.5px solid ${isRunning ? T.border : 'rgba(16,32,51,0.15)'}`,
              padding: '8px 16px', cursor: isRunning ? 'not-allowed' : 'pointer',
              animation: isRunning ? 'temperPulse 1.8s ease-in-out infinite' : 'none',
            }}
          >
            {isRunning ? 'Synthesis running' : isTriggering ? 'Starting…' : 'Synthesize Narrative'}
          </button>
        </div>

        {isRunning ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ display: 'flex', gap: '12px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.text }}>Elapsed {elapsedSeconds}s</span>
              <span style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.textMuted }}>typically 15–45 seconds</span>
            </div>
            <div style={{ height: '2px', background: T.borderSub, overflow: 'hidden', maxWidth: '320px' }}>
              <div style={{ width: `${Math.min(96, 15 + elapsedSeconds * 3)}%`, height: '100%', background: T.accent, animation: 'temperPulse 1.6s ease-in-out infinite' }} />
            </div>
          </div>
        ) : null}

        {jobStatus?.status === 'error' ? (
          <span style={{ fontFamily: T.mono, fontSize: '11.5px', color: T.dn }}>Error: {safeStr(jobStatus.error)}</span>
        ) : null}

        {result ? (
          <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', borderTop: `1px solid ${T.borderSub}`, paddingTop: '10px' }}>
            <Pill label="Model" value={safeStr((result._meta as AnyRecord)?.model ?? result.model ?? '—') || '—'} />
            <Pill label="Sources" value={total !== null ? `${total} items` : '—'} />
            <Pill label="Ledgers" value={ledgerCount > 0 ? `${ledgerCount} active` : '—'} />
            <Pill label="Price context" value={hasPrice ? 'active' : 'unavailable'} />
          </div>
        ) : null}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Narrative Regime Snapshot
// ─────────────────────────────────────────────────────────────
function NarrativeRegimeSnapshot({ data }: { data: AnyRecord }) {
  const { summary, archetype, gap, confidence, stance } = extractRegimeSnapshot(data);
  const sc = STANCE_COLOR[stance?.toLowerCase()] ?? T.mid;
  const narratives = safeArray<AnyRecord>(data.dominant_narratives);
  const topConf = safeNum(narratives[0]?.confidence);

  return (
    <NarrativePanel title="Narrative Regime Snapshot" meta={data.asof_utc ? new Date(data.asof_utc as string).toLocaleString() : undefined}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          {stance ? <Badge label={stance} color={sc} /> : null}
          {archetype ? <Badge label={`Archetype: ${truncate(archetype, 60)}`} color={T.accent} /> : null}
          {gap ? <Badge label={`Gap: ${truncate(gap, 60)}`} color={T.wa} /> : null}
          {topConf !== null ? (
            <Badge label={`Confidence: ${topConf}/100`} color={T.textMuted} />
          ) : confidence ? (
            <Badge label={`Confidence: ${confidence}`} color={T.textMuted} />
          ) : null}
        </div>
        {summary ? (
          <p style={{ fontFamily: T.sans, fontSize: '15px', color: 'rgba(16,32,51,0.72)', lineHeight: 1.72, margin: 0, maxWidth: '900px' }}>
            {summary}
          </p>
        ) : (
          <EmptyState msg="No summary available" />
        )}
      </div>
    </NarrativePanel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Information Set
// ─────────────────────────────────────────────────────────────
function InformationSetCard({ data }: { data: AnyRecord }) {
  const c = extractLedgerCounts(data);
  const meta = (data._meta ?? {}) as AnyRecord;
  const roleCounts = (meta.role_counts ?? {}) as AnyRecord;
  const tagCounts = (meta.content_tag_counts ?? {}) as AnyRecord;
  const filtered = (meta.filtered_items_summary ?? {}) as AnyRecord;
  const filteredReasons = (filtered.reasons ?? {}) as AnyRecord;

  return (
    <NarrativePanel title="Information Set" meta={`${c.selected} of ${c.total} items selected`}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <MetricChip label="Total items" value={c.total} />
          <MetricChip label="Policy / official" value={c.policy} />
          <MetricChip label="Fundamental" value={c.fundamental} />
          <MetricChip label="Narrative" value={c.narrative} />
          <MetricChip label="Alt views" value={c.alternative} dim />
          <MetricChip label="Price evidence" value={c.price} />
          {c.filtered > 0 ? <MetricChip label="Filtered" value={c.filtered} dim /> : null}
        </div>

        <Collapsible label="Source breakdown">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px,1fr))', gap: '16px', paddingTop: '8px' }}>
            {Object.keys(roleCounts).length > 0 ? (
              <div>
                <MutedLabel>By role</MutedLabel>
                {Object.entries(roleCounts).map(([k, v]) => (
                  <BulletRow key={k}><span style={{ opacity: 0.55 }}>{k.replace(/_/g, ' ')}</span><span style={{ marginLeft: 'auto', fontFamily: T.mono, fontSize: '12px' }}>{String(v)}</span></BulletRow>
                ))}
              </div>
            ) : null}
            {Object.keys(tagCounts).length > 0 ? (
              <div>
                <MutedLabel>Content tags</MutedLabel>
                {Object.entries(tagCounts).slice(0, 10).map(([k, v]) => (
                  <BulletRow key={k}><span style={{ opacity: 0.55 }}>{k.replace(/_/g, ' ')}</span><span style={{ marginLeft: 'auto', fontFamily: T.mono, fontSize: '12px' }}>{String(v)}</span></BulletRow>
                ))}
              </div>
            ) : null}
            {Object.keys(filteredReasons).length > 0 ? (
              <div>
                <MutedLabel>Filtered reasons</MutedLabel>
                {Object.entries(filteredReasons).map(([k, v]) => (
                  <BulletRow key={k}><span style={{ opacity: 0.55 }}>{k.replace(/_/g, ' ')}</span><span style={{ marginLeft: 'auto', fontFamily: T.mono, fontSize: '12px' }}>{String(v)}</span></BulletRow>
                ))}
              </div>
            ) : null}
          </div>
        </Collapsible>
      </div>
    </NarrativePanel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Evidence Board
// ─────────────────────────────────────────────────────────────
function EvidenceItem({ item }: { item: AnyRecord }) {
  const strength = safeStr(item.evidence_strength);
  const role = safeStr(item.information_role).replace(/_/g, ' ');
  const tags = safeArray<string>(item.content_tags).slice(0, 3);
  return (
    <div style={{ padding: '10px 12px', background: 'rgba(16,32,51,0.014)', border: `1px solid ${T.borderSub}`, borderRadius: '6px', marginBottom: '8px' }}>
      <div style={{ fontFamily: T.sans, fontSize: '13px', color: T.textSub, lineHeight: 1.5, marginBottom: '4px' }}>
        {truncate(safeStr(item.title || item.summary), 160)}
      </div>
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontFamily: T.mono, fontSize: '10px', color: T.textMuted }}>{safeStr(item.source)}</span>
        {strength ? <Badge label={strength.replace(/_/g, ' ')} /> : null}
        {tags.map(t => <Badge key={t} label={t.replace(/_/g, ' ')} color={T.accent} />)}
      </div>
    </div>
  );
}

function PriceBullets({ entries }: { entries: unknown[] }) {
  const ca = findPriceLedgerEntry(entries, 'cross_asset_returns');
  const rels = findPriceLedgerEntry(entries, 'relationship_signals');
  const sec = findPriceLedgerEntry(entries, 'sector_returns');

  const caItems = priceLedgerItems(ca);
  const relItems = safeArray<AnyRecord>((rels?.items as AnyRecord[]) ?? []);
  const secItems = priceLedgerItems(sec);

  const renderAsset = (a: AnyRecord, i: number) => {
    const r = getReturn1D(a);
    return (
      <BulletRow key={i}>
        <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textSub, marginRight: '4px' }}>{safeStr(a.ticker)}</span>
        <span style={{ color: pctColor(r), fontFamily: T.mono, fontSize: '12px' }}>{formatPct(r)}</span>
        {' '}
        <span style={{ color: T.textMuted, fontSize: '12px' }}>{safeStr(a.name)}</span>
      </BulletRow>
    );
  };

  if (!caItems.length && !relItems.length && !secItems.length) {
    return <EmptyState msg="Price evidence unavailable for this run" />;
  }

  return (
    <div>
      {caItems.slice(0, 5).map((a, i) => renderAsset(a as AnyRecord, i))}
      {relItems.slice(0, 4).map((r, i) => {
        const rel = r as AnyRecord;
        const v = safeNum(rel.value) ?? getReturn1D(rel);
        return (
          <BulletRow key={`rel-${i}`}>
            <span style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>{safeStr(rel.name)}</span>
            {' '}
            <span style={{ color: pctColor(v), fontFamily: T.mono, fontSize: '11px' }}>{formatPct(v)}</span>
            {' — '}
            <span style={{ fontSize: '11px', color: T.textMuted }}>{truncate(safeStr(rel.interpretation), 80)}</span>
          </BulletRow>
        );
      })}
    </div>
  );
}

function EvidenceBoard({ data }: { data: AnyRecord }) {
  const reality = getRealityEvidence(data);
  const story = getStoryEvidence(data);
  const priceEntries = getPriceLedgerEntries(data);
  const gap = extractDetectedGap(data);

  const col = (title: string, color: string, children: React.ReactNode) => (
    <div style={{ flex: '1 1 240px', minWidth: 0 }}>
      <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '2px', textTransform: 'uppercase', fontWeight: 600, color, marginBottom: '12px', paddingBottom: '6px', borderBottom: `1px solid ${color}30` }}>
        {title}
      </div>
      {children}
    </div>
  );

  return (
    <NarrativePanel title="Evidence Board">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
          {col('Reality', T.up,
            reality.length > 0
              ? reality.map((item, i) => <EvidenceItem key={i} item={item} />)
              : <EmptyState msg="No policy or fundamental evidence" />
          )}
          {col('Story', '#60a5fa',
            story.length > 0
              ? story.map((item, i) => <EvidenceItem key={i} item={item} />)
              : <EmptyState msg="No narrative evidence" />
          )}
          {col('Price', T.accent,
            <PriceBullets entries={priceEntries} />
          )}
        </div>

        {gap ? (
          <div style={{ padding: '12px 16px', background: `${T.wa}10`, border: `1px solid ${T.wa}30`, borderRadius: '6px', borderLeft: `3px solid ${T.wa}` }}>
            <div style={{ fontFamily: T.sans, fontSize: '10px', letterSpacing: '1.2px', textTransform: 'uppercase', color: T.wa, marginBottom: '6px', fontWeight: 600 }}>Detected Gap</div>
            <p style={{ fontFamily: T.sans, fontSize: '13px', color: T.textSub, lineHeight: 1.6, margin: 0 }}>{gap}</p>
          </div>
        ) : null}
      </div>
    </NarrativePanel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Price & Timeframe Context
// ─────────────────────────────────────────────────────────────
const HORIZONS_ORDERED = ['1D', '5D', '1M', '3M', 'YTD', '1Y'];

function PriceTable({ title, items }: { title: string; items: AnyRecord[] }) {
  if (!items.length) return null;

  const sample = items[0];
  const multiRets = sample.returns as Record<string, unknown> | undefined;
  const visibleHorizons = multiRets
    ? HORIZONS_ORDERED.filter(h => items.some(a => safeNum((a.returns as Record<string, unknown>)?.[h]) !== null))
    : ['1D'];

  return (
    <div style={{ marginBottom: '20px' }}>
      <MutedLabel>{title}</MutedLabel>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' as const, fontFamily: T.mono, fontSize: '12px' }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${T.borderSub}` }}>
              <th style={{ textAlign: 'left' as const, padding: '6px 8px', color: T.textMuted, fontWeight: 400, letterSpacing: '0.5px' }}>Asset</th>
              {visibleHorizons.map(h => (
                <th key={h} style={{ textAlign: 'right' as const, padding: '6px 8px', color: T.textMuted, fontWeight: 400, letterSpacing: '0.5px', minWidth: '56px' }}>{h}</th>
              ))}
              <th style={{ textAlign: 'left' as const, padding: '6px 8px', color: T.textMuted, fontWeight: 400, fontSize: '11px' }}>Trend</th>
            </tr>
          </thead>
          <tbody>
            {items.map((asset, i) => {
              const rets = getReturns(asset);
              const tc = (asset.trend_context as AnyRecord) ?? {};
              return (
                <tr key={i} style={{ borderBottom: `1px solid ${T.borderSub}`, opacity: 0.92 }}>
                  <td style={{ padding: '7px 8px', color: T.textSub }}>
                    <span style={{ color: T.text }}>{safeStr(asset.ticker)}</span>
                    {' '}
                    <span style={{ color: T.textMuted, fontSize: '11px' }}>{safeStr(asset.name)}</span>
                  </td>
                  {visibleHorizons.map(h => {
                    const v = rets[h];
                    return (
                      <td key={h} style={{ textAlign: 'right' as const, padding: '7px 8px', color: pctColor(v) }}>
                        {formatPct(v)}
                      </td>
                    );
                  })}
                  <td style={{ padding: '7px 8px', color: T.textMuted, fontSize: '11px', maxWidth: '200px' }}>
                    {truncate(safeStr(tc.today_vs_trend), 90)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RelationshipCards({ items }: { items: AnyRecord[] }) {
  if (!items.length) return null;
  return (
    <div style={{ marginBottom: '16px' }}>
      <MutedLabel>Relationship Signals</MutedLabel>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
        {items.map((rel, i) => {
          const rets = getReturns(rel);
          const v = rets['1D'] ?? safeNum(rel.value);
          const interp = safeStr(rel.interpretation);
          return (
            <div key={i} style={{
              padding: '8px 12px', background: 'rgba(16,32,51,0.014)',
              border: `1px solid ${T.borderSub}`, borderRadius: '6px',
              flex: '1 1 260px', maxWidth: '380px',
            }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'baseline', marginBottom: '4px' }}>
                <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textSub }}>{safeStr(rel.name)}</span>
                <span style={{ fontFamily: T.mono, fontSize: '12px', color: pctColor(v) }}>{formatPct(v)}</span>
              </div>
              <div style={{ fontFamily: T.sans, fontSize: '11px', color: T.textMuted }}>{truncate(interp, 100)}</div>
              {rel.returns != null && (
                <div style={{ display: 'flex', gap: '8px', marginTop: '6px', flexWrap: 'wrap' }}>
                  {(['5D', '1M', '3M'] as const).map(h => {
                    const hv = (rel.returns as Record<string, unknown>)?.[h];
                    const hn = safeNum(hv);
                    return hn !== null ? (
                      <span key={h} style={{ fontFamily: T.mono, fontSize: '10px', color: pctColor(hn) }}>
                        {h} {formatPct(hn)}
                      </span>
                    ) : null;
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PriceTimeframeContext({ data }: { data: AnyRecord }) {
  const entries = getPriceLedgerEntries(data);
  const caEntry = findPriceLedgerEntry(entries, 'cross_asset_returns');
  const secEntry = findPriceLedgerEntry(entries, 'sector_returns');
  const snEntry = findPriceLedgerEntry(entries, 'single_name_returns');
  const relEntry = findPriceLedgerEntry(entries, 'relationship_signals');

  const caAll = safeArray<AnyRecord>(((caEntry?.items as AnyRecord)?.all as AnyRecord[]) ?? []);
  const secAll = safeArray<AnyRecord>(((secEntry?.items as AnyRecord)?.all as AnyRecord[]) ?? []);
  const snAll = safeArray<AnyRecord>(((snEntry?.items as AnyRecord)?.all as AnyRecord[]) ?? []).filter(a => getReturn1D(a) !== null);
  const relItems = safeArray<AnyRecord>((relEntry?.items as AnyRecord[]) ?? []);

  const horizons = safeArray<string>(caEntry?.horizons as string[]);

  if (!caAll.length && !secAll.length && !relItems.length) {
    return (
      <NarrativePanel title="Price & Timeframe Context">
        <EmptyState msg="Price context unavailable for this run" />
      </NarrativePanel>
    );
  }

  return (
    <NarrativePanel
      title="Price & Timeframe Context"
      meta={horizons.length > 0 ? horizons.join(' · ') : undefined}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <PriceTable title="Cross-Asset" items={caAll} />
        <PriceTable title="Sectors" items={secAll} />
        {snAll.length > 0 ? <PriceTable title="Single Names" items={snAll} /> : (
          <div style={{ marginBottom: '8px' }}>
            <MutedLabel>Single Names</MutedLabel>
            <span style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>No single-name price reactions available for this run.</span>
          </div>
        )}
        <RelationshipCards items={relItems} />
      </div>
    </NarrativePanel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Dominant Themes
// ─────────────────────────────────────────────────────────────
const TAKEAWAY_COLOR: Record<string, string> = {
  CHANGE: '#60a5fa',
  CONFIRMATION: T.up,
  INVALIDATION: T.dn,
  UNCLEAR: T.wa,
  'REALITY': T.up,
  'STORY': '#60a5fa',
  'PRICE': T.accent,
  'GAP': T.wa,
  'ARCHETYPE': T.textMuted,
  'FALSIFIER': T.dn,
};

function ThemeField({ label, color, value }: { label: string; color: string; value: string }) {
  if (!value) return null;
  return (
    <div style={{ marginBottom: '10px' }}>
      <div style={{ fontFamily: T.sans, fontSize: '9px', letterSpacing: '1.5px', textTransform: 'uppercase', color, fontWeight: 600, marginBottom: '3px' }}>{label}</div>
      <p style={{ fontFamily: T.sans, fontSize: '13px', color: T.textSub, lineHeight: 1.6, margin: 0 }}>{value}</p>
    </div>
  );
}

function DominantThemeCard({ theme }: { theme: ReturnType<typeof normalizeDominantThemes>[0] }) {
  const sc = STANCE_COLOR[theme.stance?.toLowerCase()] ?? T.mid;
  const conf = safeNum(theme.confidence);
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={sx.subPanel}>
      <div style={{ padding: '14px 16px', borderBottom: `1px solid ${T.borderSub}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', marginBottom: '6px' }}>
          <span style={{ fontFamily: T.sans, fontSize: '15px', fontWeight: 500, color: T.text }}>{theme.title}</span>
          <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
            {theme.stance ? <Badge label={theme.stance} color={sc} /> : null}
            {conf !== null ? <Badge label={`${conf}/100`} color={T.textMuted} /> : null}
          </div>
        </div>
      </div>
      <div style={{ padding: '14px 16px' }}>
        <ThemeField label="Reality" color={T.up} value={theme.reality} />
        <ThemeField label="Story" color="#60a5fa" value={theme.story} />
        <ThemeField label="Price" color={T.accent} value={theme.price} />
        {theme.timeframe ? <ThemeField label="Timeframe" color={T.textMuted} value={theme.timeframe} /> : null}
        {theme.gap ? <ThemeField label="Gap" color={T.wa} value={theme.gap} /> : null}
        {theme.archetype ? <ThemeField label="Archetype" color={T.textMuted} value={theme.archetype} /> : null}
        {theme.falsifier ? <ThemeField label="Falsifier" color={T.dn} value={theme.falsifier} /> : null}
        {theme.allFalsifiers.length > 1 || theme.catalysts.length > 0 ? (
          <Collapsible label="Details">
            {theme.catalysts.length > 0 ? (
              <div style={{ marginBottom: '10px' }}>
                <MutedLabel>Key catalysts</MutedLabel>
                {theme.catalysts.map((c, j) => <BulletRow key={j}>{c}</BulletRow>)}
              </div>
            ) : null}
            {theme.allFalsifiers.length > 1 ? (
              <div>
                <MutedLabel>What would change this</MutedLabel>
                {theme.allFalsifiers.map((f, j) => <BulletRow key={j}>{f}</BulletRow>)}
              </div>
            ) : null}
          </Collapsible>
        ) : null}
      </div>
    </div>
  );
}

function DominantThemes({ data }: { data: AnyRecord }) {
  const themes = normalizeDominantThemes(data);
  const takeaways = safeArray<string>(data.raw_takeaways);

  return (
    <NarrativePanel title="Dominant Themes" meta={`${themes.length} theme${themes.length !== 1 ? 's' : ''}`}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {takeaways.length > 0 ? (
          <div style={{ marginBottom: '8px' }}>
            <MutedLabel>Key Takeaways</MutedLabel>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {takeaways.map((item, i) => {
                const prefix = item.match(/^(CHANGE|CONFIRMATION|INVALIDATION|UNCLEAR|REALITY|STORY|PRICE|GAP|ARCHETYPE|FALSIFIER)/)?.[0];
                const c = prefix ? (TAKEAWAY_COLOR[prefix] ?? T.textMuted) : T.textMuted;
                return (
                  <div key={i} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', padding: '10px 12px', border: `0.5px solid ${T.borderSub}`, background: 'rgba(16,32,51,0.012)', borderRadius: '6px' }}>
                    {prefix ? <Badge label={prefix} color={c} /> : null}
                    <p style={{ fontFamily: T.sans, fontSize: '13.5px', color: 'rgba(16,32,51,0.65)', lineHeight: 1.6, margin: 0 }}>
                      {prefix ? item.replace(prefix, '').replace(/^[:\s]+/, '') : item}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        {themes.length > 0
          ? themes.map((theme, i) => <DominantThemeCard key={i} theme={theme} />)
          : <EmptyState msg="No dominant themes identified" />}
      </div>
    </NarrativePanel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Inefficiency Map
// ─────────────────────────────────────────────────────────────
function InefficiencyMap({ data }: { data: AnyRecord }) {
  const rows = extractInefficiencyRows(data);
  if (!rows.length) {
    return (
      <NarrativePanel title="Inefficiency Map">
        <EmptyState msg="No explicit inefficiency classifications were produced in this run." />
      </NarrativePanel>
    );
  }
  return (
    <NarrativePanel title="Inefficiency Map" meta={`${rows.length} classification${rows.length !== 1 ? 's' : ''}`}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.sans, fontSize: '13px' }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${T.border}` }}>
              {['Subject', 'Gap / Signal', 'Archetype', 'Confidence', 'Falsifier'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, fontWeight: 500 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${T.borderSub}` }}>
                <td style={{ padding: '10px 10px', color: T.text, fontWeight: 500, maxWidth: '160px' }}>{row.subject}</td>
                <td style={{ padding: '10px 10px', color: T.textSub, maxWidth: '200px' }}>{truncate(row.gap, 120)}</td>
                <td style={{ padding: '10px 10px' }}>
                  {row.archetype ? <Badge label={truncate(row.archetype, 40)} color={T.textMuted} /> : <span style={{ color: T.textMuted }}>—</span>}
                </td>
                <td style={{ padding: '10px 10px', color: T.textMuted, fontFamily: T.mono, fontSize: '12px' }}>{row.confidence || '—'}</td>
                <td style={{ padding: '10px 10px', color: T.textMuted, fontSize: '12px', maxWidth: '180px' }}>{truncate(row.falsifier, 100)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </NarrativePanel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Cycle Positioning
// ─────────────────────────────────────────────────────────────
const CYCLE_COLORS: Record<string, string> = {
  euphoria: T.dn, thrill: T.wa, excitement: T.wa, optimism: T.up,
  hope: T.up, relief: T.up, despondency: T.dn, depression: T.dn,
  panic: T.dn, capitulation: T.dn, desperation: T.dn, fear: T.dn,
  denial: T.wa, anxiety: T.wa,
};

function CyclePositioning({ data }: { data: AnyRecord }) {
  const rows = extractCycleRows(data);
  return (
    <NarrativePanel title="Cycle Positioning">
      {rows.length === 0 ? (
        <div style={{ padding: '24px 0', textAlign: 'center' }}>
          <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.textMuted }}>
            Cycle positioning will appear here once the psychology/cycle classifier is enabled.
          </span>
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.sans, fontSize: '13px' }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${T.border}` }}>
              {['Subject', 'Stage', 'Direction', 'Timeframe', 'Confidence', 'Why'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', fontFamily: T.sans, fontSize: '10px', letterSpacing: '1px', textTransform: 'uppercase', color: T.textMuted, fontWeight: 500 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const stage = safeStr(row.cycle_stage || row.stage);
              const c = CYCLE_COLORS[stage.toLowerCase()] ?? T.textMuted;
              return (
                <tr key={i} style={{ borderBottom: `1px solid ${T.borderSub}` }}>
                  <td style={{ padding: '10px 10px', color: T.text }}>{safeStr(row.subject)}</td>
                  <td style={{ padding: '10px 10px' }}><Badge label={stage} color={c} /></td>
                  <td style={{ padding: '10px 10px', color: T.textSub }}>{safeStr(row.direction)}</td>
                  <td style={{ padding: '10px 10px', color: T.textMuted, fontFamily: T.mono, fontSize: '11px' }}>{safeStr(row.timeframe)}</td>
                  <td style={{ padding: '10px 10px', color: T.textMuted }}>{safeStr(row.confidence)}</td>
                  <td style={{ padding: '10px 10px', color: T.textMuted, fontSize: '12px' }}>{truncate(safeStr(row.why), 100)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </NarrativePanel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Counter-Narratives & Watchpoints
// ─────────────────────────────────────────────────────────────
function TextColumn({ title, items, emptyMsg }: { title: string; items: string[]; emptyMsg: string }) {
  return (
    <div style={{ flex: '1 1 200px' }}>
      <MutedLabel>{title}</MutedLabel>
      {items.length > 0
        ? items.map((s, i) => <BulletRow key={i}>{s}</BulletRow>)
        : <span style={{ fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>{emptyMsg}</span>}
    </div>
  );
}

function CounterNarrativesWatchpoints({ data }: { data: AnyRecord }) {
  const counters = extractCounterNarratives(data);
  const falsifiers = extractFalsifiers(data);
  const watchpoints = extractWatchpoints(data);

  if (!counters.length && !falsifiers.length && !watchpoints.length) return null;

  return (
    <NarrativePanel title="Counter-Narratives · Falsifiers · Watchpoints">
      <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
        <TextColumn title="Counter-Narratives" items={counters} emptyMsg="None specified" />
        <TextColumn title="Falsifiers" items={falsifiers} emptyMsg="None specified" />
        <TextColumn title="Watchpoints" items={watchpoints} emptyMsg="None specified" />
      </div>
    </NarrativePanel>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Advanced Raw Ledgers
// ─────────────────────────────────────────────────────────────
function AdvancedRawLedgers({ data }: { data: AnyRecord }) {
  const meta = (data._meta ?? {}) as AnyRecord;
  const lc = (meta.ledger_counts ?? {}) as AnyRecord;
  const ledgers = ledgersFromMeta(meta);

  return (
    <section style={sx.panel}>
      <div style={sx.panelHeader}>
        <span style={sx.sectionLabel}>Advanced · Raw Ledgers</span>
      </div>
      <div style={sx.panelBody}>
        <Collapsible label="Ledger counts & metadata">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px,1fr))', gap: '12px', paddingTop: '8px' }}>
            {Object.entries(lc).map(([k, v]) => (
              <MetricChip key={k} label={k.replace(/_/g, ' ')} value={String(v)} dim />
            ))}
          </div>
          <div style={{ marginTop: '12px', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
            {[
              ['Total in bundle', String(safeNum(meta.total_items_in_bundle) ?? '—')],
              ['Selected for LLM', String(safeNum(meta.items_selected_for_llm) ?? '—')],
              ['Prior snapshot', String(meta.prior_snapshot_found ?? '—')],
              ['Lookback hours', String(safeNum(meta.lookback_hours) ?? '—')],
            ].map(([l, v]) => <Pill key={l} label={l} value={v} />)}
          </div>
        </Collapsible>

        {Object.entries(ledgers).map(([ledgerKey, ledgerVal]) => {
          const items = safeArray<AnyRecord>(ledgerVal as unknown);
          if (!items.length) return null;
          return (
            <Collapsible key={ledgerKey} label={`${ledgerKey.replace(/_/g, ' ')} (${items.length} items)`}>
              <div style={{ paddingTop: '8px' }}>
                {items.map((item, i) => (
                  item.type || item.kind ? (
                    <div key={i} style={{ marginBottom: '6px', padding: '8px', background: 'rgba(16,32,51,0.01)', borderRadius: '4px', fontFamily: T.mono, fontSize: '11px', color: T.textMuted }}>
                      {String(item.type ?? item.kind)}
                    </div>
                  ) : (
                    <EvidenceItem key={i} item={item} />
                  )
                ))}
              </div>
            </Collapsible>
          );
        })}
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────
export default function NarrativePage() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [tickers, setTickers] = useState('SPY,QQQ,IWM,AAPL,MSFT,NVDA,TSLA,GOOGL,AMZN,META');
  const [completedResult, setCompletedResult] = useState<AnyRecord | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);

  const { getToken } = useAuth();
  const authFetcher = useAuthFetcher();

  const { data: latest } = useSWR('/api/narrative/latest', authFetcher, { onError: () => null });

  const { data: jobStatus } = useSWR(
    jobId ? `/api/narrative/status/${jobId}` : null,
    authFetcher,
    {
      refreshInterval: jobId ? 2000 : 0,
      onSuccess: (data) => {
        if (data?.status === 'done') { setCompletedResult(data.result); setJobId(null); }
        if (data?.status === 'error') setJobId(null);
      },
    },
  );

  const trigger = async () => {
    setIsTriggering(true);
    try {
      const token = await getToken();
      const params = new URLSearchParams({ tickers, news_category: 'general', earnings_days: '7', lookback_hours: '36' });
      const res = await fetch(`/api/narrative/synthesize?${params}`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`Server responded ${res.status}`);
      const data = await res.json();
      setJobId(data.job_id);
      setStartedAt(Date.now());
      setElapsedMs(0);
    } catch (e) {
      console.error('Narrative trigger failed:', e);
    } finally {
      setIsTriggering(false);
    }
  };

  const result: AnyRecord | null = completedResult ?? (jobStatus?.status === 'done' ? (jobStatus.result as AnyRecord) : latest) ?? null;
  const isRunning = jobId !== null && jobStatus?.status === 'running';
  const elapsedSeconds = Math.floor(elapsedMs / 1000);

  useEffect(() => {
    if (!isRunning || !startedAt) return;
    const t = window.setInterval(() => setElapsedMs(Date.now() - startedAt), 250);
    return () => window.clearInterval(t);
  }, [isRunning, startedAt]);

  useEffect(() => {
    if (!isRunning) { setStartedAt(null); setElapsedMs(0); }
  }, [isRunning]);

  return (
    <main style={sx.main}>
      <div style={sx.pageShell}>

        {/* 1. Header / Controls */}
        <NarrativeHeaderControls
          tickers={tickers}
          setTickers={setTickers}
          trigger={trigger}
          isTriggering={isTriggering}
          isRunning={isRunning}
          elapsedSeconds={elapsedSeconds}
          jobStatus={jobStatus as AnyRecord | null}
          result={result}
        />

        {result ? (
          <>
            {/* 2. Regime Snapshot */}
            <NarrativeRegimeSnapshot data={result} />

            {/* 3. Information Set */}
            <InformationSetCard data={result} />

            {/* 4. Evidence Board */}
            <EvidenceBoard data={result} />

            {/* 5. Price & Timeframe Context */}
            <PriceTimeframeContext data={result} />

            {/* 6. Dominant Themes */}
            <DominantThemes data={result} />

            {/* 7. Inefficiency Map */}
            <InefficiencyMap data={result} />

            {/* 8. Cycle Positioning */}
            <CyclePositioning data={result} />

            {/* 9. Counter-Narratives & Watchpoints */}
            <CounterNarrativesWatchpoints data={result} />

            {/* 10. Advanced Raw Ledgers */}
            <AdvancedRawLedgers data={result} />
          </>
        ) : !isRunning ? (
          <section style={sx.panel}>
            <div style={{ ...sx.panelBody, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '80px 24px', gap: '6px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '13px', color: T.textMuted }}>No narrative snapshot found</span>
              <span style={{ fontFamily: T.sans, fontSize: '13px', color: 'rgba(16,32,51,0.35)' }}>
                Hit &quot;Synthesize Narrative&quot; to generate today&apos;s analysis
              </span>
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
