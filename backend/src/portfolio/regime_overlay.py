from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

CURRENT_REGIME: Dict[str, Any] = {
    "id": "supply_shock_inflation",
    "label": "Supply-shock inflation / late-cycle tightening",
    "headline": "Oil-driven inflation pressure is tightening financial conditions while AI earnings leadership remains intact.",
    "summary": (
        "The regime is being pulled in two directions: supply-shock inflation and hawkish "
        "policy repricing pressure broad beta, while a narrow group of high-quality AI "
        "leaders can continue to carry index-level performance."
    ),
    "risk_summary": (
        "This is not a clean risk-on or risk-off regime. It is a fractured late-cycle setup "
        "where energy and AI leadership can work while broad beta and rate-sensitive assets struggle."
    ),
    "inflation": "up",
    "growth": "mixed",
    "liquidity": "tightening",
    "policy": "hawkish_repricing",
    "leadership": "narrow_ai_energy",
    "confidence": 0.78,
    "key_drivers": [
        {
            "name": "Oil supply shock",
            "status": "bearish for broad beta / bullish for energy",
            "explanation": "A prolonged Strait of Hormuz disruption keeps oil elevated, raising input costs and inflation expectations.",
        },
        {
            "name": "Inflation reacceleration",
            "status": "bearish for long duration",
            "explanation": "Higher inflation reduces the likelihood of Fed cuts and increases the probability of restrictive policy.",
        },
        {
            "name": "Fed hike repricing",
            "status": "bearish for rate-sensitive assets",
            "explanation": "Higher policy-rate expectations pressure small caps, long-duration bonds, speculative growth, and weak balance sheets.",
        },
        {
            "name": "AI earnings resilience",
            "status": "bullish for quality AI leaders",
            "explanation": "Strong earnings and capex momentum can keep mega-cap AI leadership intact even as the broader macro backdrop worsens.",
        },
        {
            "name": "Narrow market leadership",
            "status": "mixed",
            "explanation": "Indexes can hold up if AI leaders perform, but weak breadth raises fragility and makes broad beta less attractive.",
        },
    ],
    "portfolio_implications": [
        "Favor energy, commodities, real assets, short-duration cash-like exposure, defense, infrastructure, and high-quality AI leaders.",
        "Be cautious with small caps, long-duration bonds, unprofitable growth, consumer discretionary, and liquidity-sensitive assets.",
        "Hold more optionality than usual because macro uncertainty can create sharp rotations and dislocations.",
    ],
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
    "SPAXX": _meta("Money Market", "Cash", ["short_duration", "cash_like", "money_market"], 0.02, 0.15, 0.00, 0.92, 0.00),
    "FDRXX": _meta("Money Market", "Cash", ["short_duration", "cash_like", "money_market"], 0.02, 0.15, 0.00, 0.92, 0.00),
    "VMFXX": _meta("Money Market", "Cash", ["short_duration", "cash_like", "money_market"], 0.02, 0.15, 0.00, 0.92, 0.00),
    "SWVXX": _meta("Money Market", "Cash", ["short_duration", "cash_like", "money_market"], 0.02, 0.15, 0.00, 0.92, 0.00),
    "TIP": _meta("ETF", "Inflation Bonds", ["inflation_linked_bonds", "real_assets"], 0.55, 0.75, 0.00, 0.74, 0.10),
    "SCHP": _meta("ETF", "Inflation Bonds", ["inflation_linked_bonds", "real_assets"], 0.55, 0.75, 0.00, 0.74, 0.10),
    "PDBC": _meta("ETF", "Commodities", ["commodities", "real_assets", "inflation_beta"], 0.20, 0.85, 0.60, 0.55, 0.55),
    "DBC": _meta("ETF", "Commodities", ["commodities", "real_assets", "inflation_beta"], 0.20, 0.85, 0.60, 0.52, 0.60),
    "IFRA": _meta("ETF", "Infrastructure", ["infrastructure", "grid", "real_assets"], 0.45, 0.55, 0.15, 0.62, 0.55),
    "PAVE": _meta("ETF", "Infrastructure", ["infrastructure", "grid", "cyclical"], 0.50, 0.50, 0.15, 0.62, 0.65),
    "MLPX": _meta("ETF", "Energy Infrastructure", ["energy", "oil_beta", "real_assets", "infrastructure"], 0.35, 0.70, 0.75, 0.62, 0.55),
    "NVDA": _meta("Stock", "Technology", ["quality_ai", "semiconductors", "mega_cap_growth"], 0.65, 0.15, 0.05, 0.86, 0.80),
    "MSFT": _meta("Stock", "Technology", ["quality_ai", "mega_cap_growth", "software"], 0.60, 0.10, 0.00, 0.88, 0.45),
    "AMZN": _meta("Stock", "Consumer Discretionary / Cloud", ["quality_ai", "cloud_ai", "consumer_discretionary", "mega_cap_growth", "rate_sensitive"], 0.62, 0.10, 0.05, 0.80, 0.62),
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
    "MU": _meta("Stock", "Semiconductors", ["quality_ai", "ai_infrastructure", "semiconductors", "cyclical", "high_beta"], 0.68, 0.15, 0.05, 0.70, 0.88),
    "IBIT": _meta("ETF", "Crypto", ["crypto", "bitcoin", "digital_gold", "liquidity_sensitive", "speculative_real_asset"], 0.85, 0.35, 0.05, 0.30, 0.90),
    "BABA": _meta("Stock", "International Internet", ["china", "international", "consumer_discretionary", "platform", "liquidity_sensitive", "geopolitical_risk"], 0.72, 0.10, 0.05, 0.48, 0.82),
    "PYPL": _meta("Stock", "Fintech", ["fintech", "payments", "rate_sensitive", "competitive_pressure", "liquidity_sensitive"], 0.78, 0.10, 0.00, 0.45, 0.78),
    "MRK": _meta("Stock", "Health Care", ["defensive", "healthcare", "quality"], 0.30, 0.15, 0.00, 0.78, 0.20),
    "EWJ": _meta("ETF", "International Developed", ["international", "japan", "currency_sensitive", "cyclical"], 0.45, 0.25, 0.10, 0.58, 0.62),
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
            "liquidity_sensitive",
            "high_beta",
            "crypto",
        ],
        "best_positioned": [
            "Energy / oil beta",
            "Commodities / real assets",
            "Short-duration cash-like instruments",
            "Quality AI leaders",
            "Defense / geopolitics",
            "Infrastructure / grid",
        ],
        "most_vulnerable": [
            "Small caps",
            "Long-duration bonds",
            "Unprofitable growth",
            "Weak balance sheets",
            "Consumer discretionary exposed to energy costs",
            "Liquidity-sensitive speculative assets",
        ],
        "suggested_buckets": [
            {
                "name": "Energy / oil beta",
                "bucket": "Energy / oil beta",
                "target_min": 0.10,
                "target_max": 0.20,
                "target_range": "10–20%",
                "examples": ["XLE", "XOP", "OIH", "XOM", "CVX", "SLB"],
                "theme_tags": ["energy", "oil_beta"],
                "why_it_fits": "Direct beneficiary if supply risk keeps oil firm and inflation pressure elevated.",
                "type": "Equity / ETF",
            },
            {
                "name": "Commodities / real assets",
                "bucket": "Commodities / real assets",
                "target_min": 0.05,
                "target_max": 0.15,
                "target_range": "5–15%",
                "examples": ["PDBC", "DBC", "GLD", "USO"],
                "theme_tags": ["commodities"],
                "why_it_fits": "Real-asset exposure can hedge inflation and commodity supply shocks.",
                "type": "ETF",
            },
            {
                "name": "AI quality growth",
                "bucket": "AI quality growth",
                "target_min": 0.15,
                "target_max": 0.30,
                "target_range": "15–30%",
                "examples": ["QQQ", "SMH", "SOXX", "NVDA", "MSFT", "AVGO"],
                "theme_tags": ["quality_ai"],
                "why_it_fits": "Keeps exposure to the narrow leadership cohort with earnings support.",
                "type": "Equity / ETF",
            },
            {
                "name": "Defense / geopolitics",
                "bucket": "Defense / geopolitics",
                "target_min": 0.03,
                "target_max": 0.10,
                "target_range": "3–10%",
                "examples": ["LMT", "RTX", "NOC"],
                "theme_tags": ["defense"],
                "why_it_fits": "Geopolitical risk and fiscal defense spend can support relative performance.",
                "type": "Equity",
            },
            {
                "name": "Infrastructure / grid",
                "bucket": "Infrastructure / grid",
                "target_min": 0.05,
                "target_max": 0.15,
                "target_range": "5–15%",
                "examples": ["IFRA", "PAVE", "ETN", "VST"],
                "theme_tags": ["infrastructure", "grid"],
                "why_it_fits": "Power demand, grid investment, and reshoring themes remain regime-relevant.",
                "type": "Equity / ETF",
            },
            {
                "name": "Short duration / cash",
                "bucket": "Short duration / cash",
                "target_min": 0.10,
                "target_max": 0.25,
                "target_range": "10–25%",
                "examples": ["SGOV", "BIL"],
                "theme_tags": ["short_duration", "cash_like"],
                "why_it_fits": "High front-end yields with low duration risk while policy reprices hawkishly.",
                "type": "Treasury ETF",
            },
            {
                "name": "Inflation-linked bonds",
                "bucket": "Inflation-linked bonds",
                "target_min": 0.03,
                "target_max": 0.10,
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


def _clean_ticker(value: str) -> str:
    return str(value or "").upper().strip().replace("*", "")


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
        "money_market": ["spaxx", "fdrxx", "vmfxx", "swvxx", "money market"],
        "defense": ["defense", "aerospace"],
        "infrastructure": ["infrastructure"],
        "grid": ["grid", "power", "electricity"],
        "small_caps": ["small cap", "small-cap"],
        "long_duration": ["long duration", "duration", "bond"],
        "consumer_discretionary": ["consumer discretionary"],
        "rate_sensitive": ["rate sensitive", "growth", "duration"],
        "inflation_linked_bonds": ["tips", "inflation linked", "inflation-linked"],
        "liquidity_sensitive": ["bitcoin", "crypto", "china internet", "fintech", "speculative"],
        "crypto": ["bitcoin", "crypto", "ibit"],
        "ai_infrastructure": ["memory", "semiconductor", "ai infrastructure"],
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
    if "liquidity_sensitive" in tag_set or "crypto" in tag_set:
        score -= 12
        reasons.append("liquidity-sensitive exposure can struggle as financial conditions tighten")

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


def _macro_read_through(ticker: str, tags: List[str], base_reason: str) -> str:
    tag_set = set(tags)
    if "cash_like" in tag_set or "short_duration" in tag_set:
        return "Cash-like exposure benefits from high front-end yields and lowers duration risk."
    if "small_caps" in tag_set:
        return "Small caps are vulnerable because higher rates and tighter liquidity pressure financing conditions."
    if "long_duration" in tag_set:
        return "Long-duration bonds are vulnerable if inflation risk delays cuts or revives hike pricing."
    if ticker == "MU":
        return "MU benefits from AI memory demand but remains cyclical and high beta."
    if ticker == "IBIT" or "crypto" in tag_set:
        return "IBIT may behave more like a liquidity-sensitive risk asset than a defensive inflation hedge."
    if "energy" in tag_set or "oil_beta" in tag_set:
        return "Energy/oil beta is directly aligned with a supply-shock inflation regime."
    if "commodities" in tag_set or "gold" in tag_set:
        return "Commodity and gold exposure can hedge inflation and geopolitical supply risk."
    if "quality_ai" in tag_set and ("cyclical" in tag_set or "high_beta" in tag_set):
        return "AI exposure helps, but cyclicality and beta make sizing more important in tight liquidity."
    if "quality_ai" in tag_set:
        return "Quality AI leadership can keep working while broader market breadth is fragile."
    if "defense" in tag_set:
        return "Defense exposure can benefit from geopolitics and is less tied to consumer demand."
    if "infrastructure" in tag_set or "grid" in tag_set:
        return "Infrastructure and grid exposure connect to power demand, reshoring, and real-asset investment."
    if "consumer_discretionary" in tag_set:
        return "Consumer discretionary exposure is vulnerable if energy costs and rates pressure consumers."
    if "liquidity_sensitive" in tag_set:
        return "Liquidity-sensitive exposure can re-rate lower when policy expectations turn hawkish."
    return base_reason


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
    return "in_range"


def _target_gap(weight: float, target: Tuple[float, float]) -> Dict[str, float]:
    low, high = target
    return {
        "gap_to_min": round(max(low - weight, 0.0), 6),
        "gap_to_max": round(max(weight - high, 0.0), 6),
    }


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
    d["ticker"] = d["ticker"].astype(str).map(_clean_ticker)
    d["theme"] = d["theme"].fillna("").astype(str)
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)

    for _, pos in d.iterrows():
        ticker = _clean_ticker(str(pos["ticker"]))
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
            "reason": _macro_read_through(ticker, tags, reason),
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
        gap = _target_gap(weight, bucket["target"])
        target_min, target_max = bucket["target"]
        exposure_map.append({
            "name": bucket["name"],
            "current_weight": round(weight, 6),
            "target_min": target_min,
            "target_max": target_max,
            "target_range": f"{target_min:.0%}–{target_max:.0%}",
            **gap,
            "status": _status_for_weight(weight, bucket["target"]),
        })

    playbook = REGIME_PLAYBOOKS[active_regime["id"]]
    suggested = []
    for bucket in playbook["suggested_buckets"]:
        current_weight = _bucket_weight(rows, bucket.get("theme_tags", []), bucket.get("examples", []))
        target = (float(bucket["target_min"]), float(bucket["target_max"]))
        gap = _target_gap(current_weight, target)
        suggested.append({
            **bucket,
            "current_weight": round(current_weight, 6),
            **gap,
            "status": _status_for_weight(current_weight, target),
        })

    favored_names = {b["name"] for b in playbook["suggested_buckets"]}
    under_gaps = [
        x for x in exposure_map
        if x["name"] in favored_names and x["gap_to_min"] > 0
    ]
    over_gaps = [
        x for x in exposure_map
        if x["name"] not in favored_names and x["gap_to_max"] > 0
    ]
    combined_gaps = sorted(
        [*under_gaps, *over_gaps],
        key=lambda x: max(float(x.get("gap_to_min", 0)), float(x.get("gap_to_max", 0))),
        reverse=True,
    )
    energy = next((x for x in suggested if x["name"] == "Energy / oil beta"), None)
    commodities = next((x for x in suggested if x["name"] == "Commodities / real assets"), None)
    cash = next((x for x in suggested if x["name"] == "Short duration / cash"), None)
    ai = next((x for x in suggested if x["name"] == "AI quality growth"), None)
    defense = next((x for x in suggested if x["name"] == "Defense / geopolitics"), None)

    if energy and energy["gap_to_min"] > 0.04:
        main_mismatch = "Portfolio is underweight energy/oil beta relative to this supply-shock regime."
    elif commodities and commodities["gap_to_min"] > 0.03:
        main_mismatch = "Portfolio has useful cash or AI exposure but is light on commodity and inflation hedges."
    elif cash and cash["status"] == "in_range" and defense and defense["gap_to_min"] > 0:
        main_mismatch = "Portfolio has cash optionality, but limited defense and geopolitics exposure."
    elif combined_gaps:
        gap = combined_gaps[0]
        if gap["gap_to_min"] > 0:
            main_mismatch = f"Portfolio is underweight {gap['name']} relative to this regime."
        else:
            main_mismatch = f"Portfolio is overweight {gap['name']} relative to this regime."
    elif unknown_weight > 0:
        main_mismatch = "Some portfolio weight is unknown because ticker metadata is not available yet."
    else:
        main_mismatch = "No major regime mismatch detected in the MVP overlay."

    diagnosis_bullets: List[str] = []
    if cash and cash["status"] in {"in_range", "overweight"}:
        diagnosis_bullets.append("Cash-like exposure helps in a hawkish repricing environment.")
    if (energy and energy["status"] == "underweight") or (commodities and commodities["status"] == "underweight"):
        diagnosis_bullets.append("Energy and commodity exposure are below the target range for a supply-shock inflation regime.")
    if ai and ai["current_weight"] >= 0.10:
        mu_weight = next((r["weight"] for r in rows if r["ticker"] == "MU"), 0.0)
        if mu_weight > 0:
            diagnosis_bullets.append("AI exposure is meaningful, but the portfolio has high-beta semiconductor cyclicality through MU.")
        else:
            diagnosis_bullets.append("AI exposure is meaningful and aligned with the narrow leadership regime.")
    small_caps = next((x for x in exposure_map if x["name"] == "Small caps"), None)
    if small_caps and small_caps["current_weight"] > 0:
        diagnosis_bullets.append("Small-cap exposure is not necessarily huge, but it is still a poor fit if rates rise and liquidity tightens.")
    if unknown_weight > 0:
        diagnosis_bullets.append("Some tickers are unclassified, so the overlay may understate hidden macro exposures.")
    if not diagnosis_bullets:
        diagnosis_bullets.append("The portfolio has no single dominant mismatch, but the regime still favors more inflation hedges and optionality.")

    if ai and ai["current_weight"] >= 0.10 and ((energy and energy["status"] == "underweight") or (commodities and commodities["status"] == "underweight")):
        diagnosis_headline = "Portfolio has useful AI exposure but is light on inflation shock beneficiaries."
    elif cash and cash["status"] in {"in_range", "overweight"} and defense and defense["status"] == "underweight":
        diagnosis_headline = "Portfolio has cash optionality, but lacks some geopolitical and real-asset ballast."
    elif energy and energy["status"] == "underweight":
        diagnosis_headline = "Portfolio is underweight the main direct beneficiary of the current oil/inflation shock."
    else:
        diagnosis_headline = "Portfolio has partial regime alignment, with positioning gaps to monitor."

    return {
        "regime": active_regime,
        "context_panel": {
            "title": "Why this regime matters",
            "regime_headline": active_regime.get("headline"),
            "regime_summary": active_regime.get("summary"),
            "risk_summary": active_regime.get("risk_summary"),
            "key_drivers": active_regime.get("key_drivers", []),
            "portfolio_implications": active_regime.get("portfolio_implications", []),
            "best_positioned": playbook.get("best_positioned", []),
            "most_vulnerable": playbook.get("most_vulnerable", []),
        },
        "diagnosis_summary": {
            "headline": diagnosis_headline,
            "bullets": diagnosis_bullets[:5],
        },
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
