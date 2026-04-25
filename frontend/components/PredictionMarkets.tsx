"use client";

/**
 * PredictionMarkets.tsx
 * 
 * Drop-in panel for the Helix app. Fetches top finance/economics prediction
 * markets from Polymarket's public Gamma API and displays them in terminal style.
 *
 * Usage:
 *   import PredictionMarkets from "@/components/PredictionMarkets";
 *   <PredictionMarkets />
 *
 * No API key required — Polymarket Gamma API is public.
 * Data refreshes every 60s automatically.
 */

import { useEffect, useState, useCallback } from "react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface PolyMarket {
  id: string;
  question: string;
  slug: string;
  outcomePrices: string;   // JSON array e.g. '["0.72", "0.28"]'
  outcomes: string;        // JSON array e.g. '["Yes", "No"]'
  volume24hr: number;
  liquidity: number;
  endDate: string;
  events: { title: string }[];
  oneDayPriceChange?: number;
}

interface ParsedMarket {
  id: string;
  question: string;
  slug: string;
  eventTitle: string;
  yesProb: number;
  noProb: number;
  volume24hr: number;
  liquidity: number;
  endDate: string;
  dayChange: number | null;
}

// ─── Config ──────────────────────────────────────────────────────────────────

// Polymarket Gamma API — public, no auth required
const GAMMA = "https://gamma-api.polymarket.com";

// Tag IDs for finance/economics categories
// 102000 = Macro Indicators, 370 = GDP, 833 = ETF
const FINANCE_TAG_IDS = [102000, 370, 833];

const REFRESH_INTERVAL_MS = 60_000;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function parseMarket(m: PolyMarket): ParsedMarket | null {
  try {
    const prices: number[] = JSON.parse(m.outcomePrices).map(Number);
    const outcomes: string[] = JSON.parse(m.outcomes);
    const yesIdx = outcomes.findIndex((o) => o.toLowerCase() === "yes");
    const yesProb = yesIdx >= 0 ? prices[yesIdx] : prices[0];
    const noProb = 1 - yesProb;
    return {
      id: m.id,
      question: m.question,
      slug: m.slug,
      eventTitle: m.events?.[0]?.title ?? m.question,
      yesProb: Math.round(yesProb * 100),
      noProb: Math.round(noProb * 100),
      volume24hr: m.volume24hr ?? 0,
      liquidity: m.liquidity ?? 0,
      endDate: m.endDate,
      dayChange: m.oneDayPriceChange != null ? Math.round(m.oneDayPriceChange * 100) : null,
    };
  } catch {
    return null;
  }
}

