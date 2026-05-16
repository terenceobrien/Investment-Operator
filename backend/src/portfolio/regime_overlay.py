from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

CURRENT_REGIME: Dict[str, Any] = {
    "id": "supply_shock_inflation",
    "label": "Supply-shock inflation / late-cycle tightening",
    "inflation": "up",
    "growth": "mixed",
    "liquidity": "tightening",
    "policy": "hawkish_repricing",
    "leadership": "narrow_ai_energy",
    "confidence": 0.78,
}

FALSIFIERS = [
    "Oil falls sharply despite Hormuz risk",
    "Inflation breakevens stop rising",
    "Fed hike odds fade",
    "Credit spreads remain contained",
    "Market breadth improves meaningfully",
    "Small caps begin outperforming",
    "AI earnings revisions weaken",
    "Strait of Hormuz reopening probability rises",
]


def _meta(
    asset_type: str,
    sector: str,
    tags: List[str],
    rate: float,
    inflation: float,
    oil: float,
    quality: float,
    cyclicality: float,
) -> Dict[str, Any]:
    return {
        "asset_type": asset_type,
        "sector": sector,
        "theme_tags": tags,
        "rate_sensitivity": rate,
        "inflation_beta": inflation,
        "oil_beta": oil,
        "quality_score": quality,
        "cyclicality_score": cyclicality,
    }


