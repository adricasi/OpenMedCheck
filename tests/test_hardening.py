"""T-008 hardening: exposure, sockets, markup, wording, concurrency, warm-up (NFR-001/005/008)."""

from __future__ import annotations

import asyncio
import json
import re
import socket
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from openmedcheck import web
from openmedcheck.config import Config
from openmedcheck.contracts import MAX_BODY_BYTES
from openmedcheck.model_client import (
    FakeModelClient,
    ModelHealth,
    ModelRequest,
    ModelResult,
    OllamaClient,
)
from openmedcheck.presets import PRESET_A, PRESET_C
from tests.model_helpers import verdict_json

Payload = Callable[..., dict[str, Any]]
ROOT = Path(__file__).parent.parent
PACKAGE = ROOT / "src" / "openmedcheck"
MARKUP = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
NO_ISSUE_VERDICT = {
    "status": "NO_ISSUE",
    "risk_level": "LOW",
    "conflict_type": None,
    "alternative_drug_id": None,
    "headline": "No issue found by these checks",
}


def preset_body(preset: Any) -> dict[str, Any]:
    return json.loads(preset.request.model_dump_json())  # type: ignore[no-any-return]


def client_for(model: Any, config: Config | None = None) -> TestClient:
    return TestClient(web.create_app(config or Config(), model), base_url="http://127.0.0.1:8000")


# --- exposure: host, body limit, content type, CORS ----------------------------------------


def test_nfr_001_foreign_host_is_problem_json_with_security_headers(make_payload: Payload) -> None:
    foreign = TestClient(
        web.create_app(Config(), FakeModelClient([])), base_url="http://evil.example"
    )

    response = foreign.post("/api/check/rules", json=make_payload())

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 400
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("host", ["127.0.0.1:8000", "localhost:9", "[::1]:8000", "LOCALHOST"])
def test_nfr_001_loopback_hosts_with_port_are_trusted(host: str) -> None:
    api = TestClient(web.create_app(Config(), FakeModelClient([])), base_url="http://127.0.0.1")

    assert api.get("/", headers={"host": host}).status_code == 200


def test_nfr_001_chunked_oversized_body_is_413_and_reading_stops() -> None:
    app = web.create_app(Config(), FakeModelClient([]))
    chunk = b" " * 1024
    received = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal received
        received += 1
        if received > 1000:  # the app must have stopped long before this
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/check/rules",
        "raw_path": b"/api/check/rules",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1:8000"),
            (b"content-type", b"application/json"),
            (b"transfer-encoding", b"chunked"),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 8000),
    }

    asyncio.run(app(scope, receive, send))  # type: ignore[arg-type]

    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 413
    assert received <= MAX_BODY_BYTES // 1024 + 2


