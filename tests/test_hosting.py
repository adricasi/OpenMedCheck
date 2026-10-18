"""Hosted demo profile (REQ-015): config, trusted hosts, bearer key, /healthz, banner."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from openmedcheck import web
from openmedcheck.config import Config, ConfigError
from openmedcheck.model_client import FakeModelClient, OllamaClient
from tests.model_helpers import make_request

SECRET = "s3cret-token-value"  # noqa: S105 - test fixture, not a real credential
HOSTED_ENV = {
    "OPENMEDCHECK_HOST": "0.0.0.0",  # noqa: S104
    "OPENMEDCHECK_ALLOW_NONLOCAL": "1",
    "OPENMEDCHECK_PUBLIC_HOSTS": "demo.onrender.com, Other.Example.org",
    "OPENMEDCHECK_OLLAMA_URL": "https://gemma.example.org",
    "OPENMEDCHECK_OLLAMA_API_KEY": SECRET,
}


def _client(config: Config, host: str) -> TestClient:
    return TestClient(web.create_app(config, FakeModelClient([])), base_url=f"http://{host}")


# --- config --------------------------------------------------------------------------------


def test_ac_015_1_defaults_are_not_hosted() -> None:
    config = Config.from_env({})

    assert config.public_hosts == ()
    assert config.ollama_api_key == ""
    assert config.hosted is False


def test_ac_015_1_hosted_needs_nonlocal_and_public_host() -> None:
    config = Config.from_env(HOSTED_ENV)

    assert config.hosted is True
    assert config.public_hosts == ("demo.onrender.com", "other.example.org")


def test_ac_015_1_loopback_public_hosts_are_not_hosted() -> None:
    config = Config.from_env(
        {
            "OPENMEDCHECK_HOST": "0.0.0.0",  # noqa: S104
            "OPENMEDCHECK_ALLOW_NONLOCAL": "1",
            "OPENMEDCHECK_PUBLIC_HOSTS": "localhost,127.0.0.1",
        }
    )

    assert config.hosted is False


def test_ac_015_1_public_hosts_require_allow_nonlocal() -> None:
    with pytest.raises(ConfigError, match="ALLOW_NONLOCAL"):
        Config.from_env({"OPENMEDCHECK_PUBLIC_HOSTS": "demo.example.org"})


@pytest.mark.parametrize("raw", ["bad host", "evil.com/path", "a..b", "-x.org", "http://x.org"])
def test_ac_015_2_public_hosts_are_validated(raw: str) -> None:
    with pytest.raises(ConfigError, match="PUBLIC_HOSTS"):
        Config.from_env({"OPENMEDCHECK_ALLOW_NONLOCAL": "1", "OPENMEDCHECK_PUBLIC_HOSTS": raw})


def test_ac_015_2_api_key_requires_https_for_remote_ollama() -> None:
    env = {
        "OPENMEDCHECK_ALLOW_NONLOCAL": "1",
        "OPENMEDCHECK_OLLAMA_URL": "http://gemma.example.org:11434",
        "OPENMEDCHECK_OLLAMA_API_KEY": SECRET,
    }

    with pytest.raises(ConfigError, match="https"):
        Config.from_env(env)


def test_ac_015_2_api_key_allowed_over_http_on_loopback() -> None:
    config = Config.from_env({"OPENMEDCHECK_OLLAMA_API_KEY": SECRET})

    assert config.ollama_api_key == SECRET


def test_ac_015_2_api_key_with_whitespace_is_refused() -> None:
    with pytest.raises(ConfigError, match="API_KEY"):
        Config.from_env({"OPENMEDCHECK_OLLAMA_API_KEY": "two words"})


def test_ac_015_2_api_key_is_not_in_repr_or_error() -> None:
    config = Config.from_env(HOSTED_ENV)
    assert SECRET not in repr(config)
    assert SECRET not in str(config)

    with pytest.raises(ConfigError) as error:
        Config.from_env({**HOSTED_ENV, "OPENMEDCHECK_OLLAMA_URL": "http://gemma.example.org"})
    assert SECRET not in str(error.value)


def test_ac_015_2_platform_port_is_the_fallback() -> None:
    assert Config.from_env({"PORT": "10000"}).port == 10000
    assert Config.from_env({"PORT": "10000", "OPENMEDCHECK_PORT": "9001"}).port == 9001


def test_ac_015_2_invalid_platform_port_is_refused() -> None:
    with pytest.raises(ConfigError, match="PORT"):
        Config.from_env({"PORT": "nope"})


# --- trusted hosts ---------------------------------------------------------------------------


def test_ac_015_2_configured_public_host_is_accepted() -> None:
    config = Config.from_env(HOSTED_ENV)

    assert _client(config, "demo.onrender.com").get("/").status_code == 200
    assert _client(config, "other.example.org:443").get("/").status_code == 200


def test_ac_015_2_other_hosts_are_still_rejected() -> None:
    config = Config.from_env(HOSTED_ENV)

    assert _client(config, "evil.example").get("/").status_code == 400
    assert _client(config, "demo.onrender.com.evil.example").get("/").status_code == 400


def test_ac_015_1_public_host_is_ignored_without_allow_nonlocal() -> None:
    config = Config(public_hosts=("demo.example.org",))

    assert _client(config, "demo.example.org").get("/").status_code == 400


# --- bearer key ------------------------------------------------------------------------------


def _recording_client(api_key: str) -> tuple[OllamaClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"content": "{}"}})
        return httpx.Response(200, json={"models": [{"name": "gemma4:e4b"}]})

    client = OllamaClient(
        "https://gemma.example.org",
        "gemma4:e4b",
        transport=httpx.MockTransport(handler),
        api_key=api_key,
    )
    return client, seen


def test_ac_015_2_bearer_header_is_sent_on_every_request() -> None:
    client, seen = _recording_client(SECRET)

    client.health()
    client.warm_up()
    client._chat(make_request(), 5.0)

    assert {r.url.path for r in seen} >= {"/api/tags", "/api/ps", "/api/generate", "/api/chat"}
    assert all(r.headers["authorization"] == f"Bearer {SECRET}" for r in seen)


def test_ac_015_1_no_authorization_header_without_a_key() -> None:
    client, seen = _recording_client("")

    client.health()
    client.warm_up()
    client._chat(make_request(), 5.0)

    assert seen
    assert all("authorization" not in r.headers for r in seen)


# --- healthz and banner ----------------------------------------------------------------------


def test_ac_015_2_healthz_is_ok_without_touching_the_model() -> None:
    fake = FakeModelClient([])
    api = TestClient(web.create_app(Config(), fake), base_url="http://127.0.0.1")

    response = api.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert fake.warm_up_calls == 0


def test_ac_015_2_healthz_ignores_the_host_header_but_pages_do_not() -> None:
    api = _client(Config(), "10.0.0.5")

    assert api.get("/healthz").status_code == 200
    assert api.get("/").status_code == 400


def test_ac_015_3_hosted_banner_only_in_hosted_mode() -> None:
    hosted = _client(Config.from_env(HOSTED_ENV), "demo.onrender.com").get("/").text
    local = _client(Config(), "127.0.0.1").get("/").text

    assert 'class="hosted-banner"' in hosted
    assert "synthetic data only" in hosted.lower()
    assert "on-premises" in hosted
    assert "hosted-banner" not in local


def test_ac_015_2_hosted_profile_refuses_a_remote_model_without_https_and_key() -> None:
    from openmedcheck.config import Config, ConfigError

    base = {
        "OPENMEDCHECK_ALLOW_NONLOCAL": "1",
        "OPENMEDCHECK_HOST": "0.0.0.0",  # noqa: S104 - the platform bind, exercised in config only
        "OPENMEDCHECK_PUBLIC_HOSTS": "openmedcheck-demo.onrender.com",
    }
    for url, key in (
        ("http://203.0.113.7:11434", ""),
        ("https://gemma.example.org", ""),
    ):
        env = {**base, "OPENMEDCHECK_OLLAMA_URL": url, "OPENMEDCHECK_OLLAMA_API_KEY": key}
        with pytest.raises(ConfigError):
            Config.from_env(env)
    ok = {
        **base,
        "OPENMEDCHECK_OLLAMA_URL": "https://gemma.example.org",
        "OPENMEDCHECK_OLLAMA_API_KEY": "a" * 64,
    }
    assert Config.from_env(ok).hosted


def test_ac_015_2_model_calls_over_the_cap_get_the_rules_only_card_at_once() -> None:
    import threading

    from openmedcheck.check_service import MODEL_UNAVAILABLE_NOTE, final_card
    from openmedcheck.contracts import Source
    from openmedcheck.model_client import BoundedModelClient, ModelOutcome
    from openmedcheck.presets import PRESET_A

    release = threading.Event()
    entered = threading.Event()

    class SlowClient:
        def assess(self, _request):  # type: ignore[no-untyped-def]
            entered.set()
            release.wait(5)
            from openmedcheck.model_client import ModelResult

            return ModelResult(
                outcome=ModelOutcome.UNAVAILABLE, verdict=None, attempts=1, latency_ms=0
            )

        def health(self):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def warm_up(self) -> bool:
            return True

    bounded = BoundedModelClient(SlowClient(), 1)
    worker = threading.Thread(target=final_card, args=(PRESET_A.request, bounded))
    worker.start()
    assert entered.wait(5)

    card = final_card(PRESET_A.request, bounded)  # the only slot is busy

    release.set()
    worker.join(5)
    assert card.source is Source.RULES
    assert card.model_note == MODEL_UNAVAILABLE_NOTE


def test_ac_015_2_max_model_calls_is_validated() -> None:
    from openmedcheck.config import Config, ConfigError

    assert Config.from_env({"OPENMEDCHECK_MAX_MODEL_CALLS": "2"}).max_model_calls == 2
    for bad in ("0", "65", "x"):
        with pytest.raises(ConfigError):
            Config.from_env({"OPENMEDCHECK_MAX_MODEL_CALLS": bad})