TICKER_METADATA: Dict[str, Dict[str, Any]] = {
    "SPY": _meta("ETF", "Broad Market", ["broad_market", "large_caps", "equity"], 0.45, 0.35, 0.20, 0.65, 0.55),
    "QQQ": _meta("ETF", "Technology", ["quality_ai", "mega_cap_growth", "rate_sensitive"], 0.70, 0.20, 0.10, 0.78, 0.55),
    "IWM": _meta("ETF", "Small Caps", ["small_caps", "cyclical", "weak_balance_sheet"], 0.75, 0.25, 0.20, 0.40, 0.85),
    "TLT": _meta("ETF", "Treasuries", ["long_duration", "rate_sensitive"], 0.95, 0.05, 0.00, 0.72, 0.10),
    "HYG": _meta("ETF", "Credit", ["credit", "cyclical", "rate_sensitive"], 0.55, 0.20, 0.10, 0.45, 0.70),
    "GLD": _meta("ETF", "Commodities", ["commodities", "real_assets", "gold"], 0.25, 0.75, 0.10, 0.65, 0.20),
    "USO": _meta("ETF", "Energy", ["energy", "oil_beta", "commodities", "real_assets"], 0.20, 0.75, 0.95, 0.45, 0.80),
    "XLE": _meta("ETF", "Energy", ["energy", "oil_beta", "real_assets"], 0.30, 0.75, 0.85, 0.68, 0.70),
    "XOP": _meta("ETF", "Energy", ["energy", "oil_beta", "cyclical"], 0.35, 0.75, 0.90, 0.50, 0.85),
    "OIH": _meta("ETF", "Energy", ["energy", "oil_beta", "oil_services", "cyclical"], 0.35, 0.70, 0.90, 0.52, 0.85),
    "XLB": _meta("ETF", "Materials", ["commodities", "real_assets", "cyclical"], 0.45, 0.65, 0.30, 0.58, 0.75),
    "XLI": _meta("ETF", "Industrials", ["infrastructure", "cyclical", "quality"], 0.45, 0.45, 0.25, 0.68, 0.70),
    "XLK": _meta("ETF", "Technology", ["quality_ai", "mega_cap_growth", "rate_sensitive"], 0.70, 0.20, 0.05, 0.78, 0.55),
    "XLV": _meta("ETF", "Health Care", ["defensive_quality", "quality"], 0.35, 0.20, 0.05, 0.72, 0.25),
    "XLU": _meta("ETF", "Utilities", ["defensive", "rate_sensitive"], 0.80, 0.30, 0.05, 0.62, 0.20),
    "XLF": _meta("ETF", "Financials", ["financials", "cyclical"], 0.50, 0.30, 0.05, 0.60, 0.70),
    "XLY": _meta("ETF", "Consumer Discretionary", ["consumer_discretionary", "cyclical", "rate_sensitive"], 0.70, 0.15, 0.05, 0.58, 0.80),
    "SMH": _meta("ETF", "Semiconductors", ["quality_ai", "semiconductors", "rate_sensitive"], 0.72, 0.20, 0.05, 0.76, 0.75),
    "SOXX": _meta("ETF", "Semiconductors", ["quality_ai", "semiconductors", "rate_sensitive"], 0.72, 0.20, 0.05, 0.75, 0.75),
    "SGOV": _meta("ETF", "Cash", ["short_duration", "cash_like"], 0.05, 0.20, 0.00, 0.90, 0.00),
    "BIL": _meta("ETF", "Cash", ["short_duration", "cash_like"], 0.05, 0.20, 0.00, 0.90, 0.00),
    "TIP": _meta("ETF", "Inflation Bonds", ["inflation_linked_bonds", "real_assets"], 0.55, 0.75, 0.00, 0.74, 0.10),
    "SCHP": _meta("ETF", "Inflation Bonds", ["inflation_linked_bonds", "real_assets"], 0.55, 0.75, 0.00, 0.74, 0.10),
    "PDBC": _meta("ETF", "Commodities", ["commodities", "real_assets", "inflation_beta"], 0.20, 0.85, 0.60, 0.55, 0.55),
    "DBC": _meta("ETF", "Commodities", ["commodities", "real_assets", "inflation_beta"], 0.20, 0.85, 0.60, 0.52, 0.60),
    "IFRA": _meta("ETF", "Infrastructure", ["infrastructure", "grid", "real_assets"], 0.45, 0.55, 0.15, 0.62, 0.55),
    "PAVE": _meta("ETF", "Infrastructure", ["infrastructure", "grid", "cyclical"], 0.50, 0.50, 0.15, 0.62, 0.65),
    "MLPX": _meta("ETF", "Energy Infrastructure", ["energy", "oil_beta", "real_assets", "infrastructure"], 0.35, 0.70, 0.75, 0.62, 0.55),
    "NVDA": _meta("Stock", "Technology", ["quality_ai", "semiconductors", "mega_cap_growth"], 0.65, 0.15, 0.05, 0.86, 0.80),
    "MSFT": _meta("Stock", "Technology", ["quality_ai", "mega_cap_growth", "software"], 0.60, 0.10, 0.00, 0.88, 0.45),
    "AMZN": _meta("Stock", "Consumer Discretionary", ["consumer_discretionary", "mega_cap_growth", "rate_sensitive"], 0.68, 0.10, 0.05, 0.74, 0.70),
    "META": _meta("Stock", "Communication Services", ["quality_ai", "mega_cap_growth", "advertising"], 0.62, 0.10, 0.00, 0.80, 0.65),
    "GOOGL": _meta("Stock", "Communication Services", ["quality_ai", "mega_cap_growth", "advertising"], 0.60, 0.10, 0.00, 0.82, 0.55),
    "GOOG": _meta("Stock", "Communication Services", ["quality_ai", "mega_cap_growth", "advertising"], 0.60, 0.10, 0.00, 0.82, 0.55),
    "AVGO": _meta("Stock", "Technology", ["quality_ai", "semiconductors"], 0.58, 0.15, 0.05, 0.84, 0.65),
    "XOM": _meta("Stock", "Energy", ["energy", "oil_beta", "real_assets"], 0.30, 0.75, 0.85, 0.76, 0.65),
    "CVX": _meta("Stock", "Energy", ["energy", "oil_beta", "real_assets"], 0.30, 0.75, 0.82, 0.74, 0.62),
    "SLB": _meta("Stock", "Energy", ["energy", "oil_beta", "oil_services"], 0.35, 0.70, 0.90, 0.62, 0.85),
    "OXY": _meta("Stock", "Energy", ["energy", "oil_beta"], 0.38, 0.75, 0.90, 0.58, 0.82),
    "COP": _meta("Stock", "Energy", ["energy", "oil_beta"], 0.32, 0.75, 0.86, 0.70, 0.68),
    "LMT": _meta("Stock", "Defense", ["defense", "geopolitics", "quality"], 0.35, 0.25, 0.05, 0.76, 0.30),
    "RTX": _meta("Stock", "Defense", ["defense", "geopolitics", "quality"], 0.40, 0.25, 0.05, 0.70, 0.45),
    "NOC": _meta("Stock", "Defense", ["defense", "geopolitics", "quality"], 0.35, 0.25, 0.05, 0.75, 0.30),
    "GE": _meta("Stock", "Industrials", ["infrastructure", "grid", "quality"], 0.45, 0.35, 0.05, 0.72, 0.60),
    "ETN": _meta("Stock", "Industrials", ["infrastructure", "grid", "quality"], 0.45, 0.45, 0.05, 0.78, 0.60),
    "VST": _meta("Stock", "Utilities", ["grid", "power_demand", "quality_ai"], 0.45, 0.55, 0.10, 0.72, 0.65),
}

