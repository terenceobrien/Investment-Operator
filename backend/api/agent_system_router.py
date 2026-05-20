"""
Internal/dev-facing endpoints for inspecting the agent-system execution spine.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from api.auth import verify_clerk_token

agent_system_router = APIRouter(prefix="/api/agent-system", tags=["agent-system"])


def _storage_dir() -> Path:
    return Path(os.getenv("AGENT_SYSTEM_DATA_DIR", str(ROOT_DIR / "data" / "agent_system")))


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read JSONL robustly: skip blanks and malformed lines."""

    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _decision_payloads() -> List[Dict[str, Any]]:
    rows = _read_jsonl(_storage_dir() / "decision_log.jsonl")
    payloads: List[Dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload_json")
        if isinstance(payload, dict):
            payloads.append(payload)
    return sorted(payloads, key=lambda x: str(x.get("timestamp") or ""), reverse=True)


def _schema_rows() -> List[Dict[str, Any]]:
    return _read_jsonl(_storage_dir() / "schema_records.jsonl")


def _trade_idea_records() -> List[Dict[str, Any]]:
    rows = [row for row in _schema_rows() if row.get("schema_type") == "TradeIdea"]
    return sorted(rows, key=lambda x: str(x.get("created_at") or ""), reverse=True)


def _flatten_trade_idea(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
    conviction = payload.get("combined_conviction") or {}
    expression = payload.get("expression") or {}
    primary_instrument = expression.get("primary_instrument") if isinstance(expression, dict) else None
    proposed_sizing = payload.get("proposed_sizing") or {}
    fundamental = payload.get("fundamental") or {}
    thesis = fundamental.get("thesis_statement") if isinstance(fundamental, dict) else None
    rating = conviction.get("rating")
    is_accepted = rating not in {"pass", "weak"} and bool(expression)

    return {
        "id": row.get("id") or payload.get("id"),
        "created_at": payload.get("created_at") or row.get("created_at"),
        "underlying": payload.get("underlying"),
        "conviction_rating": rating,
        "rule_applied": conviction.get("rule_applied"),
        "weakest_link": conviction.get("weakest_link"),
        "is_accepted": is_accepted,
        "rejection_reason": payload.get("rejection_reason"),
        "rejection_stage": payload.get("rejection_stage"),
        "expected_holding_period": payload.get("expected_holding_period"),
        "primary_instrument": primary_instrument.get("ticker") if isinstance(primary_instrument, dict) else None,
        "direction": primary_instrument.get("direction") if isinstance(primary_instrument, dict) else None,
        "base_size_pct": proposed_sizing.get("base_size_pct") if isinstance(proposed_sizing, dict) else None,
        "max_loss_estimate_pct": proposed_sizing.get("max_loss_estimate_pct") if isinstance(proposed_sizing, dict) else None,
        "thesis": thesis,
        "invalidation_thesis": payload.get("invalidation_thesis"),
        "falsifiers_count": len(payload.get("trade_falsifiers") or []),
    }


def _latest_cycle_summary() -> Dict[str, Any]:
    decisions = _decision_payloads()
    if not decisions:
        return {
            "has_data": False,
            "message": "No agent-system research cycles found yet.",
            "storage_path": str(_storage_dir()),
            "dev_endpoint_enabled": _dev_endpoint_enabled(),
        }

    latest_cycle_id = decisions[0].get("cycle_id")
    latest_cycle = [d for d in decisions if d.get("cycle_id") == latest_cycle_id]
    accepted = [d for d in latest_cycle if d.get("decision") == "accepted"]
    rejected = [d for d in latest_cycle if d.get("decision") == "rejected"]
    timestamps = [str(d.get("timestamp")) for d in latest_cycle if d.get("timestamp")]

    return {
        "has_data": True,
        "latest_cycle_id": latest_cycle_id,
        "last_run_at": max(timestamps) if timestamps else None,
        "accepted": len(accepted),
        "rejected": len(rejected),
        "candidates_considered": len(latest_cycle),
        "accepted_underlyings": [str(d.get("candidate")) for d in accepted if d.get("candidate")],
        "rejected_underlyings": [str(d.get("candidate")) for d in rejected if d.get("candidate")],
        "storage_path": str(_storage_dir()),
        "dev_endpoint_enabled": _dev_endpoint_enabled(),
    }


def _dev_endpoint_enabled() -> bool:
    return os.getenv("ENABLE_AGENT_SYSTEM_DEV_ENDPOINTS", "").lower() == "true"


@agent_system_router.get("/summary")
async def get_agent_system_summary(user: dict = Depends(verify_clerk_token)):
    try:
        return _latest_cycle_summary()
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to read agent-system summary")


@agent_system_router.get("/decisions")
async def get_agent_system_decisions(user: dict = Depends(verify_clerk_token)):
    try:
        return _decision_payloads()
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to read agent-system decision log")


@agent_system_router.get("/trade-ideas")
async def get_agent_system_trade_ideas(user: dict = Depends(verify_clerk_token)):
    try:
        return [_flatten_trade_idea(row) for row in _trade_idea_records()]
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to read agent-system trade ideas")


@agent_system_router.get("/trade-ideas/{trade_idea_id}")
async def get_agent_system_trade_idea(
    trade_idea_id: str,
    user: dict = Depends(verify_clerk_token),
):
    try:
        for row in _trade_idea_records():
            payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
            record_id = row.get("id") or payload.get("id")
            if record_id != trade_idea_id:
                continue
            decisions = _decision_payloads()
            matching_decision = next(
                (d for d in decisions if d.get("trade_idea_id") == trade_idea_id),
                None,
            )
            return {
                "trade_idea": payload,
                "decision_log_entry": matching_decision,
            }
        raise HTTPException(status_code=404, detail="Trade idea not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to read agent-system trade idea")


@agent_system_router.post("/run-stub-cycle")
async def post_agent_system_run_stub_cycle(user: dict = Depends(verify_clerk_token)):
    if not _dev_endpoint_enabled():
        raise HTTPException(
            status_code=403,
            detail="Agent-system dev endpoints are disabled. Set ENABLE_AGENT_SYSTEM_DEV_ENDPOINTS=true to enable.",
        )
    try:
        from agent_system.orchestration.run_research_cycle import run_stub_research_cycle

        summary = run_stub_research_cycle()
        summary["ran_at"] = datetime.now(timezone.utc).isoformat()
        return summary
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to run stub research cycle")
