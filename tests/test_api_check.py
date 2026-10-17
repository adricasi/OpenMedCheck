"""POST /api/check and GET /api/model/health with a fake model (T-005, REQ-005, AC-011.2)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from openmedcheck.config import Config
from openmedcheck.model_client import (
    FakeModelClient,
    ModelHealth,
    ModelUnavailable,
    OllamaClient,
)
from openmedcheck.presets import PRESET_A, PRESET_B, PRESET_C
from openmedcheck.web import create_app
from tests.model_helpers import verdict_json

Payload = Callable[..., dict[str, Any]]
MARKER = "SECRET-NOTE-MARKER"


def client_for(fake: FakeModelClient) -> TestClient:
    return TestClient(create_app(Config(), fake), base_url="http://127.0.0.1:8000")


def body(preset: Any) -> dict[str, Any]:
    return json.loads(preset.request.model_dump_json())


def test_ac_004_1_check_returns_the_final_card_for_preset_a() -> None:
    fake = FakeModelClient([verdict_json()])

    response = client_for(fake).post("/api/check", json=body(PRESET_A))

    assert response.status_code == 200
    card = response.json()
    assert card["status"] == "BLOCKED"
    assert card["source"] == "rules+model"
    assert card["model_note"] is None
    assert card["alternative"]["drug_id"] == "paracetamol"
    assert response.headers["cache-control"] == "no-store"


def test_ac_005_1_check_with_model_down_returns_200_rules_only_card() -> None:
    fake = FakeModelClient([ModelUnavailable()] * 3)
    api = client_for(fake)

    cards = [api.post("/api/check", json=body(p)) for p in (PRESET_A, PRESET_B, PRESET_C)]

    assert [r.status_code for r in cards] == [200, 200, 200]
    assert [r.json()["status"] for r in cards] == ["NO_ISSUE", "WARNING", "NO_ISSUE"]
    assert all(r.json()["source"] == "rules" for r in cards)
    assert all(r.json()["model_note"] == "Model check unavailable — rules only" for r in cards)


def test_ac_001_4_check_422_is_problem_json_and_does_not_call_the_model(
    make_payload: Payload,
) -> None:
    fake = FakeModelClient([])
    payload = make_payload(age=5)

    response = client_for(fake).post("/api/check", json=payload)

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert fake.requests == []


def test_check_rejects_non_json_and_oversize_bodies() -> None:
    api = client_for(FakeModelClient([]))

    assert (
        api.post("/api/check", content=b"x", headers={"content-type": "text/plain"}).status_code
        == 415
    )
    big = api.post(
        "/api/check",
        content=b"{" + b" " * 20_000 + b"}",
        headers={"content-type": "application/json"},
    )
    assert big.status_code == 413


def test_nfr_002_check_logs_no_patient_data_for_422_and_invalid_model_output(
    caplog: pytest.LogCaptureFixture, make_payload: Payload
) -> None:
    hostile = {**verdict_json(), "headline": MARKER, "extra": MARKER}
    api = client_for(FakeModelClient([hostile, hostile]))

    with caplog.at_level(logging.DEBUG):
        invalid_model = api.post("/api/check", json=make_payload(ed_note=MARKER))
        rejected = api.post("/api/check", json=make_payload(ed_note=MARKER, age=1))

    assert invalid_model.status_code == 200
    assert invalid_model.json()["source"] == "rules"
    assert rejected.status_code == 422
    assert MARKER not in caplog.text
    check_lines = [r for r in caplog.records if r.name.startswith("openmedcheck")]
    assert len(check_lines) == 1  # the valid request is logged once; the 422 not at all


@pytest.mark.parametrize("state", list(ModelHealth))
def test_ac_011_2_health_reports_the_model_state_and_tag(state: ModelHealth) -> None:
    api = client_for(FakeModelClient([], health_state=state))

    response = api.get("/api/model/health")

    assert response.status_code == 200
    assert response.json() == {"status": state.value, "model": "gemma4:e4b"}
    assert response.headers["cache-control"] == "no-store"


# --- OllamaClient.health over a mock transport ---------------------------------------------


def ollama_health(tags: Any, loaded: Any, model: str = "gemma4:e4b") -> ModelHealth:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = tags if request.url.path == "/api/tags" else loaded
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(200, json=payload)

    client = OllamaClient("http://127.0.0.1:11434", model, transport=httpx.MockTransport(handler))
    return client.health()


def test_ac_011_2_ollama_health_ready_when_pulled_and_loaded() -> None:
    listing = {"models": [{"name": "gemma4:e4b"}]}

    assert ollama_health(listing, listing) is ModelHealth.READY


def test_ac_011_2_ollama_health_warming_when_pulled_but_not_loaded() -> None:
    assert (
        ollama_health({"models": [{"name": "gemma4:e4b"}]}, {"models": []}) is ModelHealth.WARMING
    )


def test_ac_011_2_ollama_health_unavailable_when_model_missing_or_server_down() -> None:
    other = {"models": [{"name": "llama3:8b"}]}

    assert ollama_health(other, other) is ModelHealth.UNAVAILABLE
    assert ollama_health(httpx.ConnectError("down"), {}) is ModelHealth.UNAVAILABLE
    assert ollama_health({"unexpected": 1}, {}) is ModelHealth.UNAVAILABLE