REGIME_PLAYBOOKS: Dict[str, Dict[str, Any]] = {
    "supply_shock_inflation": {
        "overweight_tags": [
            "energy",
            "oil_beta",
            "commodities",
            "real_assets",
            "quality_ai",
            "short_duration",
            "defense",
            "infrastructure",
            "grid",
        ],
        "underweight_tags": [
            "small_caps",
            "long_duration",
            "unprofitable_growth",
            "weak_balance_sheet",
            "consumer_discretionary",
            "rate_sensitive",
        ],
        "suggested_buckets": [
            {
                "name": "Energy / oil beta",
                "target_range": "10–20%",
                "examples": ["XLE", "XOP", "OIH", "XOM", "CVX", "SLB"],
                "theme_tags": ["energy", "oil_beta"],
                "why_it_fits": "Direct beneficiary if supply risk keeps oil firm and inflation pressure elevated.",
                "type": "Equity / ETF",
            },
            {
                "name": "Commodities / real assets",
                "target_range": "5–15%",
                "examples": ["PDBC", "DBC", "GLD", "USO"],
                "theme_tags": ["commodities"],
                "why_it_fits": "Real-asset exposure can hedge inflation and commodity supply shocks.",
                "type": "ETF",
            },
            {
                "name": "AI quality growth",
                "target_range": "15–30%",
                "examples": ["QQQ", "SMH", "SOXX", "NVDA", "MSFT", "AVGO"],
                "theme_tags": ["quality_ai"],
                "why_it_fits": "Keeps exposure to the narrow leadership cohort with earnings support.",
                "type": "Equity / ETF",
            },
            {
                "name": "Defense / geopolitics",
                "target_range": "3–10%",
                "examples": ["LMT", "RTX", "NOC"],
                "theme_tags": ["defense"],
                "why_it_fits": "Geopolitical risk and fiscal defense spend can support relative performance.",
                "type": "Equity",
            },
            {
                "name": "Infrastructure / grid",
                "target_range": "5–15%",
                "examples": ["IFRA", "PAVE", "ETN", "VST"],
                "theme_tags": ["infrastructure", "grid"],
                "why_it_fits": "Power demand, grid investment, and reshoring themes remain regime-relevant.",
                "type": "Equity / ETF",
            },
            {
                "name": "Short duration / cash",
                "target_range": "10–25%",
                "examples": ["SGOV", "BIL"],
                "theme_tags": ["short_duration", "cash_like"],
                "why_it_fits": "High front-end yields with low duration risk while policy reprices hawkishly.",
                "type": "Treasury ETF",
            },
            {
                "name": "Inflation-linked bonds",
                "target_range": "3–10%",
                "examples": ["TIP", "SCHP"],
                "theme_tags": ["inflation_linked_bonds"],
                "why_it_fits": "Adds explicit inflation compensation without long nominal duration concentration.",
                "type": "Bond ETF",
            },
        ],
    }
}

