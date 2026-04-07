from __future__ import annotations
from pydantic import BaseModel
from typing import Optional, Dict, List, Tuple, Any

class MacroSignalOut(BaseModel):
    name: str
    latest: float
    mom: float
    yoy: float
    trend: str
    slope_n: float
    components: Dict[str, float]

class MarketStateOut(BaseModel):
    asof_utc: str
    horizon: str
    score_total: Optional[float]
    environment: Optional[str]
    confidence: Optional[float]
    score_components: Optional[Dict[str, float]]
    cross_asset_returns: Dict[str, float]
    sector_returns: Dict[str, float]
    leadership_top3: List[Tuple[str, float]]
    sectors_green: int
    dispersion: Optional[float]
    spy_last_price: Optional[float]
    spy_vwap: Optional[float]
    spy_above_vwap: Optional[bool]
    spy_above_prev_close: Optional[bool]
    spy_clv: Optional[float]
    spy_range_pct: Optional[float]
    spy_vol_vs_20d_pct: Optional[float]
    volume_confirmation: Optional[float]
    vix_level: Optional[float]
    vix_z_20d: Optional[float]
    vix_change_pct_1d: Optional[float]
    market_session_date: Optional[str]

class DeltaOut(BaseModel):
    score: Dict[str, Any]
    environment: Dict[str, Any]
    leadership: Dict[str, Any]
    components_delta: Dict[str, Optional[float]]
    cross_asset_delta: Dict[str, Optional[float]]
    sector_delta: Dict[str, Optional[float]]
    bullets: List[str]

class PortfolioOut(BaseModel):
    summary: Dict[str, Any]
    top_positions: List[Dict[str, Any]]
    theme_exposure: List[Dict[str, Any]]
    flags: List[str]

class NarrativeOut(BaseModel):
    status: str
    job_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None