function fmtMoney(n: number) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}k`;
  return `$${Math.round(n)}`;
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso.slice(0, 10);
  }
}

// ─── Fetcher ─────────────────────────────────────────────────────────────────

async function fetchFinanceMarkets(): Promise<ParsedMarket[]> {
  const all: PolyMarket[] = [];

  await Promise.all(
    FINANCE_TAG_IDS.map(async (tagId) => {
      const res = await fetch(
        `${GAMMA}/markets?active=true&closed=false&limit=12&order=volume24hr&ascending=false&tag_id=${tagId}`,
        { cache: "no-store" }
      );
      if (!res.ok) throw new Error(`Polymarket API error: ${res.status}`);
      const data: PolyMarket[] = await res.json();
      all.push(...data);
    })
  );

  // Deduplicate by id, parse, sort by 24h volume descending
  const seen = new Set<string>();
  return all
    .filter((m) => {
      if (seen.has(m.id)) return false;
      seen.add(m.id);
      return true;
    })
    .map(parseMarket)
    .filter((m): m is ParsedMarket => m !== null)
    .sort((a, b) => b.volume24hr - a.volume24hr)
    .slice(0, 16);
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function ProbBar({ yes, no }: { yes: number; no: number }) {
  return (
    <div style={{ display: "flex", gap: 2, alignItems: "center", width: "100%" }}>
      <div
        style={{
          height: 3,
          borderRadius: 1.5,
          background: "#9580d4",
          width: `${yes}%`,
          transition: "width 0.4s ease",
          flexShrink: 0,
        }}
      />
      <div
        style={{
          height: 3,
          borderRadius: 1.5,
          background: "#3a3a4a",
          width: `${no}%`,
          transition: "width 0.4s ease",
          flexShrink: 0,
        }}
      />
    </div>
  );
}

function MarketRow({ m, idx }: { m: ParsedMarket; idx: number }) {
  const changeColor =
    m.dayChange == null ? "#666" : m.dayChange > 0 ? "#4caf89" : m.dayChange < 0 ? "#e05555" : "#666";

  return (
    <a
      href={`https://polymarket.com/market/${m.slug}`}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: "grid",
        gridTemplateColumns: "20px 1fr 64px 72px 72px 80px",
        gap: "0 16px",
        alignItems: "start",
        padding: "12px 0",
        borderBottom: "1px solid #1e1e2e",
        textDecoration: "none",
        cursor: "pointer",
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "#0e0e14")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {/* Index */}
      <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: "#444", paddingTop: 2 }}>
        {String(idx + 1).padStart(2, "0")}
      </span>

      {/* Question + bar */}
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            color: "#c8c8d8",
            lineHeight: 1.4,
            marginBottom: 5,
            overflow: "hidden",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
          }}
        >
          {m.question}
        </div>
        <ProbBar yes={m.yesProb} no={m.noProb} />
      </div>

      {/* Yes % */}
      <div style={{ textAlign: "right", paddingTop: 1 }}>
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 15,
            fontWeight: 600,
            color: m.yesProb >= 60 ? "#9580d4" : m.yesProb <= 25 ? "#e05555" : "#c8c8d8",
          }}
        >
          {m.yesProb}%
        </span>
        <div style={{ fontSize: 10, color: "#555", marginTop: 2, fontFamily: "JetBrains Mono, monospace" }}>
          YES
        </div>
      </div>

      {/* Day change */}
      <div style={{ textAlign: "right", paddingTop: 1 }}>
        {m.dayChange != null ? (
          <span
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 13,
              color: changeColor,
            }}
          >
            {m.dayChange > 0 ? "+" : ""}
            {m.dayChange}pp
          </span>
        ) : (
          <span style={{ color: "#444", fontSize: 12 }}>—</span>
        )}
        <div style={{ fontSize: 10, color: "#555", marginTop: 2, fontFamily: "JetBrains Mono, monospace" }}>
          1D CHG
        </div>
      </div>

      {/* 24h volume */}
      <div style={{ textAlign: "right", paddingTop: 1 }}>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 13, color: "#888" }}>
          {fmtMoney(m.volume24hr)}
        </span>
        <div style={{ fontSize: 10, color: "#555", marginTop: 2, fontFamily: "JetBrains Mono, monospace" }}>
          VOL 24H
        </div>
      </div>

      {/* Expiry */}
      <div style={{ textAlign: "right", paddingTop: 1 }}>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: "#555" }}>
          {fmtDate(m.endDate)}
        </span>
        <div style={{ fontSize: 10, color: "#3a3a4a", marginTop: 2, fontFamily: "JetBrains Mono, monospace" }}>
          EXPIRY
        </div>
      </div>
    </a>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function PredictionMarkets() {
  const [markets, setMarkets] = useState<ParsedMarket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (showRefreshing = false) => {
    if (showRefreshing) setRefreshing(true);
    try {
      const data = await fetchFinanceMarkets();
      setMarkets(data);
      setLastUpdated(new Date());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch markets");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => load(true), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div
      style={{
        background: "#07070a",
        color: "#c8c8d8",
        fontFamily: "Inter, system-ui, sans-serif",
        minHeight: "100vh",
        padding: "28px 32px",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          marginBottom: 24,
          paddingBottom: 16,
          borderBottom: "1px solid #1e1e2e",
        }}
      >
        <div>
          <div style={{ fontSize: 11, color: "#555", letterSpacing: "0.12em", marginBottom: 4, fontFamily: "JetBrains Mono, monospace" }}>
            PREDICTION MARKETS
          </div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 500, color: "#e8e8f0" }}>
            Finance & Economics
          </h1>
          <div style={{ fontSize: 12, color: "#555", marginTop: 4 }}>
            Top markets by 24h volume · Polymarket
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, paddingBottom: 2 }}>
          {lastUpdated && (
            <span style={{ fontSize: 11, color: "#444", fontFamily: "JetBrains Mono, monospace" }}>
              {refreshing ? "refreshing…" : `updated ${lastUpdated.toLocaleTimeString()}`}
            </span>
          )}
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            style={{
              background: "transparent",
              border: "1px solid #2a2a3a",
              color: "#666",
              fontSize: 11,
              padding: "5px 12px",
              cursor: refreshing ? "default" : "pointer",
              borderRadius: 4,
              fontFamily: "JetBrains Mono, monospace",
              letterSpacing: "0.05em",
              opacity: refreshing ? 0.5 : 1,
            }}
          >
            ↻ REFRESH
          </button>
        </div>
      </div>

      {/* States */}
      {loading && (
        <div style={{ textAlign: "center", padding: "60px 0", color: "#444", fontFamily: "JetBrains Mono, monospace", fontSize: 12 }}>
          fetching markets…
        </div>
      )}

      {error && !loading && (
        <div
          style={{
            background: "#1a0a0a",
            border: "1px solid #3a1a1a",
            borderRadius: 6,
            padding: "16px 20px",
            color: "#e05555",
            fontSize: 13,
            fontFamily: "JetBrains Mono, monospace",
          }}
        >
          ⚠ {error}
        </div>
      )}

      {/* Column headers */}
      {!loading && markets.length > 0 && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "20px 1fr 64px 72px 72px 80px",
              gap: "0 16px",
              padding: "0 0 8px",
              borderBottom: "1px solid #1e1e2e",
              marginBottom: 0,
            }}
          >
            {["#", "MARKET", "YES", "1D CHG", "VOL 24H", "EXPIRY"].map((h, i) => (
              <div
                key={h}
                style={{
                  fontSize: 10,
                  color: "#3a3a4a",
                  fontFamily: "JetBrains Mono, monospace",
                  letterSpacing: "0.1em",
                  textAlign: i >= 2 ? "right" : "left",
                }}
              >
                {h}
              </div>
            ))}
          </div>

          {markets.map((m, i) => (
            <MarketRow key={m.id} m={m} idx={i} />
          ))}

          {/* Footer */}
          <div
            style={{
              marginTop: 20,
              paddingTop: 12,
              borderTop: "1px solid #1e1e2e",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ fontSize: 11, color: "#333", fontFamily: "JetBrains Mono, monospace" }}>
              {markets.length} markets · Macro Indicators + GDP + ETF tags · auto-refresh 60s
            </div>
            <a
              href="https://polymarket.com"
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: 11, color: "#444", textDecoration: "none", fontFamily: "JetBrains Mono, monospace" }}
            >
              polymarket.com ↗
            </a>
          </div>
        </>
      )}
    </div>
  );
}