EXPOSURE_BUCKETS: List[Dict[str, Any]] = [
    {"name": "Energy / oil beta", "tags": ["energy", "oil_beta"], "target": (0.10, 0.20)},
    {"name": "Commodities / real assets", "tags": ["commodities"], "target": (0.05, 0.15)},
    {"name": "AI quality growth", "tags": ["quality_ai"], "target": (0.15, 0.30)},
    {"name": "Defense / geopolitics", "tags": ["defense", "geopolitics"], "target": (0.03, 0.10)},
    {"name": "Infrastructure / grid", "tags": ["infrastructure", "grid"], "target": (0.05, 0.15)},
    {"name": "Short duration / cash", "tags": ["short_duration", "cash_like"], "target": (0.10, 0.25)},
    {"name": "Inflation-linked bonds", "tags": ["inflation_linked_bonds"], "target": (0.03, 0.10)},
    {"name": "Small caps", "tags": ["small_caps"], "target": (0.00, 0.05)},
    {"name": "Long duration", "tags": ["long_duration"], "target": (0.00, 0.05)},
    {"name": "Consumer discretionary", "tags": ["consumer_discretionary"], "target": (0.00, 0.08)},
    {"name": "Rate-sensitive growth", "tags": ["rate_sensitive"], "target": (0.00, 0.25)},
]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _tags_for_position(ticker: str, theme: str, meta: Optional[Dict[str, Any]]) -> List[str]:
    tags = set(meta.get("theme_tags", []) if meta else [])
    text = f"{ticker} {theme}".lower()
    theme_rules = {
        "energy": ["energy", "oil", "o&g"],
        "oil_beta": ["oil"],
        "commodities": ["commodity", "commodities"],
        "real_assets": ["real asset", "gold", "commodity"],
        "quality_ai": ["ai", "artificial intelligence", "semiconductor", "chip"],
        "short_duration": ["cash", "short duration", "t-bill", "treasury bill"],
        "cash_like": ["cash", "sgov", "bil"],
        "defense": ["defense", "aerospace"],
        "infrastructure": ["infrastructure"],
        "grid": ["grid", "power", "electricity"],
        "small_caps": ["small cap", "small-cap"],
        "long_duration": ["long duration", "duration", "bond"],
        "consumer_discretionary": ["consumer discretionary"],
        "rate_sensitive": ["rate sensitive", "growth", "duration"],
        "inflation_linked_bonds": ["tips", "inflation linked", "inflation-linked"],
    }
    for tag, needles in theme_rules.items():
        if any(needle in text for needle in needles):
            tags.add(tag)
    return sorted(tags)


def _score_position(ticker: str, theme: str, regime: Dict[str, Any]) -> Tuple[float, str, List[str], str]:
    meta = TICKER_METADATA.get(ticker)
    if not meta:
        return 50.0, "Hold / Monitor", [], "No regime metadata yet; keep position under review until classified."

    playbook = REGIME_PLAYBOOKS[regime["id"]]
    tags = _tags_for_position(ticker, theme, meta)
    tag_set = set(tags)
    score = 50.0
    reasons: List[str] = []

    if tag_set.intersection(playbook["overweight_tags"]):
        score += 20
        reasons.append("matches regime-favored exposure")
    if float(meta.get("inflation_beta", 0)) > 0.6:
        score += 15
        reasons.append("positive inflation beta")
    if float(meta.get("oil_beta", 0)) > 0.6:
        score += 15
        reasons.append("benefits from oil/supply risk")
    if float(meta.get("quality_score", 0)) > 0.75:
        score += 10
        reasons.append("high quality score")
    if "quality_ai" in tag_set and float(meta.get("quality_score", 0)) > 0.75:
        score += 10
        reasons.append("quality AI leadership")
    if tag_set.intersection({"short_duration", "cash_like"}):
        score += 10
        reasons.append("short-duration/cash-like exposure")

    if tag_set.intersection(playbook["underweight_tags"]):
        score -= 20
        reasons.append("matches regime-underweight exposure")
    if float(meta.get("rate_sensitivity", 0)) > 0.7 and regime.get("policy") == "hawkish_repricing":
        score -= 20
        reasons.append("high rate sensitivity during hawkish repricing")
    if float(meta.get("cyclicality_score", 0)) > 0.7 and regime.get("liquidity") == "tightening":
        score -= 15
        reasons.append("high cyclicality while liquidity is tightening")
    if "long_duration" in tag_set:
        score -= 15
        reasons.append("long-duration exposure is vulnerable in this regime")
    if "small_caps" in tag_set:
        score -= 10
        reasons.append("small-cap exposure is vulnerable to higher rates and tighter liquidity")

    score = round(_clamp(score), 1)
    if score >= 75:
        action = "Keep / Overweight"
    elif score >= 55:
        action = "Hold / Monitor"
    elif score >= 35:
        action = "Neutral / Trim if needed"
    else:
        action = "Reduce / Avoid"

    reason = "; ".join(reasons[:3]) or "No major regime conflict identified."
    return score, action, tags, reason[0].upper() + reason[1:]


def _bucket_weight(rows: Iterable[Dict[str, Any]], tags: List[str], examples: Optional[List[str]] = None) -> float:
    tag_set = set(tags)
    example_set = {str(x).upper() for x in (examples or [])}
    weight = 0.0
    for row in rows:
        if row["ticker"] in example_set or tag_set.intersection(row["tags"]):
            weight += row["weight"]
    return float(weight)


