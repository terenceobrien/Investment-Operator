'use client';

import { useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';
import { useAuthFetcher } from '../../lib/api';
import AuthRequired from '@/components/AuthRequired';
import { T } from '@/lib/tokens';
import {
  Card,
  Chip,
  Collapsible,
  EmptyState,
  MAIN_GRID,
  MutedLabel,
  PAGE_SHELL,
  SNAPSHOT_GRID,
} from '@/components/helix/primitives';

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
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
function truncate(s: string, max = 200): string {
  if (!s || s.length <= max) return s;
  return s.slice(0, max).trimEnd() + '…';
}
function firstNonEmpty(...vals: unknown[]): string {
  for (const v of vals) if (typeof v === 'string' && v.trim()) return v.trim();
  return '';
}
function compactList<T>(items: T[], max: number): T[] {
  return items.slice(0, max);
}
function formatPct(v: unknown): string {
  const n = safeNum(v);
  if (n === null) return '—';
  const abs = Math.abs(n).toFixed(2) + '%';
  return n < 0 ? `−${abs}` : `+${abs}`;
}
function pctColor(v: unknown): string {
  const n = safeNum(v);
  if (n === null) return T.textMuted;
  return n > 0 ? T.up : n < 0 ? T.dn : T.textMuted;
}
function parsePrefixedText(text: string): Record<string, string> {
  const prefixes = ['REALITY', 'STORY', 'PRICE', 'TIMEFRAME', 'GAP', 'ARCHETYPE', 'FALSIFIER'];
  const out: Record<string, string> = {};
  for (const p of prefixes) {
    const others = prefixes.filter(x => x !== p).join('|');
    const re = new RegExp(`${p}[:\\s]+([\\s\\S]*?)(?=${others}|$)`, 'i');
    const m = text.match(re);
    if (m?.[1]?.trim()) out[p] = m[1].trim();
  }
  return out;
}

// ─────────────────────────────────────────────────────────────
// Data accessors
// ─────────────────────────────────────────────────────────────
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
  return { '1D': safeNum(asset.return) };
}

// ─────────────────────────────────────────────────────────────
// Extraction helpers
// ─────────────────────────────────────────────────────────────
function extractExecutiveSnapshot(data: AnyRecord) {
  const meta = (data._meta ?? {}) as AnyRecord;
  const narratives = safeArray<AnyRecord>(data.dominant_narratives);
  const takeaways = safeArray<string>(data.raw_takeaways);
  const fullSummary = safeStr(data.one_paragraph_summary);

  // ── Prefer the explicit executive_snapshot if the synthesis populated it
  // (prompt v3+). Older snapshots fall through to the heuristic path below.
  const snap = (data.executive_snapshot ?? null) as AnyRecord | null;

  const isMissing = (v: string) =>
    !v || /^not specified$/i.test(v) || /^mixed\s*\/\s*unclear$/i.test(v);

  if (snap) {
    const eb = (snap.executive_bullets ?? {}) as AnyRecord;
    const ebReality = safeStr(eb.reality);
    const ebStory = safeStr(eb.story);
    const ebPrice = safeStr(eb.price);

    const bullets = [
      { label: 'Reality', text: ebReality },
      { label: 'Story', text: ebStory },
      { label: 'Price', text: ebPrice },
    ];

    // If all three explicit bullets are empty, fall back to summary-split.
    if (bullets.every(b => !b.text) && fullSummary) {
      const sentences = fullSummary
        .split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(Boolean);
      if (sentences[0]) bullets[0].text = sentences[0];
      if (sentences[1]) bullets[1].text = sentences[1];
      if (sentences[2]) bullets[2].text = sentences.slice(2).join(' ');
    }

    const regimeTone = safeStr(snap.regime_tone);
    const primaryGap = safeStr(snap.primary_gap);
    const primaryArchetype = safeStr(snap.primary_archetype);
    const priceConfirmation = safeStr(snap.price_confirmation);
    const confidence = safeNum(snap.confidence);

    return {
      regimeTone: isMissing(regimeTone) ? '' : regimeTone,
      primaryGap: isMissing(primaryGap) ? '' : primaryGap,
      primaryArchetype: isMissing(primaryArchetype) ? '' : primaryArchetype,
      priceConfirmation: isMissing(priceConfirmation) ? '' : priceConfirmation,
      confidence,
      bullets: bullets.filter(b => b.text),
      fullSummary,
      asof: safeStr(data.asof_utc),
      model: safeStr(meta.model ?? data.model),
    };
  }

  // ── Heuristic fallback for older snapshots without executive_snapshot ──
  const archetype = firstNonEmpty(
    ...narratives.map(n => safeStr(n.archetype)),
    takeaways.find(t => /^ARCHETYPE/i.test(t))?.replace(/^ARCHETYPE[:\s]*/i, '').split('\n')[0],
  );
  const gap = firstNonEmpty(
    ...narratives.map(n => safeStr(n.gap)),
    takeaways.find(t => /^GAP/i.test(t))?.replace(/^GAP[:\s]*/i, '').split('\n')[0],
  );

  const stance = firstNonEmpty(safeStr(narratives[0]?.stance));
  const regimeTone = stance
    ? stance.charAt(0).toUpperCase() + stance.slice(1)
    : '';

  const confValues = narratives.map(n => safeNum(n.confidence)).filter((x): x is number => x !== null);
  const confidence = confValues.length ? Math.max(...confValues) : null;

  let priceConfirmation = '';
  const cf = takeaways.filter(t => /^CONFIRMATION/i.test(t)).length;
  const inv = takeaways.filter(t => /^INVALIDATION/i.test(t)).length;
  const unc = takeaways.filter(t => /^UNCLEAR/i.test(t)).length;
  if (cf || inv || unc) {
    if (cf > inv && cf > unc) priceConfirmation = 'Confirmed';
    else if (inv > cf && inv > unc) priceConfirmation = 'Contradicted';
    else priceConfirmation = 'Mixed';
  }

  const findTakeaway = (re: RegExp) => takeaways
    .find(t => re.test(t))
    ?.replace(re, '').replace(/^[:\s]+/, '').trim();

  const bullets = [
    { label: 'Reality', text: firstNonEmpty(findTakeaway(/^REALITY[:\s]*/i)) },
    { label: 'Story', text: firstNonEmpty(findTakeaway(/^STORY[:\s]*/i)) },
    { label: 'Price', text: firstNonEmpty(findTakeaway(/^PRICE[:\s]*/i)) },
  ];
  if (bullets.every(b => !b.text) && fullSummary) {
    const sentences = fullSummary.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(Boolean);
    if (sentences[0]) bullets[0].text = sentences[0];
    if (sentences[1]) bullets[1].text = sentences[1];
    if (sentences[2]) bullets[2].text = sentences.slice(2).join(' ');
  }

  return {
    regimeTone,
    primaryGap: gap,
    primaryArchetype: archetype,
    priceConfirmation,
    confidence,
    bullets: bullets.filter(b => b.text),
    fullSummary,
    asof: safeStr(data.asof_utc),
    model: safeStr(meta.model ?? data.model),
  };
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
      confidence: safeNum(n.confidence),
      thesis: parsed.STORY ? '' : truncate(whyNow, 160),
      reality: parsed.REALITY || firstNonEmpty(...keyCatalysts.slice(0, 1)),
      story: parsed.STORY || (parsed.REALITY ? '' : truncate(whyNow, 140)),
      price: parsed.PRICE || safeStr(n.price_action),
      gap: parsed.GAP || safeStr(n.gap),
      archetype: parsed.ARCHETYPE || safeStr(n.archetype),
      falsifier: parsed.FALSIFIER || whatWouldChange[0] || '',
      allFalsifiers: whatWouldChange,
      catalysts: keyCatalysts,
    };
  });
}

type Theme = ReturnType<typeof normalizeDominantThemes>[0];