def test_nfr_001_body_without_content_length_over_limit_is_413(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(40):
            yield b" " * 1024

    response = client.post(
        "/api/check/rules", content=chunks(), headers={"content-type": "application/json"}
    )

    assert response.status_code == 413


def test_nfr_001_non_json_content_type_is_415(client: TestClient) -> None:
    response = client.post("/api/check", content="x", headers={"content-type": "text/plain"})

    assert response.status_code == 415
    assert response.headers["content-type"].startswith("application/problem+json")


def test_nfr_001_no_cors_headers_even_for_a_cross_origin_request(
    client: TestClient, make_payload: Payload
) -> None:
    response = client.post(
        "/api/check/rules", json=make_payload(), headers={"origin": "http://evil.example"}
    )
    preflight = client.options(
        "/api/check/rules",
        headers={"origin": "http://evil.example", "access-control-request-method": "POST"},
    )

    assert not any(key.lower().startswith("access-control-") for key in response.headers)
    assert not any(key.lower().startswith("access-control-") for key in preflight.headers)
    assert preflight.status_code == 405


def test_nfr_001_uvicorn_access_log_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from openmedcheck import __main__ as entry

    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(entry.uvicorn, "run", lambda _app, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(entry, "configure_logging", lambda: None)
    monkeypatch.setattr(entry, "create_app", lambda _config: object())
    monkeypatch.delenv("OPENMEDCHECK_HOST", raising=False)

    entry.main()

    assert calls[0]["access_log"] is False
    assert calls[0]["host"] == "127.0.0.1"


# --- outbound sockets ----------------------------------------------------------------------


def test_nfr_001_only_the_configured_ollama_address_is_ever_contacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destinations: list[Any] = []
    resolved: list[Any] = []

    def refuse(_sock: socket.socket, address: Any) -> None:
        destinations.append(address)
        raise ConnectionRefusedError

    real_getaddrinfo = socket.getaddrinfo

    def record_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        resolved.append(host)
        return real_getaddrinfo(host, *args, **kwargs)

    def refuse_ex(_sock: socket.socket, address: Any) -> int:
        destinations.append(address)
        return 111

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_ex)
    monkeypatch.setattr(socket, "getaddrinfo", record_getaddrinfo)
    config = Config()
    # verify=False only skips loading CA files (this URL is plain http); sockets stay real.
    model = OllamaClient(
        config.ollama_url,
        config.model,
        deadline_s=2,
        transport=httpx.HTTPTransport(verify=False),
    )

    with TestClient(web.create_app(config, model), base_url="http://127.0.0.1:8000") as api:
        assert api.get("/").status_code == 200
        assert api.get("/api/model/health").json()["status"] == "unavailable"
        assert api.post("/api/model/warmup").status_code == 202
        for preset in (PRESET_A, PRESET_C):
            checked = api.post("/api/check", json=preset_body(preset))
            assert checked.status_code == 200
            assert checked.json()["source"] == "rules"  # model unreachable: fail-safe card

    assert destinations, "the model client should have tried the Ollama address"
    assert {tuple(address) for address in destinations} == {("127.0.0.1", 11434)}
    assert set(resolved) <= {"127.0.0.1", "localhost"}


# --- markup is data, never HTML ------------------------------------------------------------


def test_nfr_001_markup_in_note_and_model_output_is_returned_as_json_text() -> None:
    payload = preset_body(PRESET_A)
    payload["context"]["ed_note"] = f"{payload['context']['ed_note']} {MARKUP}"
    fake = FakeModelClient([verdict_json(headline=MARKUP, rationale=MARKUP)])

    response = client_for(fake).post("/api/check", json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "<html" not in response.text.lower()
    card = response.json()
    # Model markup is either carried as inert JSON text or rejected into the rules-only card.
    assert card["source"] in {"rules", "rules+model"}


def test_nfr_001_static_js_has_no_html_sinks() -> None:
    sinks = re.compile(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|createContextualFragment"
        r"|DOMParser|\.srcdoc|setAttribute\(\s*['\"]on|\beval\s*\(|new\s+Function"
        r"|setTimeout\(\s*['\"]|setInterval\(\s*['\"]|javascript:"
    )
    scripts = list(PACKAGE.glob("static/*.js"))
    assert scripts
    for script in scripts:
        assert not sinks.search(script.read_text()), script.name


# --- wording (AC-010.2) --------------------------------------------------------------------

# Decision: "safety" is allowed in prose, and so is "fail-safe" in developer docs under docs/
# (not checked here). In user-facing files (templates, static JS, README) and in card text the
# system never calls a drug or order safe/safely/safer or approved.
ABSOLUTE_CLAIMS = re.compile(r"\b(?:approved|safe|safely|safer)\b", re.IGNORECASE)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_ac_010_2_no_absolute_safety_claims_in_user_facing_files() -> None:
    files = [
        *PACKAGE.glob("templates/*.html"),
        *PACKAGE.glob("static/*.js"),
        ROOT / "README.md",
    ]
    for path in files:
        assert not ABSOLUTE_CLAIMS.search(path.read_text()), path.name


def test_ac_010_2_cards_never_make_absolute_claims_and_no_issue_text_is_exact() -> None:
    cards = [
        client_for(FakeModelClient([])).post("/api/check/rules", json=preset_body(p)).json()
        for p in (PRESET_A, PRESET_C)
    ]
    cards.append(
        client_for(FakeModelClient([verdict_json()]))
        .post("/api/check", json=preset_body(PRESET_A))
        .json()
    )
    cards.append(
        client_for(FakeModelClient([verdict_json(**NO_ISSUE_VERDICT)]))
        .post("/api/check", json=preset_body(PRESET_C))
        .json()
    )

    for card in cards:
        for text in _strings(card):
            assert not ABSOLUTE_CLAIMS.search(text), text
    no_issue = [card for card in cards if card["status"] == "NO_ISSUE"]
    assert no_issue
    assert all(card["headline"] == "No issue found by these checks" for card in no_issue)


def test_ac_010_2_banner_is_on_every_page(client: TestClient) -> None:
    banner = "Not for clinical use — synthetic patients"
    templates = list(PACKAGE.glob("templates/*.html"))
    assert templates
    for template in templates:
        assert banner in template.read_text(), template.name
    assert banner in client.get("/").text


# --- concurrency ---------------------------------------------------------------------------


class _OverlappingClient:
    """Thread-safe model double; a barrier proves the two checks really ran concurrently."""

    def __init__(self) -> None:
        self._barrier = threading.Barrier(2, timeout=5)

    def assess(self, request: ModelRequest) -> ModelResult:
        self._barrier.wait()
        escalate = request.context.patient_id == PRESET_A.request.context.patient_id
        verdict = verdict_json() if escalate else verdict_json(**NO_ISSUE_VERDICT)
        return FakeModelClient([verdict]).assess(request)

    def health(self) -> ModelHealth:
        return ModelHealth.READY

    def warm_up(self) -> bool:
        return True


def test_nfr_005_two_parallel_checks_return_independent_correct_cards() -> None:
    app = web.create_app(Config(), _OverlappingClient())

    def run(payload: dict[str, Any]) -> dict[str, Any]:
        with TestClient(app, base_url="http://127.0.0.1:8000") as api:
            return api.post("/api/check", json=payload).json()  # type: ignore[no-any-return]

    with ThreadPoolExecutor(max_workers=2) as pool:
        card_a, card_c = pool.map(run, [preset_body(PRESET_A), preset_body(PRESET_C)])

    assert card_a["status"] == "BLOCKED"
    assert card_a["alternative"]["drug_id"] == "paracetamol"
    assert card_c["status"] == "NO_ISSUE"
    assert card_c["alternative"] is None
    assert card_a["request_id"] != card_c["request_id"]


# --- warm-up (REQ-014) ---------------------------------------------------------------------


def test_ac_014_1_warmup_starts_one_load_and_returns_202_warming() -> None:
    fake = FakeModelClient([], health_state=ModelHealth.WARMING)

    response = client_for(fake).post("/api/model/warmup")

    assert response.status_code == 202
    assert response.json() == {"status": "warming"}
    assert fake.warm_up_calls == 1


@pytest.mark.parametrize("state", [ModelHealth.READY, ModelHealth.UNAVAILABLE])
def test_ac_014_1_warmup_when_ready_or_unavailable_loads_nothing(state: ModelHealth) -> None:
    fake = FakeModelClient([], health_state=state)

    response = client_for(fake).post("/api/model/warmup")

    assert (response.status_code, response.json()) == (202, {"status": state.value})
    assert fake.warm_up_calls == 0


def test_ac_014_1_warmup_is_single_flight() -> None:
    guard = web._WarmUp()

    assert guard.try_start() is True
    assert guard.try_start() is False
    guard.run(FakeModelClient([]))
    assert guard.try_start() is True


def test_ac_014_1_warmup_never_raises_even_if_the_load_or_probe_fails() -> None:
    class BrokenLoad(FakeModelClient):
        def warm_up(self) -> bool:
            raise RuntimeError("boom")

    class BrokenProbe(FakeModelClient):
        def health(self) -> ModelHealth:
            raise RuntimeError("boom")

    for fake in (BrokenLoad([], health_state=ModelHealth.WARMING), BrokenProbe([])):
        response = client_for(fake).post("/api/model/warmup")

        assert response.status_code == 202
        assert response.json()["status"] in {"warming", "unavailable"}


def test_ac_014_1_ollama_warm_up_sends_an_empty_prompt_and_reports_success() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"done": True})

    model = OllamaClient(
        "http://127.0.0.1:11434", "gemma4:e4b", transport=httpx.MockTransport(handler)
    )

    assert model.warm_up() is True
    sent = json.loads(seen[0].content)
    assert seen[0].url.path == "/api/generate"
    assert sent["prompt"] == ""
    assert set(sent) == {"model", "prompt", "stream", "keep_alive"}


