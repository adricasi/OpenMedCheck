from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openmedcheck import web
from openmedcheck.config import Config
from openmedcheck.contracts import MAX_BODY_BYTES
from openmedcheck.model_client import FakeModelClient

Payload = Callable[..., dict[str, Any]]
CARD_KEYS = {
    "status",
    "risk_level",
    "headline",
    "rationale",
    "fired_rules",
    "renal_adjustment_required",
    "crcl_ml_min",
    "alternative",
    "source",
    "model_note",
    "request_id",
}


def test_ac_001_1_valid_request_returns_one_rules_card(
    client: TestClient, make_payload: Payload
) -> None:
    response = client.post("/api/check/rules", json=make_payload())

    assert response.status_code == 200
    card = response.json()
    assert set(card) == CARD_KEYS
    assert card["status"] == "NO_ISSUE"
    assert card["risk_level"] == "LOW"
    assert card["headline"] == "No issue found by these checks"
    assert card["fired_rules"] == []
    assert card["alternative"] is None
    assert card["source"] == "rules"


def test_ac_001_1_allergy_match_returns_blocked(client: TestClient, make_payload: Payload) -> None:
    response = client.post("/api/check/rules", json=make_payload(allergies=["ibuprofen"]))

    assert response.status_code == 200
    card = response.json()
    assert card["status"] == "BLOCKED"
    assert card["risk_level"] == "CRITICAL"
    assert [rule["rule_id"] for rule in card["fired_rules"]] == ["ALLERGY_EXACT_MATCH"]
    assert card["fired_rules"][0]["reason"] in card["rationale"]
    assert card["source"] == "rules"


def test_ac_001_4_out_of_range_value_is_rejected_with_field_errors(
    client: TestClient, make_payload: Payload
) -> None:
    response = client.post("/api/check/rules", json=make_payload(age=17, weight_kg=500))

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 422
    assert {error["field"] for error in body["errors"]} >= {"context.age", "context.weight_kg"}


def test_ac_001_4_missing_field_and_unknown_drug_are_rejected(
    client: TestClient, make_payload: Payload
) -> None:
    payload = make_payload()
    del payload["context"]["age"]
    payload["order"]["drug_id"] = "not_a_drug"

    response = client.post("/api/check/rules", json=payload)

    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["errors"]}
    assert fields == {"context.age", "order.drug_id"}


def test_ac_001_4_overlong_note_is_rejected(client: TestClient, make_payload: Payload) -> None:
    response = client.post("/api/check/rules", json=make_payload(ed_note="x" * 2001))

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["context.ed_note"]


def test_ac_001_4_error_body_does_not_echo_patient_data(
    client: TestClient, make_payload: Payload
) -> None:
    response = client.post(
        "/api/check/rules", json=make_payload(age=17, ed_note="SECRET-NOTE-MARKER")
    )

    assert response.status_code == 422
    assert "SECRET-NOTE-MARKER" not in response.text


def test_ac_001_4_malformed_json_is_rejected_with_422(client: TestClient) -> None:
    response = client.post(
        "/api/check/rules", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_non_json_content_type_is_415(client: TestClient, make_payload: Payload) -> None:
    response = client.post(
        "/api/check/rules",
        content=json.dumps(make_payload()),
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.headers["content-type"].startswith("application/problem+json")


def test_oversized_body_is_413(client: TestClient, make_payload: Payload) -> None:
    payload = make_payload(reason_for_consult="y" * 100)
    payload["pad"] = "z" * MAX_BODY_BYTES

    response = client.post("/api/check/rules", json=payload)

    assert response.status_code == 413
    assert response.headers["content-type"].startswith("application/problem+json")


def test_unknown_route_returns_problem_json(client: TestClient) -> None:
    response = client.get("/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 404


def test_nfr_002_unexpected_error_returns_500_problem_and_logs_no_patient_data(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, make_payload: Payload
) -> None:
    def boom(_request: object) -> None:
        raise RuntimeError("SECRET-NOTE-MARKER")

    monkeypatch.setattr(web, "rules_card", boom)
    local = TestClient(
        web.create_app(Config(), FakeModelClient([])),
        base_url="http://127.0.0.1:8000",
        raise_server_exceptions=False,
    )

    with caplog.at_level(logging.DEBUG):
        response = local.post("/api/check/rules", json=make_payload())

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "SECRET-NOTE-MARKER" not in response.text
    assert "SECRET-NOTE-MARKER" not in caplog.text


def test_nfr_002_422_logs_no_patient_data(
    client: TestClient, caplog: pytest.LogCaptureFixture, make_payload: Payload
) -> None:
    with caplog.at_level(logging.DEBUG):
        client.post("/api/check/rules", json=make_payload(age=17, ed_note="SECRET-NOTE-MARKER"))

    assert "SECRET-NOTE-MARKER" not in caplog.text


def test_ac_010_1_banner_is_shown_on_the_page(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Not for clinical use — synthetic patients. Not a medical device." in response.text


def test_page_uses_only_local_assets(client: TestClient) -> None:
    html = client.get("/").text

    assert "http://" not in html
    assert "https://" not in html
    assert "//cdn" not in html
    assert client.get("/static/style.css").status_code == 200


def test_page_and_rules_do_not_use_forbidden_wording(
    client: TestClient, make_payload: Payload
) -> None:
    texts = [client.get("/").text, client.post("/api/check/rules", json=make_payload()).text]

    for text in texts:
        lowered = text.lower()
        assert "approved" not in lowered
        assert "safe to prescribe" not in lowered


def test_nfr_001_trusted_host_rejects_foreign_host_header(make_payload: Payload) -> None:
    foreign = TestClient(
        web.create_app(Config(), FakeModelClient([])), base_url="http://evil.example"
    )

    assert foreign.post("/api/check/rules", json=make_payload()).status_code == 400


def test_ac_001_4_unknown_chronic_medication_is_rejected(
    client: TestClient, make_payload: Payload
) -> None:
    response = client.post(
        "/api/check/rules", json=make_payload(chronic_medications=["not_a_drug"])
    )

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == [
        "context.chronic_medications"
    ]


def test_ac_011_4_explicitly_allowed_nonlocal_host_is_a_trusted_host(
    make_payload: Payload,
) -> None:
    config = Config(host="clinic.internal", allow_nonlocal=True)
    allowed = TestClient(
        web.create_app(config, FakeModelClient([])), base_url="http://clinic.internal"
    )

    assert allowed.post("/api/check/rules", json=make_payload()).status_code == 200


def test_nfr_001_security_headers_on_page_card_and_problem(
    client: TestClient, make_payload: Payload
) -> None:
    page = client.get("/")
    card = client.post("/api/check/rules", json=make_payload())
    problem = client.post("/api/check/rules", json=make_payload(age=17))

    assert (page.status_code, card.status_code, problem.status_code) == (200, 200, 422)
    for response in (page, card, problem):
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert card.headers["cache-control"] == "no-store"
    assert problem.headers["cache-control"] == "no-store"
    assert "cache-control" not in page.headers


def test_ac_001_4_unknown_field_names_are_not_echoed(
    client: TestClient, make_payload: Payload
) -> None:
    payload = make_payload()
    payload["context"]["<img src=x onerror=alert(1)>"] = 1

    response = client.post("/api/check/rules", json=payload)

    assert response.status_code == 422
    assert [error["field"] for error in response.json()["errors"]] == ["context.<unknown field>"]
    assert "onerror" not in response.text


def test_static_assets_are_revalidated_so_an_upgrade_is_never_stale(client: TestClient) -> None:
    response = client.get("/static/style.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["etag"]