function extractInefficiencyRows(data: AnyRecord, themes: Theme[]) {
  // Prefer the explicit inefficiency_map produced by prompt v3 synthesis.
  const explicit = safeArray<AnyRecord>(data.inefficiency_map);
  if (explicit.length > 0) {
    return explicit
      .map(r => ({
        subject: safeStr(r.subject),
        gap: safeStr(r.gap),
        archetype: safeStr(r.archetype),
        archetypeId: safeStr(r.archetype_id),
        confidence: safeNum(r.confidence),
        falsifier: safeStr(r.falsifier),
        evidence: safeStr(r.evidence),
        taxonomyBasis: safeStr(r.taxonomy_basis),
        underlyingGapType: safeStr(r.underlying_gap_type),
      }))
      .filter(r => r.subject && (r.gap || r.archetype));
  }

  // Fallback: derive from dominant themes for older snapshots.
  return themes
    .map(t => ({
      subject: t.title,
      gap: t.gap,
      archetype: t.archetype,
      archetypeId: '' as string,
      confidence: t.confidence,
      falsifier: t.falsifier,
      evidence: '' as string,
      taxonomyBasis: '' as string,
      underlyingGapType: '' as string,
    }))
    .filter(r => r.subject && (r.gap || r.archetype));
}

function extractTopWatchpoints(data: AnyRecord, themes: Theme[]): string[] {
  const fromUnknowns = safeArray<string>(data.unknowns).filter(Boolean);
  const fromCounter = safeArray<string>(data.counter_narratives).filter(Boolean);
  const fromThemes = themes
    .flatMap(t => [t.falsifier, ...t.allFalsifiers.slice(1)])
    .filter(Boolean);
  // De-dupe roughly by lower-cased prefix
  const seen = new Set<string>();
  const dedupe = (arr: string[]) => arr.filter(s => {
    const k = s.slice(0, 60).toLowerCase();
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  return dedupe([...fromUnknowns, ...fromCounter, ...fromThemes]).slice(0, 3);
}

function extractCounterNarratives(data: AnyRecord): string[] {
  return safeArray<string>(data.counter_narratives).filter(Boolean);
}
function extractFalsifiers(data: AnyRecord, themes: Theme[]): string[] {
  const fromTakeaways = safeArray<string>(data.raw_takeaways)
    .filter(t => /^(FALSIFIER|INVALIDATION)/i.test(t))
    .map(t => t.replace(/^(FALSIFIER|INVALIDATION)[:\s]*/i, '').trim());
  const fromThemes = themes.flatMap(t => t.allFalsifiers);
  return Array.from(new Set([...fromTakeaways, ...fromThemes].filter(Boolean)));
}
function extractUnknowns(data: AnyRecord): string[] {
  return safeArray<string>(data.unknowns).filter(Boolean);
}

// ─────────────────────────────────────────────────────────────
// Evidence prioritization
// ─────────────────────────────────────────────────────────────
const STRENGTH_SCORE: Record<string, number> = {
  high: 4,
  medium_high: 3,
  medium: 2,
  low_to_medium: 1,
  weak: 0,
};
const FUNDAMENTAL_TAGS = new Set([
  'macro_data', 'inflation_data', 'labor_data', 'growth_data', 'credit_data',
  'earnings_result', 'guidance_update', 'company_fundamental', 'policy_signal',
  'commodity_fundamental',
]);
const NEGATIVE_TAGS = new Set(['low_market_relevance', 'boilerplate_or_paywall']);

function scoreEvidence(item: AnyRecord, lane: 'reality' | 'story' | 'price'): number {
  let s = 0;
  s += STRENGTH_SCORE[safeStr(item.evidence_strength)] ?? 0;
  const tags = new Set(safeArray<string>(item.content_tags));
  for (const t of tags) {
    if (FUNDAMENTAL_TAGS.has(t)) s += lane === 'reality' ? 2 : 0.5;
    if (NEGATIVE_TAGS.has(t)) s -= 4;
  }
  const mrs = safeNum(item.market_relevance_score);
  if (mrs !== null) s += Math.min(2, Math.max(-2, mrs));
  const rank = safeNum(item.rank_score);
  if (rank !== null) s += Math.min(1.5, rank * 0.15);
  // Newness bonus
  if (item.is_new_vs_prior) s += 0.5;
  return s;
}

function getKeyEvidence(data: AnyRecord) {
  const ledgers = ledgersFromMeta((data._meta ?? {}) as AnyRecord);
  const policy = safeArray<AnyRecord>(ledgers.policy_ledger);
  const fundamental = safeArray<AnyRecord>(ledgers.fundamental_ledger)
    .filter(i => !i.is_duplicate_fundamental);
  const narrative = safeArray<AnyRecord>(ledgers.narrative_ledger);

  const reality = [...policy, ...fundamental]
    .map(item => ({ item, score: scoreEvidence(item, 'reality') }))
    .sort((a, b) => b.score - a.score)
    .map(x => x.item);

  const story = narrative
    .map(item => ({ item, score: scoreEvidence(item, 'story') }))
    .sort((a, b) => b.score - a.score)
    .map(x => x.item);

  return {
    reality: reality.slice(0, 4),
    story: story.slice(0, 4),
    realityFull: reality,
    storyFull: story,
  };
}

// ─────────────────────────────────────────────────────────────
// Price summary helpers
// ─────────────────────────────────────────────────────────────
function getPriceLedgerEntries(data: AnyRecord): unknown[] {
  return safeArray(ledgersFromMeta((data._meta ?? {}) as AnyRecord).price_ledger);
}

function extractPriceSummary(data: AnyRecord) {
  const entries = getPriceLedgerEntries(data);
  const ca = findPriceLedgerEntry(entries, 'cross_asset_returns');
  const sec = findPriceLedgerEntry(entries, 'sector_returns');
  const sn = findPriceLedgerEntry(entries, 'single_name_returns');
  const rels = findPriceLedgerEntry(entries, 'relationship_signals');

  // Prefer the explicit price_summary the synthesis returns (prompt v3+).
  // Keep computing the raw arrays below so the tabs/tables still render.
  const explicitPS = (data.price_summary ?? null) as AnyRecord | null;

  const caAll = safeArray<AnyRecord>(((ca?.items as AnyRecord)?.all as AnyRecord[]) ?? []);
  const secAll = safeArray<AnyRecord>(((sec?.items as AnyRecord)?.all as AnyRecord[]) ?? []);
  const snAll = safeArray<AnyRecord>(((sn?.items as AnyRecord)?.all as AnyRecord[]) ?? [])
    .filter(a => getReturn1D(a) !== null);
  const relItems = safeArray<AnyRecord>((rels?.items as AnyRecord[]) ?? []);

  const sortByR = (arr: AnyRecord[]) => [...arr]
    .filter(a => getReturn1D(a) !== null)
    .sort((a, b) => (getReturn1D(b) ?? 0) - (getReturn1D(a) ?? 0));

  const caSorted = sortByR(caAll);
  const secSorted = sortByR(secAll);

  // Cross-Asset Read — top 3 winners
  const caTop = caSorted.slice(0, 3).map(a => `${safeStr(a.ticker)} ${formatPct(getReturn1D(a))}`).join(', ');
  const caRead = (() => {
    const wins = caSorted.slice(0, 3).map(a => safeStr(a.ticker));
    if (wins.includes('SPY') && wins.includes('QQQ')) return 'Equities resilient';
    if (caSorted[0] && (getReturn1D(caSorted[0]) ?? 0) < 0) return 'Risk-off across the board';
    return wins.length ? 'Mixed cross-asset tape' : '';
  })();

  // Sector Read — top leader + bottom laggard
  const sectorLeader = secSorted[0];
  const sectorLag = secSorted[secSorted.length - 1];
  const secHeadline = secSorted.length
    ? [
      sectorLeader ? `${safeStr(sectorLeader.ticker)} ${formatPct(getReturn1D(sectorLeader))}` : '',
      sectorLag && sectorLag !== sectorLeader ? `${safeStr(sectorLag.ticker)} ${formatPct(getReturn1D(sectorLag))}` : '',
    ].filter(Boolean).join(', ')
    : '';
  const secRead = sectorLeader ? `${safeStr(sectorLeader.name) || safeStr(sectorLeader.ticker)} led${sectorLag && sectorLag !== sectorLeader ? `, ${safeStr(sectorLag.name) || safeStr(sectorLag.ticker)} lagged` : ''}` : '';

  // Timeframe Read — find an asset with notable 1D vs 1M divergence
  const allAssets = [...caAll, ...secAll, ...snAll];
  let timeframeHeadline = '';
  let timeframeRead = '';
  for (const a of allAssets) {
    const rets = getReturns(a);
    const r1d = rets['1D'];
    const r1m = rets['1M'];
    if (r1d !== null && r1m !== null && Math.abs(r1m) > 8 && Math.sign(r1d) !== Math.sign(r1m)) {
      const ticker = safeStr(a.ticker);
      timeframeHeadline = `${ticker} ${formatPct(r1d)} 1D, ${formatPct(r1m)} 1M`;
      timeframeRead = r1d < 0 && r1m > 0
        ? 'Short-term pullback within uptrend'
        : 'Bounce within downtrend — higher-timeframe trend intact';
      break;
    }
  }

  // Relationship Read — most extreme |1D|
  const relSorted = [...relItems]
    .map(r => ({ rel: r, v: Math.abs(getReturn1D(r) ?? 0) }))
    .sort((a, b) => b.v - a.v);
  const topRel = relSorted[0]?.rel;
  const relHeadline = topRel ? `${safeStr(topRel.name)} ${formatPct(getReturn1D(topRel))}` : '';
  const relRead = topRel ? truncate(safeStr(topRel.interpretation), 80) : '';

  // Prefer explicit price_summary read for the "read" line; keep the
  // heuristic headline (which is data, not interpretation) so users always
  // see the actual numbers.
  const psRead = (k: 'cross_asset' | 'sector' | 'timeframe' | 'relationship'): string => {
    if (!explicitPS) return '';
    const v = safeStr((explicitPS as AnyRecord)[k]);
    if (!v || /price evidence unavailable/i.test(v)) return '';
    return v;
  };

  return {
    crossAsset:   { headline: caTop,             read: psRead('cross_asset')  || caRead },
    sector:       { headline: secHeadline,       read: psRead('sector')       || secRead },
    timeframe:    { headline: timeframeHeadline, read: psRead('timeframe')    || timeframeRead },
    relationship: { headline: relHeadline,       read: psRead('relationship') || relRead },
    raw: { caAll, secAll, snAll, relItems, horizons: safeArray<string>(ca?.horizons as string[]) },
  };
}

// ─────────────────────────────────────────────────────────────
// Tokens — local color sugar
// ─────────────────────────────────────────────────────────────
const STANCE_COLOR: Record<string, string> = {
  bullish: T.up,
  bearish: T.dn,
  neutral: T.wa,
  cautious: T.wa,
  mixed: T.wa,
};

function Tabs({
  tabs, defaultIndex = 0,
}: {
  tabs: { label: string; render: () => React.ReactNode; hidden?: boolean }[];
  defaultIndex?: number;
}) {
  const visible = tabs.filter(t => !t.hidden);
  const [active, setActive] = useState(Math.min(defaultIndex, Math.max(0, visible.length - 1)));
  return (
    <div>
      <div style={{
        display: 'flex', gap: '4px', borderBottom: `1px solid ${T.borderSub}`,
        marginBottom: '16px',
      }}>
        {visible.map((t, i) => (
          <button
            key={t.label}
            onClick={() => setActive(i)}
            style={{
              border: 'none', background: 'none', cursor: 'pointer',
              fontFamily: T.sans, fontSize: '12.5px', fontWeight: 600,
              color: i === active ? T.text : T.textMuted,
              padding: '10px 14px', position: 'relative', top: '1px',
              borderBottom: i === active ? `2px solid ${T.accent}` : '2px solid transparent',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div>{visible[active]?.render()}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Analysis Controls — search-style; no manual synthesize button.
// The page automatically loads the cached read for the ticker entered.
// ─────────────────────────────────────────────────────────────
function AnalysisControls({
  ticker, setTicker, statusLine,
}: {
  ticker: string;
  setTicker: (v: string) => void;
  statusLine?: React.ReactNode;
}) {
  const [draft, setDraft] = useState(ticker);
  useEffect(() => { setDraft(ticker); }, [ticker]);
  const commit = () => {
    const next = draft.toUpperCase().trim().replace(/\s+/g, '').replace('.', '-');
    if (next && next !== ticker) setTicker(next);
  };
  return (
    <Card padded={false}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '12px',
        flexWrap: 'wrap', padding: '14px 18px',
      }}>
        <span style={{
          fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.1em',
          textTransform: 'uppercase', color: T.label, fontWeight: 600, flexShrink: 0,
        }}>Analyze narrative for</span>
        <input
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => { if (e.key === 'Enter') { e.currentTarget.blur(); } }}
          placeholder="SPY"
          style={{
            flex: '1 1 220px', fontFamily: T.mono, fontSize: '13.5px',
            color: T.text, background: T.surfaceMuted,
            border: `1px solid ${T.borderSub}`, borderRadius: '8px',
            padding: '10px 14px', outline: 'none', letterSpacing: '0.05em',
          }}
        />
        {statusLine}
      </div>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Executive Snapshot
// ─────────────────────────────────────────────────────────────
function ChipCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  if (!value) return null;
  return (
    <div style={{
      flex: '1 1 180px',
      minWidth: 0,
      padding: '12px 14px',
      background: T.surfaceMuted,
      border: `1px solid ${T.borderSub}`,
      borderRadius: '10px',
      borderLeft: accent ? `3px solid ${accent}` : `1px solid ${T.borderSub}`,
    }}>
      <div style={{
        fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.12em',
        textTransform: 'uppercase', color: T.textMuted,
        fontWeight: 600, marginBottom: '4px',
      }}>{label}</div>
      <div style={{
        fontFamily: T.sans, fontSize: '13.5px', color: T.text,
        fontWeight: 500, lineHeight: 1.45,
        wordBreak: 'break-word',
      }}>{value}</div>
    </div>
  );
}

function ExecutiveSnapshot({ data }: { data: AnyRecord }) {
  const s = useMemo(() => extractExecutiveSnapshot(data), [data]);
  const [openSummary, setOpenSummary] = useState(false);

  const stanceColor = STANCE_COLOR[s.regimeTone.toLowerCase()] ?? T.textMuted;
  const asof = s.asof ? new Date(s.asof).toLocaleString() : '';

  const bulletColors: Record<string, string> = {
    Reality: T.up,
    Story: T.accent,
    Price: T.navy,
  };

  return (
    <Card title="Executive Snapshot" meta={asof} prominent>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
        {/* Top row: classification chips */}
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: '10px',
        }}>
          {s.regimeTone ? (
            <ChipCard label="Regime Tone" value={s.regimeTone} accent={stanceColor} />
          ) : null}
          {s.primaryGap ? (
            <ChipCard label="Primary Gap" value={s.primaryGap} accent={T.wa} />
          ) : null}
          {s.primaryArchetype ? (
            <ChipCard label="Primary Archetype" value={s.primaryArchetype} accent={T.accent} />
          ) : null}
          {s.priceConfirmation ? (
            <ChipCard label="Price Confirmation" value={s.priceConfirmation} />
          ) : null}
          {s.confidence !== null ? (
            <ChipCard label="Confidence" value={`${s.confidence}/100`} />
          ) : null}
        </div>

        {/* Bullet row */}
        {s.bullets.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {s.bullets.map(b => (
              <div key={b.label} style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                <span style={{
                  flexShrink: 0,
                  fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.12em',
                  textTransform: 'uppercase', color: bulletColors[b.label] ?? T.text,
                  fontWeight: 700, marginTop: '4px',
                  width: '60px',
                }}>{b.label}</span>
                <p style={{
                  margin: 0, fontFamily: T.sans, fontSize: '14.5px',
                  color: T.text, lineHeight: 1.6,
                }}>{b.text}</p>
              </div>
            ))}
          </div>
        ) : null}

        {/* Full synthesis disclosure */}
        {s.fullSummary ? (
          <div style={{ borderTop: `1px solid ${T.borderSub}`, paddingTop: '10px' }}>
            <button
              onClick={() => setOpenSummary(o => !o)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontFamily: T.sans, fontSize: '12px', fontWeight: 600,
                color: T.accentDark, padding: 0,
              }}
            >
              {openSummary ? '▾ Hide full synthesis' : '▸ Show full synthesis'}
            </button>
            {openSummary ? (
              <p style={{
                marginTop: '10px',
                fontFamily: T.sans, fontSize: '13.5px',
                color: T.textSub, lineHeight: 1.7,
              }}>{s.fullSummary}</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Dominant Themes
// ─────────────────────────────────────────────────────────────
function ThemeRow({ label, color, value }: { label: string; color: string; value: string }) {
  if (!value) return null;
  return (
    <div style={{ display: 'flex', gap: '10px', marginBottom: '6px' }}>
      <span style={{
        fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.1em',
        textTransform: 'uppercase', color, fontWeight: 700,
        width: '64px', flexShrink: 0, paddingTop: '3px',
      }}>{label}</span>
      <p style={{
        margin: 0, fontFamily: T.sans, fontSize: '13px',
        color: T.textSub, lineHeight: 1.55, flex: 1,
      }}>{value}</p>
    </div>
  );
}

function DominantThemeCard({ theme }: { theme: Theme }) {
  const sc = STANCE_COLOR[theme.stance.toLowerCase()] ?? T.mid;
  return (
    <div style={{
      padding: '16px 18px',
      background: T.surfaceMuted,
      border: `1px solid ${T.borderSub}`,
      borderRadius: '14px',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        alignItems: 'flex-start', gap: '12px', marginBottom: '10px',
      }}>
        <span style={{
          fontFamily: T.sans, fontSize: '14.5px', fontWeight: 600,
          color: T.text, lineHeight: 1.4,
        }}>{theme.title}</span>
        <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
          {theme.stance ? <Chip label={theme.stance} color={sc} /> : null}
          {theme.confidence !== null ? <Chip label={`${theme.confidence}/100`} /> : null}
        </div>
      </div>

      {theme.thesis ? (
        <p style={{
          margin: '0 0 12px',
          fontFamily: T.sans, fontSize: '13px',
          color: T.textSub, lineHeight: 1.55,
        }}>{theme.thesis}</p>
      ) : null}

      <ThemeRow label="Reality" color={T.up} value={theme.reality} />
      <ThemeRow label="Story" color={T.accent} value={theme.story} />
      <ThemeRow label="Price" color={T.navy} value={theme.price} />
      <ThemeRow label="Gap" color={T.wa} value={theme.gap} />
      <ThemeRow label="Falsifier" color={T.dn} value={theme.falsifier} />

      {theme.catalysts.length > 0 || theme.allFalsifiers.length > 1 ? (
        <div style={{ marginTop: '10px' }}>
          <Collapsible label="Details">
            {theme.catalysts.length > 0 ? (
              <div style={{ marginBottom: '10px' }}>
                <MutedLabel>Catalysts</MutedLabel>
                {theme.catalysts.map((c, i) => (
                  <p key={i} style={{
                    margin: '0 0 4px', fontFamily: T.sans, fontSize: '12.5px',
                    color: T.textSub, lineHeight: 1.5,
                  }}>· {c}</p>
                ))}
              </div>
            ) : null}
            {theme.allFalsifiers.length > 1 ? (
              <div>
                <MutedLabel>Other falsifiers</MutedLabel>
                {theme.allFalsifiers.slice(1).map((f, i) => (
                  <p key={i} style={{
                    margin: '0 0 4px', fontFamily: T.sans, fontSize: '12.5px',
                    color: T.textSub, lineHeight: 1.5,
                  }}>· {f}</p>
                ))}
              </div>
            ) : null}
          </Collapsible>
        </div>
      ) : null}
    </div>
  );
}

function DominantThemes({ themes }: { themes: Theme[] }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? themes : themes.slice(0, 3);
  return (
    <Card title="Dominant Themes" meta={`${themes.length} theme${themes.length !== 1 ? 's' : ''}`}>
      {visible.length === 0 ? (
        <EmptyState msg="No dominant themes identified" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {visible.map((t, i) => <DominantThemeCard key={i} theme={t} />)}
        </div>
      )}
      {themes.length > 3 ? (
        <button
          onClick={() => setShowAll(s => !s)}
          style={{
            marginTop: '14px', background: 'none', border: 'none',
            cursor: 'pointer', padding: 0,
            fontFamily: T.sans, fontSize: '12px', fontWeight: 600, color: T.accentDark,
          }}
        >
          {showAll ? '▾ Show top 3' : `▸ Show all themes (${themes.length})`}
        </button>
      ) : null}
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Inefficiency Map
// ─────────────────────────────────────────────────────────────
function InefficiencyMap({ data, themes }: { data: AnyRecord; themes: Theme[] }) {
  const rows = extractInefficiencyRows(data, themes);
  return (
    <Card title="Inefficiency Map">
      {rows.length === 0 ? (
        <EmptyState msg="No explicit inefficiency classifications were produced in this run." />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {rows.map((row, i) => (
            <div key={i} style={{
              padding: '12px 14px',
              background: T.surfaceMuted,
              border: `1px solid ${T.borderSub}`,
              borderRadius: '12px',
              borderLeft: `3px solid ${T.wa}`,
            }}>
              <div style={{ display: 'flex', gap: '10px', marginBottom: '8px' }}>
                <span style={{
                  fontFamily: T.sans, fontSize: '11px', color: T.textMuted,
                  flexShrink: 0, paddingTop: '2px',
                }}>{i + 1}.</span>
                <span style={{
                  fontFamily: T.sans, fontSize: '13.5px', fontWeight: 600,
                  color: T.text, lineHeight: 1.4,
                }}>{row.subject}</span>
              </div>
              {row.gap ? (
                <div style={{
                  fontFamily: T.sans, fontSize: '12.5px', color: T.textSub,
                  lineHeight: 1.5, marginBottom: row.archetype || row.confidence !== null ? '8px' : 0,
                }}>{row.gap}</div>
              ) : null}
              {row.archetype || row.confidence !== null ? (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {row.archetype ? <Chip label={truncate(row.archetype, 40)} color={T.accent} /> : null}
                  {row.underlyingGapType ? <Chip label={row.underlyingGapType.replace(/_/g, ' ')} /> : null}
                  {row.confidence !== null ? <Chip label={`${row.confidence}/100`} /> : null}
                </div>
              ) : null}
              {row.taxonomyBasis ? (
                <div style={{
                  marginTop: '10px',
                  paddingTop: '10px',
                  borderTop: `1px solid ${T.borderSub}`,
                  fontFamily: T.sans,
                  fontSize: '12px',
                  color: T.textMuted,
                  lineHeight: 1.5,
                }}>
                  {row.taxonomyBasis}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Price Context
// ─────────────────────────────────────────────────────────────
const HORIZONS_ORDERED = ['1D', '5D', '1M', '3M', 'YTD', '1Y'];

function PriceSummaryCard({ label, headline, read, accent }: {
  label: string; headline: string; read: string; accent: string;
}) {
  if (!headline && !read) return null;
  return (
    <div style={{
      flex: '1 1 220px',
      padding: '14px 16px',
      background: T.surfaceMuted,
      border: `1px solid ${T.borderSub}`,
      borderRadius: '12px',
      borderLeft: `3px solid ${accent}`,
      display: 'flex', flexDirection: 'column', gap: '6px',
    }}>
      <span style={{
        fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.12em',
        textTransform: 'uppercase', color: T.textMuted, fontWeight: 600,
      }}>{label}</span>
      <span style={{
        fontFamily: T.mono, fontSize: '12.5px', color: T.text, fontWeight: 500,
      }}>{headline || '—'}</span>
      {read ? (
        <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textSub, lineHeight: 1.45 }}>
          {read}
        </span>
      ) : null}
    </div>
  );
}

function PriceTable({ items, maxRows }: { items: AnyRecord[]; maxRows?: number }) {
  if (!items.length) return <EmptyState msg="No data" small />;

  const sample = items[0];
  const isMulti = !!sample.returns;
  const visibleHorizons = isMulti
    ? HORIZONS_ORDERED.filter(h => items.some(a => safeNum((a.returns as Record<string, unknown>)?.[h]) !== null))
    : ['1D'];

  const display = typeof maxRows === 'number' ? items.slice(0, maxRows) : items;

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: '12px' }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${T.borderSub}` }}>
            <th style={{ textAlign: 'left', padding: '8px 10px', color: T.textMuted, fontWeight: 500, letterSpacing: '0.04em' }}>Asset</th>
            {visibleHorizons.map(h => (
              <th key={h} style={{ textAlign: 'right', padding: '8px 10px', color: T.textMuted, fontWeight: 500, letterSpacing: '0.04em', minWidth: '60px' }}>{h}</th>
            ))}
            {isMulti ? (
              <th style={{ textAlign: 'left', padding: '8px 10px', color: T.textMuted, fontWeight: 500, letterSpacing: '0.04em' }}>Trend</th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {display.map((asset, i) => {
            const rets = getReturns(asset);
            const tc = (asset.trend_context as AnyRecord) ?? {};
            return (
              <tr key={i} style={{ borderBottom: `1px solid ${T.borderSub}` }}>
                <td style={{ padding: '9px 10px', color: T.text }}>
                  <span style={{ fontWeight: 500 }}>{safeStr(asset.ticker)}</span>
                  {' '}
                  <span style={{ color: T.textMuted, fontSize: '11.5px' }}>{safeStr(asset.name)}</span>
                </td>
                {visibleHorizons.map(h => {
                  const v = rets[h];
                  return (
                    <td key={h} style={{ textAlign: 'right', padding: '9px 10px', color: pctColor(v) }}>
                      {formatPct(v)}
                    </td>
                  );
                })}
                {isMulti ? (
                  <td style={{ padding: '9px 10px', color: T.textMuted, fontSize: '11.5px', maxWidth: '220px' }}>
                    {truncate(safeStr(tc.today_vs_trend), 90)}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RelationshipCards({ items }: { items: AnyRecord[] }) {
  if (!items.length) return <EmptyState msg="No relationship signals available" small />;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
      {items.map((rel, i) => {
        const rets = getReturns(rel);
        const v = rets['1D'] ?? safeNum(rel.value);
        return (
          <div key={i} style={{
            flex: '1 1 280px',
            padding: '12px 14px',
            background: T.surfaceMuted,
            border: `1px solid ${T.borderSub}`,
            borderRadius: '10px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginBottom: '4px' }}>
              <span style={{ fontFamily: T.mono, fontSize: '12px', color: T.text }}>{safeStr(rel.name)}</span>
              <span style={{ fontFamily: T.mono, fontSize: '12px', color: pctColor(v), fontWeight: 600 }}>{formatPct(v)}</span>
            </div>
            <div style={{ fontFamily: T.sans, fontSize: '11.5px', color: T.textMuted, lineHeight: 1.45 }}>
              {truncate(safeStr(rel.interpretation), 100)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function PriceContext({ data }: { data: AnyRecord }) {
  const summary = useMemo(() => extractPriceSummary(data), [data]);
  const [showAllNames, setShowAllNames] = useState(false);

  const { caAll, secAll, snAll, relItems, horizons } = summary.raw;
  const hasData = caAll.length || secAll.length || snAll.length || relItems.length;

  if (!hasData) {
    return (
      <Card title="Price Context">
        <EmptyState msg="Price context unavailable for this run" />
      </Card>
    );
  }

  const meta = horizons.length ? horizons.join(' · ') : undefined;

  const tabs = [
    {
      label: 'Cross-Asset',
      hidden: !caAll.length,
      render: () => <PriceTable items={caAll} />,
    },
    {
      label: 'Sectors',
      hidden: !secAll.length,
      render: () => <PriceTable items={secAll} />,
    },
    {
      label: `Single Names${snAll.length ? ` (${snAll.length})` : ''}`,
      hidden: !snAll.length,
      render: () => (
        <div>
          <PriceTable items={snAll} maxRows={showAllNames ? undefined : 8} />
          {snAll.length > 8 ? (
            <button
              onClick={() => setShowAllNames(v => !v)}
              style={{
                marginTop: '10px', background: 'none', border: 'none', padding: 0,
                cursor: 'pointer', fontFamily: T.sans, fontSize: '12px',
                fontWeight: 600, color: T.accentDark,
              }}
            >
              {showAllNames ? '▾ Show top 8' : `▸ Show all single names (${snAll.length})`}
            </button>
          ) : null}
        </div>
      ),
    },
    {
      label: 'Relationships',
      hidden: !relItems.length,
      render: () => <RelationshipCards items={relItems} />,
    },
  ];

  return (
    <Card title="Price Context" meta={meta}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {/* Summary cards */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
          <PriceSummaryCard label="Cross-Asset Read" headline={summary.crossAsset.headline} read={summary.crossAsset.read} accent={T.accent} />
          <PriceSummaryCard label="Sector Read" headline={summary.sector.headline} read={summary.sector.read} accent={T.up} />
          {summary.timeframe.headline ? (
            <PriceSummaryCard label="Timeframe Read" headline={summary.timeframe.headline} read={summary.timeframe.read} accent={T.wa} />
          ) : null}
          {summary.relationship.headline ? (
            <PriceSummaryCard label="Key Relationship" headline={summary.relationship.headline} read={summary.relationship.read} accent={T.navy} />
          ) : null}
        </div>

        {/* Tabs */}
        <div>
          <Tabs tabs={tabs} />
        </div>
      </div>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Evidence Board
// ─────────────────────────────────────────────────────────────
function EvidenceItem({ item }: { item: AnyRecord }) {
  const strength = safeStr(item.evidence_strength);
  const tags = compactList(safeArray<string>(item.content_tags), 2);
  return (
    <div style={{
      padding: '11px 13px',
      background: T.surfaceMuted,
      border: `1px solid ${T.borderSub}`,
      borderRadius: '10px',
      marginBottom: '8px',
    }}>
      <div style={{
        fontFamily: T.sans, fontSize: '13px',
        color: T.text, lineHeight: 1.5, marginBottom: '5px', fontWeight: 500,
      }}>
        {truncate(safeStr(item.title) || safeStr(item.summary), 140)}
      </div>
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontFamily: T.sans, fontSize: '10.5px', color: T.textMuted }}>{safeStr(item.source)}</span>
        {strength ? <Chip label={strength.replace(/_/g, ' ')} /> : null}
        {tags.map(t => <Chip key={t} label={t.replace(/_/g, ' ')} color={T.accent} />)}
      </div>
    </div>
  );
}

function PriceEvidenceBullets({ data }: { data: AnyRecord }) {
  const summary = extractPriceSummary(data);
  const items: { label: string; text: string }[] = [];
  if (summary.crossAsset.headline) items.push({ label: 'Cross-Asset', text: `${summary.crossAsset.headline} — ${summary.crossAsset.read}` });
  if (summary.sector.headline) items.push({ label: 'Sectors', text: `${summary.sector.headline} — ${summary.sector.read}` });
  if (summary.relationship.headline) items.push({ label: 'Relationship', text: `${summary.relationship.headline} — ${summary.relationship.read}` });
  if (summary.timeframe.headline) items.push({ label: 'Timeframe', text: `${summary.timeframe.headline} — ${summary.timeframe.read}` });

  if (!items.length) return <EmptyState msg="No price signals" small />;

  return (
    <div>
      {items.map((b, i) => (
        <div key={i} style={{
          padding: '10px 12px',
          background: T.surfaceMuted,
          border: `1px solid ${T.borderSub}`,
          borderRadius: '10px',
          marginBottom: '8px',
        }}>
          <div style={{
            fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.1em',
            textTransform: 'uppercase', color: T.textMuted,
            fontWeight: 600, marginBottom: '4px',
          }}>{b.label}</div>
          <div style={{ fontFamily: T.sans, fontSize: '12.5px', color: T.textSub, lineHeight: 1.5 }}>{b.text}</div>
        </div>
      ))}
    </div>
  );
}

function EvidenceBoard({ data }: { data: AnyRecord }) {
  const evidence = useMemo(() => getKeyEvidence(data), [data]);
  const [showAll, setShowAll] = useState(false);

  const col = (title: string, color: string, content: React.ReactNode) => (
    <div style={{ flex: '1 1 240px', minWidth: 0 }}>
      <div style={{
        fontFamily: T.sans, fontSize: '10px', letterSpacing: '0.14em',
        textTransform: 'uppercase', fontWeight: 700, color,
        marginBottom: '12px', paddingBottom: '8px',
        borderBottom: `1px solid ${color}33`,
      }}>{title}</div>
      {content}
    </div>
  );

  const realityShown = showAll ? evidence.realityFull : evidence.reality;
  const storyShown = showAll ? evidence.storyFull : evidence.story;

  return (
    <Card title="Evidence Board">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
          {col('Reality', T.up,
            realityShown.length
              ? realityShown.map((it, i) => <EvidenceItem key={i} item={it} />)
              : <EmptyState msg="No reality evidence" small />
          )}
          {col('Story', T.accent,
            storyShown.length
              ? storyShown.map((it, i) => <EvidenceItem key={i} item={it} />)
              : <EmptyState msg="No narrative evidence" small />
          )}
          {col('Price', T.navy, <PriceEvidenceBullets data={data} />)}
        </div>

        {(evidence.realityFull.length > 4 || evidence.storyFull.length > 4) ? (
          <button
            onClick={() => setShowAll(v => !v)}
            style={{
              alignSelf: 'flex-start', background: 'none', border: 'none',
              cursor: 'pointer', padding: 0,
              fontFamily: T.sans, fontSize: '12px', fontWeight: 600, color: T.accentDark,
            }}
          >
            {showAll ? '▾ Show top evidence only' : '▸ Show all evidence'}
          </button>
        ) : null}
      </div>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Watchpoints
// ─────────────────────────────────────────────────────────────
function Watchpoints({ data, themes }: { data: AnyRecord; themes: Theme[] }) {
  const top = useMemo(() => extractTopWatchpoints(data, themes), [data, themes]);
  const counters = extractCounterNarratives(data);
  const falsifiers = extractFalsifiers(data, themes);
  const unknowns = extractUnknowns(data);

  if (!top.length && !counters.length && !falsifiers.length && !unknowns.length) return null;

  return (
    <Card title="Watchpoints">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {top.length > 0 ? (
          <div>
            <MutedLabel>Top Watchpoints</MutedLabel>
            <ol style={{ margin: 0, paddingLeft: '20px' }}>
              {top.map((w, i) => (
                <li key={i} style={{
                  fontFamily: T.sans, fontSize: '13.5px',
                  color: T.text, lineHeight: 1.55, marginBottom: '6px',
                }}>{w}</li>
              ))}
            </ol>
          </div>
        ) : null}

        {counters.length > 0 ? (
          <Collapsible label="Counter-Narratives" count={counters.length}>
            {counters.map((c, i) => (
              <p key={i} style={{
                margin: '0 0 6px', fontFamily: T.sans, fontSize: '12.5px',
                color: T.textSub, lineHeight: 1.55,
              }}>· {c}</p>
            ))}
          </Collapsible>
        ) : null}

        {falsifiers.length > 0 ? (
          <Collapsible label="Falsifiers" count={falsifiers.length}>
            {falsifiers.map((f, i) => (
              <p key={i} style={{
                margin: '0 0 6px', fontFamily: T.sans, fontSize: '12.5px',
                color: T.textSub, lineHeight: 1.55,
              }}>· {f}</p>
            ))}
          </Collapsible>
        ) : null}

        {unknowns.length > 0 ? (
          <Collapsible label="Unknowns" count={unknowns.length}>
            {unknowns.map((u, i) => (
              <p key={i} style={{
                margin: '0 0 6px', fontFamily: T.sans, fontSize: '12.5px',
                color: T.textSub, lineHeight: 1.55,
              }}>· {u}</p>
            ))}
          </Collapsible>
        ) : null}
      </div>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Information Set (collapsed by default)
// ─────────────────────────────────────────────────────────────
function InformationSet({ data }: { data: AnyRecord }) {
  const meta = (data._meta ?? {}) as AnyRecord;
  const lc = (meta.ledger_counts ?? {}) as AnyRecord;
  const ledgers = ledgersFromMeta(meta);
  const total = safeNum(meta.total_items_in_bundle) ?? 0;
  const selected = safeNum(meta.items_selected_for_llm) ?? 0;
  const filteredCount = safeNum((meta.filtered_items_summary as AnyRecord)?.count) ?? 0;
  const activeLedgers = Object.keys(lc).filter(k => safeNum(lc[k]) && safeNum(lc[k])! > 0).length;
  const hasPrice = (safeArray(ledgers.price_ledger).length) > 0;

  const oneLine = `${total} sources scanned · ${selected} selected · ${activeLedgers} ledgers active${hasPrice ? ' · price context active' : ''}${filteredCount > 0 ? ` · ${filteredCount} filtered` : ''}`;

  const roleCounts = (meta.role_counts ?? {}) as AnyRecord;
  const tagCounts = (meta.content_tag_counts ?? {}) as AnyRecord;
  const filtered = (meta.filtered_items_summary ?? {}) as AnyRecord;
  const filteredReasons = (filtered.reasons ?? {}) as AnyRecord;

  return (
    <Card>
      <Collapsible label={oneLine}>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '16px', paddingTop: '6px',
        }}>
          {Object.keys(lc).length > 0 ? (
            <div>
              <MutedLabel>By ledger</MutedLabel>
              {Object.entries(lc).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontFamily: T.sans, fontSize: '12px' }}>
                  <span style={{ color: T.textSub }}>{k.replace(/_/g, ' ')}</span>
                  <span style={{ color: T.textMuted, fontFamily: T.mono }}>{String(v)}</span>
                </div>
              ))}
            </div>
          ) : null}
          {Object.keys(roleCounts).length > 0 ? (
            <div>
              <MutedLabel>By role</MutedLabel>
              {Object.entries(roleCounts).slice(0, 8).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontFamily: T.sans, fontSize: '12px' }}>
                  <span style={{ color: T.textSub }}>{k.replace(/_/g, ' ')}</span>
                  <span style={{ color: T.textMuted, fontFamily: T.mono }}>{String(v)}</span>
                </div>
              ))}
            </div>
          ) : null}
          {Object.keys(tagCounts).length > 0 ? (
            <div>
              <MutedLabel>Content tags</MutedLabel>
              {Object.entries(tagCounts).slice(0, 8).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontFamily: T.sans, fontSize: '12px' }}>
                  <span style={{ color: T.textSub }}>{k.replace(/_/g, ' ')}</span>
                  <span style={{ color: T.textMuted, fontFamily: T.mono }}>{String(v)}</span>
                </div>
              ))}
            </div>
          ) : null}
          {Object.keys(filteredReasons).length > 0 ? (
            <div>
              <MutedLabel>Filtered reasons</MutedLabel>
              {Object.entries(filteredReasons).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', fontFamily: T.sans, fontSize: '12px' }}>
                  <span style={{ color: T.textSub }}>{k.replace(/_/g, ' ')}</span>
                  <span style={{ color: T.textMuted, fontFamily: T.mono }}>{String(v)}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </Collapsible>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Advanced Raw Ledgers (debug, collapsed)
// ─────────────────────────────────────────────────────────────
function AdvancedRawLedgers({ data }: { data: AnyRecord }) {
  const meta = (data._meta ?? {}) as AnyRecord;
  const ledgers = ledgersFromMeta(meta);

  return (
    <Card>
      <Collapsible label="Advanced · Raw Ledgers & Debug">
        <div style={{ paddingTop: '6px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {Object.entries(ledgers).map(([key, val]) => {
            const items = safeArray<AnyRecord>(val);
            if (!items.length) return null;
            return (
              <Collapsible key={key} label={key.replace(/_/g, ' ')} count={items.length}>
                <div style={{ paddingTop: '6px' }}>
                  {items.slice(0, 30).map((item, i) =>
                    item.type || item.kind ? (
                      <div key={i} style={{
                        marginBottom: '4px', padding: '6px 10px',
                        background: T.surfaceMuted, borderRadius: '6px',
                        fontFamily: T.mono, fontSize: '11px', color: T.textMuted,
                      }}>{String(item.type ?? item.kind)}</div>
                    ) : (
                      <EvidenceItem key={i} item={item} />
                    )
                  )}
                  {items.length > 30 ? (
                    <div style={{ fontFamily: T.sans, fontSize: '11px', color: T.textMuted, paddingTop: '6px' }}>
                      … and {items.length - 30} more
                    </div>
                  ) : null}
                </div>
              </Collapsible>
            );
          })}
          <Collapsible label="Run metadata">
            <div style={{ paddingTop: '6px', fontFamily: T.mono, fontSize: '11.5px', color: T.textSub }}>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                {JSON.stringify({
                  total_items_in_bundle: meta.total_items_in_bundle,
                  items_selected_for_llm: meta.items_selected_for_llm,
                  prior_snapshot_found: meta.prior_snapshot_found,
                  lookback_hours: meta.lookback_hours,
                }, null, 2)}
              </pre>
            </div>
          </Collapsible>
        </div>
      </Collapsible>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Section: Market Psychology Curve
// ─────────────────────────────────────────────────────────────
const CYCLE_STAGES = [
  'Optimism', 'Excitement', 'Thrill', 'Euphoria',
  'Anxiety', 'Denial', 'Fear', 'Desperation',
  'Panic', 'Capitulation', 'Despondency', 'Depression',
  'Hope', 'Relief',
];

// Cycle geometry — generated programmatically so:
//   1. Stage points are equidistant along the x axis.
//   2. The peak (Euphoria) is as smoothly rounded as the trough (Despondency)
//      — both follow the same cosine; the path is sampled at ~80 sub-points
//      so straight-line segments don't introduce angular kinks.
//   3. The wave amplitude is intentionally compressed relative to viewBox
//      height so the whole SVG can render larger (bigger text + nodes) in
//      the same card width.
const CYCLE_VIEW_W = 480;
const CYCLE_VIEW_H = 240;
const CYCLE_X_LEFT = 38;
const CYCLE_X_RIGHT = 442;
const CYCLE_MID_Y = 120;
const CYCLE_AMP = 64;
const CYCLE_PEAK_INDEX = 3; // Euphoria

function _cycleY(continuousIndex: number): number {
  // Full period spans 14 stages; cosine peaks at i = CYCLE_PEAK_INDEX.
  const phase = ((continuousIndex - CYCLE_PEAK_INDEX) * 2 * Math.PI) / CYCLE_STAGES.length;
  return CYCLE_MID_Y - CYCLE_AMP * Math.cos(phase);
}

function _cycleX(continuousIndex: number): number {
  return CYCLE_X_LEFT + (continuousIndex * (CYCLE_X_RIGHT - CYCLE_X_LEFT)) / (CYCLE_STAGES.length - 1);
}

// Equidistant x positions for the 14 stage markers.
const CYCLE_POINTS: Array<[number, number]> = CYCLE_STAGES.map((_, i) => {
  return [
    Math.round(_cycleX(i) * 10) / 10,
    Math.round(_cycleY(i) * 10) / 10,
  ] as [number, number];
});

// Smooth path sampled at high resolution so peak and trough have matching roundness.
const CYCLE_PATH_D: string = (() => {
  const N = 80;
  const segs: string[] = [];
  for (let k = 0; k < N; k++) {
    const i = (k * (CYCLE_STAGES.length - 1)) / (N - 1);
    segs.push(`${_cycleX(i).toFixed(2)},${_cycleY(i).toFixed(2)}`);
  }
  return 'M ' + segs.join(' L ');
})();

function inferCycleStage(data: AnyRecord | null): { stage: string; subject: string } {
  if (!data) return { stage: '', subject: '' };
  const direct = safeArray<AnyRecord>(data.cycle_positioning as unknown)
    .concat(safeArray<AnyRecord>((data._meta as AnyRecord)?.cycle_positioning as unknown));
  if (direct[0]) {
    return {
      stage: safeStr(direct[0].cycle_stage || direct[0].stage),
      subject: safeStr(direct[0].subject) || 'Market',
    };
  }
  // Fallback: derive a rough stage from regime tone
  const stance = safeStr(safeArray<AnyRecord>(data.dominant_narratives)[0]?.stance).toLowerCase();
  if (stance.includes('bull') || stance.includes('optimistic')) return { stage: 'Optimism', subject: 'Market' };
  if (stance.includes('bear')) return { stage: 'Despondency', subject: 'Market' };
  if (stance.includes('cauti') || stance.includes('mixed') || stance.includes('neutral')) return { stage: 'Anxiety', subject: 'Market' };
  return { stage: '', subject: '' };
}

function MarketPsychologyCurve({ data }: { data: AnyRecord | null }) {
  const { stage, subject } = inferCycleStage(data);
  const activeIndex = CYCLE_STAGES.findIndex(s => s.toLowerCase() === stage.toLowerCase());
  const hasStage = activeIndex >= 0;

  return (
    <Card title="Cycle Positioning">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{
          background: T.surfaceMuted,
          border: `1px solid ${T.borderSub}`,
          borderRadius: '12px',
          padding: '14px 12px 8px',
        }}>
          <svg
            viewBox={`0 0 ${CYCLE_VIEW_W} ${CYCLE_VIEW_H}`}
            style={{ width: '100%', height: 'auto', display: 'block' }}
          >
            {/* Smooth curve — sampled densely so peak and trough are equally round */}
            <path
              d={CYCLE_PATH_D}
              fill="none"
              stroke={T.border}
              strokeWidth="2.5"
              strokeLinecap="round"
            />
            {/* Stage nodes — equidistant in x */}
            {CYCLE_POINTS.map(([x, y], i) => {
              const isActive = i === activeIndex;
              return (
                <g key={i}>
                  <circle
                    cx={x} cy={y}
                    r={isActive ? 9 : 4.5}
                    fill={isActive ? T.accent : T.surface}
                    stroke={isActive ? T.accentDark : T.border}
                    strokeWidth={isActive ? 2 : 1.25}
                  />
                  {isActive ? (
                    <text
                      x={x} y={y - 18}
                      textAnchor="middle"
                      fontFamily={T.sans}
                      fontSize="14"
                      fontWeight={700}
                      fill={T.navy}
                    >{CYCLE_STAGES[i]}</text>
                  ) : null}
                </g>
              );
            })}
            {/* Anchor labels at the extremes */}
            <text x={CYCLE_X_LEFT} y={CYCLE_VIEW_H - 14} fontFamily={T.sans} fontSize="12" fill={T.textMuted}>Optimism</text>
            <text x={_cycleX(CYCLE_PEAK_INDEX)} y={28} textAnchor="middle" fontFamily={T.sans} fontSize="12" fill={T.textMuted}>Euphoria</text>
            <text x={_cycleX(10)} y={CYCLE_VIEW_H - 14} textAnchor="middle" fontFamily={T.sans} fontSize="12" fill={T.textMuted}>Despondency</text>
            <text x={CYCLE_X_RIGHT} y={CYCLE_MID_Y + 4} textAnchor="end" fontFamily={T.sans} fontSize="12" fill={T.textMuted}>Relief</text>
          </svg>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
          <span style={{
            fontFamily: T.sans, fontSize: '11px', letterSpacing: '0.1em',
            textTransform: 'uppercase', color: T.textMuted, fontWeight: 600,
          }}>Position</span>
          {hasStage ? (
            <Chip label={`${subject ? subject + ' · ' : ''}${CYCLE_STAGES[activeIndex]}`} color={T.accent} />
          ) : (
            <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted }}>
              Not classified yet
            </span>
          )}
        </div>

        <p style={{
          margin: 0,
          fontFamily: T.sans, fontSize: '11.5px', color: T.textMuted,
          lineHeight: 1.5,
        }}>
          {hasStage
            ? 'Stage inferred from regime tone. A dedicated psychology classifier will replace this read.'
            : 'Maps narrative tone, price behavior, and expectation gaps to the market psychology cycle. Cycle classifier coming soon.'}
        </p>
      </div>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────
type LatestEnvelope = {
  status: 'ready' | 'generating' | 'unsupported' | 'error' | 'cache_miss' | 'llm_blocked';
  cache_hit?: boolean;
  is_mock?: boolean;
  narrative_mode?: 'mock' | 'cache' | 'live';
  ticker?: string;
  subject?: AnyRecord;
  generated_at?: string;
  asof_date?: string;
  message?: string;
  output?: AnyRecord;
  last_cached_result?: { output?: AnyRecord; generated_at?: string } | null;
  last_error?: string;
} & Record<string, unknown>;

export default function NarrativePage() {
  const [ticker, setTicker] = useState('SPY');
  const [stacked, setStacked] = useState(false);

  const authFetcher = useAuthFetcher();
  const canFetch = authFetcher.isReady;

  const { data: latest, error: latestError } = useSWR<LatestEnvelope>(
    canFetch ? `/api/narrative/latest?ticker=${ticker}` : null,
    authFetcher,
    {
      refreshInterval: (data) => (data?.status === 'generating' ? 5000 : 0),
      onError: () => null,
    },
  );

  // Pull the synthesis output regardless of whether it's a fresh cache or a stale fallback
  const result: AnyRecord | null = useMemo(() => {
    if (!latest) return null;
    if (latest.status === 'ready' && latest.output) return latest.output as AnyRecord;
    if (latest.last_cached_result?.output) return latest.last_cached_result.output as AnyRecord;
    return null;
  }, [latest]);

  const apiErrorMessage = latestError instanceof Error
    ? latestError.message
    : latestError
      ? String(latestError)
      : '';
  const status = latest?.status ?? (latestError ? 'error' : 'loading');
  const unavailableMessage = !latest && apiErrorMessage
    ? apiErrorMessage
    : status === 'error'
      ? firstNonEmpty(safeStr(latest?.last_error), safeStr(latest?.message), 'Today’s read will appear once it has been generated.')
    : safeStr(latest?.message) || safeStr(latest?.last_error) || 'Today’s read will appear once it has been generated.';
  const isUnsupported = status === 'unsupported';
  const isGenerating = status === 'generating';
  const isCacheMiss = status === 'cache_miss';
  const isLlmBlocked = status === 'llm_blocked';
  const cacheHit = !!(latest?.cache_hit && status === 'ready');
  const generatedAt = (latest?.generated_at || latest?.last_cached_result?.generated_at) as string | undefined;
  const subject = (latest?.subject ?? ((result?._meta as AnyRecord | undefined)?.subject)) as AnyRecord | undefined;
  const subjectTicker = safeStr(subject?.ticker, safeStr(latest?.ticker, ticker));
  const subjectName = safeStr(subject?.name);
  const subjectSector = safeStr(subject?.sector);
  const modeBadge = latest?.is_mock
    ? 'Mock data'
    : latest?.narrative_mode === 'cache'
      ? 'Cache-only mode'
      : null;

  // Responsive: stack the main grid on narrow viewports
  useEffect(() => {
    const update = () => setStacked(window.innerWidth < 980);
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  const themes = useMemo(() => result ? normalizeDominantThemes(result) : [], [result]);

  // Status pill rendered inside AnalysisControls
  const statusLine = useMemo<React.ReactNode>(() => {
    if (isUnsupported) {
      return (
        <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.wa, fontWeight: 500 }}>
          Reads enabled for S&P 500 and Nasdaq-100 constituents.
        </span>
      );
    }
    if (isGenerating) {
      return (
        <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted }}>
          Generating today&apos;s {ticker} read… typically 1–2 min.
        </span>
      );
    }
    if (status === 'error') {
      return (
        <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.dn }}>
          {result ? "Could not load today's read. Showing latest available cached read." : "Could not load today's read."}
        </span>
      );
    }
    if (cacheHit && generatedAt) {
      const t = new Date(generatedAt);
      const today = new Date();
      const sameDay = t.toDateString() === today.toDateString();
      const stamp = sameDay
        ? `today at ${t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
        : t.toLocaleString();
      return (
        <span style={{ fontFamily: T.sans, fontSize: '12px', color: T.textMuted }}>
          {subjectTicker}{subjectName ? ` · ${subjectName}` : ''}{subjectSector ? ` · ${subjectSector}` : ''} · Updated {stamp} · Cached
        </span>
      );
    }
    return null;
  }, [isUnsupported, isGenerating, cacheHit, generatedAt, status, result, ticker, subjectTicker, subjectName, subjectSector]);

  if (!authFetcher.isLoaded || !authFetcher.isSignedIn) {
    return <AuthRequired isLoaded={authFetcher.isLoaded} />;
  }

  return (
    <main style={{ background: T.bg, minHeight: '100vh' }}>
      <div style={PAGE_SHELL}>

        {/* 1. Analysis Controls */}
        <AnalysisControls ticker={ticker} setTicker={setTicker} statusLine={statusLine} />
        {modeBadge ? (
          <div style={{
            alignSelf: 'flex-start',
            marginTop: '-22px',
            padding: '5px 10px',
            borderRadius: '999px',
            border: `1px solid ${T.borderSub}`,
            background: T.surfaceMuted,
            color: T.textMuted,
            fontFamily: T.sans,
            fontSize: '11px',
            fontWeight: 650,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
          }}>
            {modeBadge}
          </div>
        ) : null}

        {/* Unsupported ticker — clean coming-soon panel */}
        {isUnsupported ? (
          <Card>
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              justifyContent: 'center', padding: '60px 24px', gap: '8px',
              textAlign: 'center',
            }}>
              <span style={{ fontFamily: T.sans, fontSize: '15px', color: T.text, fontWeight: 600 }}>
                Coming soon
              </span>
              <span style={{ fontFamily: T.sans, fontSize: '13px', color: T.textMuted, maxWidth: '480px', lineHeight: 1.5 }}>
                {safeStr(latest?.message) || 'Ticker-specific Helix reads are currently enabled for S&P 500 and Nasdaq-100 constituents.'}
              </span>
              <button
                onClick={() => setTicker('SPY')}
                style={{
                  marginTop: '8px', background: T.navy, color: '#fff',
                  border: 'none', borderRadius: '8px', padding: '8px 16px',
                  fontFamily: T.sans, fontSize: '12.5px', fontWeight: 600, cursor: 'pointer',
                }}
              >Open SPY read</button>
            </div>
          </Card>
        ) : null}

        {/* Loading skeleton — only when we have nothing to show yet */}
        {!isUnsupported && !result && isGenerating ? (
          <Card title="Generating today's read">
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <span style={{ fontFamily: T.sans, fontSize: '13px', color: T.textSub }}>
                Helix is gathering sources, computing price context, and synthesizing today&apos;s read.
                This usually takes 1–2 minutes on a cold cache.
              </span>
              {[1, 2, 3].map(i => (
                <div key={i} style={{
                  height: '48px',
                  background: T.surfaceMuted,
                  border: `1px solid ${T.borderSub}`,
                  borderRadius: '10px',
                  animation: 'temperPulse 1.6s ease-in-out infinite',
                }} />
              ))}
            </div>
          </Card>
        ) : null}

        {result && !isUnsupported ? (
          <>
            {/* 2. Executive Snapshot + Psychology Curve */}
            <div style={stacked ? { display: 'flex', flexDirection: 'column', gap: '32px' } : SNAPSHOT_GRID}>
              <ExecutiveSnapshot data={result} />
              <MarketPsychologyCurve data={result} />
            </div>

            {/* 3. Two-column: Dominant Themes + Inefficiency Map */}
            <div style={stacked ? { display: 'flex', flexDirection: 'column', gap: '32px' } : MAIN_GRID}>
              <DominantThemes themes={themes} />
              <InefficiencyMap data={result} themes={themes} />
            </div>

            {/* 4. Price Context */}
            <PriceContext data={result} />

            {/* 5. Evidence Board */}
            <EvidenceBoard data={result} />

            {/* 6. Watchpoints */}
            <Watchpoints data={result} themes={themes} />

            {/* 7. Information Set */}
            <InformationSet data={result} />

            {/* 8. Advanced Raw Ledgers */}
            <AdvancedRawLedgers data={result} />
          </>
        ) : null}

        {!isUnsupported && !result && !isGenerating && status !== 'loading' ? (
          <Card>
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              justifyContent: 'center', padding: '60px 24px', gap: '6px',
            }}>
              <span style={{ fontFamily: T.sans, fontSize: '14px', color: T.textSub, fontWeight: 500 }}>
                {isCacheMiss ? 'No cached narrative read available' : isLlmBlocked ? 'Live generation is disabled' : 'No narrative read available'}
              </span>
              <span style={{ fontFamily: T.sans, fontSize: '13px', color: T.textMuted }}>
                {unavailableMessage}
              </span>
            </div>
          </Card>
        ) : null}
      </div>
    </main>
  );
}