def test_ac_014_1_ollama_warm_up_failures_return_false() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    failing = OllamaClient("http://127.0.0.1:11434", "m", transport=httpx.MockTransport(down))
    erroring = OllamaClient(
        "http://127.0.0.1:11434",
        "m",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    assert failing.warm_up() is False
    assert erroring.warm_up() is False


class _OfflineOllamaClient(OllamaClient):
    def __init__(self, base_url: str, model: str, **kwargs: Any) -> None:
        super().__init__(
            base_url,
            model,
            transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
            **kwargs,
        )


_offline_ollama_client = _OfflineOllamaClient


# --- shutdown ------------------------------------------------------------------------------


def test_t_005_app_owned_ollama_client_is_closed_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []
    monkeypatch.setattr(OllamaClient, "close", lambda _self: closed.append(True))
    monkeypatch.setattr(web, "OllamaClient", _offline_ollama_client)

    with TestClient(web.create_app(Config()), base_url="http://127.0.0.1:8000") as api:
        assert api.get("/").status_code == 200
        assert closed == []

    assert closed == [True]


def test_t_005_injected_client_is_not_closed_by_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    monkeypatch.setattr(OllamaClient, "close", lambda _self: closed.append(True))
    injected = _offline_ollama_client("http://127.0.0.1:11434", "m")

    with TestClient(web.create_app(Config(), injected), base_url="http://127.0.0.1:8000") as api:
        assert api.get("/").status_code == 200

    assert closed == []
    injected._http.close()
