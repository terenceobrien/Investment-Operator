"""Authenticated risk-state endpoints."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import verify_clerk_token
from src.risk.hedge_trigger import get_hedge_trigger_state


risk_router = APIRouter(prefix="/api/risk", tags=["risk"])
logger = logging.getLogger(__name__)


@risk_router.get("/hedge-trigger")
async def hedge_trigger_state(
    asof_date: Optional[str] = Query(None),
    user: dict = Depends(verify_clerk_token),
) -> dict:
    """Return the validated breadth/credit/volatility hedge-trigger state."""
    del user
    try:
        return await asyncio.to_thread(get_hedge_trigger_state, asof_date=asof_date)
    except Exception as exc:
        logger.error("Hedge-trigger state failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not build hedge-trigger state.",
        ) from exc

