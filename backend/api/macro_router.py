"""Authenticated macro forecast report endpoints."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from api.auth import verify_clerk_token


macro_router = APIRouter(prefix="/api/macro", tags=["macro"])


def _forecast_root() -> Path:
    default_root = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "agent_system"
        / "reports"
        / "macro_forecasts"
    )
    return Path(os.getenv("MACRO_FORECAST_DIR", str(default_root)))


def _latest_forecast_path() -> Path:
    current = _forecast_root() / "current"
    if not current.exists() and not current.is_symlink():
        raise FileNotFoundError(
            f"Macro forecast pointer not found: {current}. "
            "Set MACRO_FORECAST_DIR to the macro_forecasts directory."
        )

    source = current.resolve(strict=True) if current.is_symlink() else current
    if source.is_file():
        return source

    if source.is_dir():
        candidates = sorted(
            source.glob("macro_forecast_*.json"),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"No macro_forecast_*.json files found in {source}")

    raise FileNotFoundError(f"Macro forecast pointer is not a file or directory: {source}")


@macro_router.get("/forecast/latest")
async def latest_macro_forecast(user: dict = Depends(verify_clerk_token)) -> JSONResponse:
    """Return the latest generated macro forecast JSON."""
    del user
    try:
        path = _latest_forecast_path()
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Macro forecast file is not valid JSON: {exc}",
        ) from exc
    return JSONResponse(content=payload)
