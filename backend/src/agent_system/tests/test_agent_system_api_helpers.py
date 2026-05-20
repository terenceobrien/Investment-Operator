from __future__ import annotations

import json
import asyncio

import pytest
from fastapi import HTTPException

from api.agent_system_router import (
    _flatten_trade_idea,
    _latest_cycle_summary,
    _read_jsonl,
    verify_agent_system_access,
)


def test_jsonl_reader_missing_file_returns_empty(tmp_path):
    assert _read_jsonl(tmp_path / "missing.jsonl") == []


def test_jsonl_reader_skips_malformed_lines(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"ok": true}\nnot-json\n\n{"also_ok": 1}\n', encoding="utf-8")

    assert _read_jsonl(path) == [{"ok": True}, {"also_ok": 1}]


def test_flatten_trade_idea_handles_accepted_and_rejected_payloads():
    accepted = {
        "id": "record-1",
        "created_at": "2026-05-19T00:00:00Z",
        "schema_type": "TradeIdea",
        "payload_json": {
            "id": "record-1",
            "created_at": "2026-05-19T00:00:00Z",
            "underlying": "ETN",
            "combined_conviction": {
                "rating": "strong",
                "rule_applied": "strong_multi_layer_alignment",
                "weakest_link": "none",
            },
            "fundamental": {"thesis_statement": "ETN thesis"},
            "expression": {
                "primary_instrument": {"ticker": "ETN", "direction": "long"}
            },
            "proposed_sizing": {
                "base_size_pct": 0.04,
                "max_loss_estimate_pct": 0.018,
            },
            "expected_holding_period": "6 to 12 months",
            "invalidation_thesis": "Invalidation thesis",
            "trade_falsifiers": [{}, {}, {}],
        },
    }
    rejected = {
        "id": "record-2",
        "created_at": "2026-05-19T00:00:00Z",
        "schema_type": "TradeIdea",
        "payload_json": {
            "id": "record-2",
            "underlying": "SMH",
            "combined_conviction": {
                "rating": "pass",
                "rule_applied": "no_variant_view_pass",
                "weakest_link": "thematic",
            },
            "expression": None,
            "proposed_sizing": None,
            "rejection_reason": "No variant view.",
            "rejection_stage": "thematic",
            "trade_falsifiers": [],
        },
    }

    accepted_item = _flatten_trade_idea(accepted)
    rejected_item = _flatten_trade_idea(rejected)

    assert accepted_item["is_accepted"] is True
    assert accepted_item["primary_instrument"] == "ETN"
    assert accepted_item["falsifiers_count"] == 3
    assert rejected_item["is_accepted"] is False
    assert rejected_item["primary_instrument"] is None
    assert rejected_item["rejection_stage"] == "thematic"


def test_latest_cycle_summary_uses_latest_decision_log_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    rows = [
        {
            "payload_json": {
                "timestamp": "2026-05-18T00:00:00Z",
                "cycle_id": "older",
                "candidate": "OLD",
                "decision": "accepted",
            }
        },
        {
            "payload_json": {
                "timestamp": "2026-05-19T00:00:00Z",
                "cycle_id": "latest",
                "candidate": "ETN",
                "decision": "accepted",
            }
        },
        {
            "payload_json": {
                "timestamp": "2026-05-19T00:01:00Z",
                "cycle_id": "latest",
                "candidate": "SMH",
                "decision": "rejected",
            }
        },
    ]
    (tmp_path / "decision_log.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows),
        encoding="utf-8",
    )

    summary = _latest_cycle_summary()

    assert summary["has_data"] is True
    assert summary["latest_cycle_id"] == "latest"
    assert summary["accepted"] == 1
    assert summary["rejected"] == 1
    assert summary["accepted_underlyings"] == ["ETN"]


def test_agent_system_access_bypasses_clerk_only_when_dev_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_AGENT_SYSTEM_DEV_ENDPOINTS", "true")
    user = asyncio.run(verify_agent_system_access(credentials=None))
    assert user["id"] == "local-dev-agent-system"


def test_agent_system_access_blocks_missing_auth_when_dev_disabled(monkeypatch):
    monkeypatch.delenv("ENABLE_AGENT_SYSTEM_DEV_ENDPOINTS", raising=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_agent_system_access(credentials=None))
    assert exc.value.status_code == 403