def _status_for_weight(weight: float, target: Tuple[float, float]) -> str:
    low, high = target
    eps = 1e-9
    if weight < low - eps:
        return "underweight"
    if weight > high + eps:
        return "overweight"
    return "neutral"


def analyze_portfolio_for_regime(df: pd.DataFrame, regime: Optional[dict] = None) -> dict:
    """
    Diagnose portfolio alignment against a transparent MVP macro-regime playbook.

    Expects a standardized DataFrame from load_portfolio_csv with ticker,
    weight, and theme columns. We intentionally do not normalize total weights;
    weights are treated exactly as supplied by the loader.
    """
    active_regime = dict(regime or CURRENT_REGIME)
    rows: List[Dict[str, Any]] = []
    diagnostics: List[Dict[str, Any]] = []

    d = df.copy()
    if "theme" not in d.columns:
        d["theme"] = ""
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["theme"] = d["theme"].fillna("").astype(str)
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)

    for _, pos in d.iterrows():
        ticker = str(pos["ticker"]).upper().strip()
        weight = float(pos["weight"])
        theme = str(pos.get("theme") or "")
        meta = TICKER_METADATA.get(ticker)
        score, action, tags, reason = _score_position(ticker, theme, active_regime)
        row = {"ticker": ticker, "weight": weight, "theme": theme, "tags": tags, "known": bool(meta), "score": score}
        rows.append(row)
        diagnostics.append({
            "ticker": ticker,
            "weight": round(weight, 6),
            "regime_score": int(round(score)),
            "action": action,
            "reason": reason,
            "tags": tags,
        })

    known_rows = [r for r in rows if r["known"]]
    aligned_weight = sum(r["weight"] for r in known_rows if r["score"] >= 70)
    misaligned_weight = sum(r["weight"] for r in known_rows if r["score"] < 45)
    unknown_weight = sum(r["weight"] for r in rows if not r["known"])
    cash_like_weight = sum(r["weight"] for r in rows if {"cash_like", "short_duration"}.intersection(r["tags"]))
    total_known_weight = sum(r["weight"] for r in known_rows)
    weighted_score = (
        sum(r["score"] * r["weight"] for r in known_rows) / total_known_weight
        if total_known_weight > 0 else 50.0
    )

    exposure_map: List[Dict[str, Any]] = []
    for bucket in EXPOSURE_BUCKETS:
        weight = _bucket_weight(rows, bucket["tags"])
        exposure_map.append({
            "name": bucket["name"],
            "current_weight": round(weight, 6),
            "status": _status_for_weight(weight, bucket["target"]),
        })

    playbook = REGIME_PLAYBOOKS[active_regime["id"]]
    suggested = []
    for bucket in playbook["suggested_buckets"]:
        current_weight = _bucket_weight(rows, bucket.get("theme_tags", []), bucket.get("examples", []))
        suggested.append({
            **bucket,
            "current_weight": round(current_weight, 6),
            "status": _status_for_weight(
                current_weight,
                next((b["target"] for b in EXPOSURE_BUCKETS if b["name"] == bucket["name"]), (0.0, 1.0)),
            ),
        })

    worst = sorted([x for x in exposure_map if x["status"] == "overweight"], key=lambda x: x["current_weight"], reverse=True)
    under = sorted(
        [x for x in exposure_map if x["status"] == "underweight" and x["name"] in {b["name"] for b in playbook["suggested_buckets"]}],
        key=lambda x: x["current_weight"],
    )
    if worst:
        main_mismatch = f"Portfolio appears overweight {worst[0]['name']} for this regime."
    elif under:
        main_mismatch = f"Portfolio appears underweight {under[0]['name']}, a favored bucket in this regime."
    elif unknown_weight > 0:
        main_mismatch = "Some portfolio weight is unknown because ticker metadata is not available yet."
    else:
        main_mismatch = "No major regime mismatch detected in the MVP overlay."

    return {
        "regime": active_regime,
        "alignment": {
            "score": round(weighted_score, 1),
            "aligned_weight": round(float(aligned_weight), 6),
            "misaligned_weight": round(float(misaligned_weight), 6),
            "unknown_weight": round(float(unknown_weight), 6),
            "cash_like_weight": round(float(cash_like_weight), 6),
            "main_mismatch": main_mismatch,
        },
        "exposure_map": exposure_map,
        "position_diagnostics": diagnostics,
        "suggested_buckets": suggested,
        "falsifiers": FALSIFIERS,
    }
