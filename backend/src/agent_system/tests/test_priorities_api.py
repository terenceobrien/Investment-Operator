from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.agent_system_router import verify_agent_system_access
from api.research_router import priorities_router
from src.agent_system.evals import generate_priorities_from_text as generator
from src.agent_system.schemas.common import DerivedEvidence
from src.agent_system.schemas.regime import EdgeDecayHorizon, ResearchPriority


def _priority(theme: str = "Manual rotation thesis") -> ResearchPriority:
    return ResearchPriority(
        theme=theme,
        rationale="Breadth deterioration is creating a rotation setup beneath headline resilience.",
        edge_hypothesis=(
            "The market is underpricing the persistence of dispersion after "
            "breadth breaks down under narrow mega-cap leadership."
        ),
        sub_questions=[
            "Which defensives are seeing improving revisions?",
            "Which crowded leaders are losing breadth support?",
        ],
        priority_rank=1,
        expected_edge_decay=EdgeDecayHorizon.MONTHS,
        supporting_evidence=[
            DerivedEvidence(
                claim="Breadth deterioration supports this manual priority.",
                supports=True,
                computation="test fixture",
                upstream_claims=["test"],
            )
        ],
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(priorities_router)
    app.dependency_overrides[verify_agent_system_access] = lambda: {"id": "test-user"}
    return TestClient(app)


def test_generate_priority_route_returns_structured_priority(monkeypatch):
    async def fake_convert(text: str):
        assert text == "breadth rotation"
        return _priority()

    monkeypatch.setattr("api.research_router.convert_text_to_priority", fake_convert)

    res = _client().post(
        "/api/priorities/generate",
        json={"thesis_text": "breadth rotation"},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["priority"]["theme"] == "Manual rotation thesis"
    assert payload["raw_llm_output"] is None


def test_generate_priority_route_validation_error_returns_422(monkeypatch):
    async def fake_convert(_text: str):
        raise generator.PriorityGenerationError(
            "bad priority",
            raw_output='{"priority": {}}',
            validation_error="missing theme",
        )

    monkeypatch.setattr("api.research_router.convert_text_to_priority", fake_convert)

    res = _client().post(
        "/api/priorities/generate",
        json={"thesis_text": "bad thesis"},
    )

    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["raw_llm_output"] == '{"priority": {}}'
    assert detail["validation_error"] == "missing theme"


def test_approve_and_list_manual_priorities_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "agent_system"))
    client = _client()
    priority_payload = _priority().model_dump(mode="json")

    approve = client.post(
        "/api/priorities/approve",
        json={
            "priority": priority_payload,
            "source_thesis_text": "Operator sees breadth deterioration under the hood.",
        },
    )
    assert approve.status_code == 200
    assert approve.json() == {"success": True, "manual_priorities_count": 1}

    listed = client.get("/api/priorities/manual")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["manual_priorities_count"] == 1
    priority = payload["priorities"][0]
    assert priority["source"] == "operator_manual"
    assert priority["source_thesis_text"] == "Operator sees breadth deterioration under the hood."
    assert priority["approved_by"] == "test-user"
