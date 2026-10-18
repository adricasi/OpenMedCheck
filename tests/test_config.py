from __future__ import annotations

import pytest

from openmedcheck.config import Config, ConfigError, is_loopback_host


def test_ac_011_3_defaults_are_documented_values() -> None:
    config = Config.from_env({})

    assert config == Config(
        host="127.0.0.1",
        port=8000,
        ollama_url="http://127.0.0.1:11434",
        model="gemma4:e4b",
        model_timeout_s=10.0,
        allow_nonlocal=False,
    )


def test_ac_011_3_values_come_from_environment() -> None:
    config = Config.from_env(
        {
            "OPENMEDCHECK_PORT": "9001",
            "OPENMEDCHECK_OLLAMA_URL": "http://localhost:5555",
            "OPENMEDCHECK_MODEL": "other:tag",
            "OPENMEDCHECK_MODEL_TIMEOUT_S": "2.5",
        }
    )

    assert (config.port, config.ollama_url, config.model, config.model_timeout_s) == (
        9001,
        "http://localhost:5555",
        "other:tag",
        2.5,
    )


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.org"])  # noqa: S104
def test_ac_011_4_non_loopback_host_is_refused(host: str) -> None:
    with pytest.raises(ConfigError, match="OPENMEDCHECK_HOST"):
        Config.from_env({"OPENMEDCHECK_HOST": host})


@pytest.mark.parametrize("url", ["http://10.0.0.5:11434", "https://ollama.example.com"])
def test_ac_011_4_non_loopback_ollama_url_is_refused(url: str) -> None:
    with pytest.raises(ConfigError, match="OPENMEDCHECK_OLLAMA_URL"):
        Config.from_env({"OPENMEDCHECK_OLLAMA_URL": url})


def test_ac_011_4_non_loopback_is_allowed_with_the_flag() -> None:
    config = Config.from_env(
        {
            "OPENMEDCHECK_HOST": "0.0.0.0",  # noqa: S104
            "OPENMEDCHECK_OLLAMA_URL": "http://gemma.internal:11434",
            "OPENMEDCHECK_ALLOW_NONLOCAL": "1",
        }
    )

    assert config.host == "0.0.0.0"  # noqa: S104


def test_ac_011_4_flag_other_than_1_does_not_allow() -> None:
    with pytest.raises(ConfigError):
        Config.from_env({"OPENMEDCHECK_HOST": "0.0.0.0", "OPENMEDCHECK_ALLOW_NONLOCAL": "true"})  # noqa: S104


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "[::1]", "localhost", "LOCALHOST"])
def test_loopback_hosts_are_recognised(host: str) -> None:
    assert is_loopback_host(host)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPENMEDCHECK_PORT", "abc"),
        ("OPENMEDCHECK_PORT", "0"),
        ("OPENMEDCHECK_PORT", "70000"),
        ("OPENMEDCHECK_MODEL_TIMEOUT_S", "fast"),
        ("OPENMEDCHECK_MODEL_TIMEOUT_S", "0"),
        ("OPENMEDCHECK_MODEL_TIMEOUT_S", "nan"),
        ("OPENMEDCHECK_MODEL_TIMEOUT_S", "inf"),
        ("OPENMEDCHECK_MODEL", ""),
        ("OPENMEDCHECK_OLLAMA_URL", "not-a-url"),
        ("OPENMEDCHECK_OLLAMA_URL", "ftp://127.0.0.1:11434"),
        ("OPENMEDCHECK_OLLAMA_URL", "file:///etc/passwd"),
        ("OPENMEDCHECK_OLLAMA_URL", "http://127.0.0.1:notaport"),
        ("OPENMEDCHECK_OLLAMA_URL", "http://127.0.0.1:99999"),
    ],
)
def test_invalid_values_are_rejected(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        Config.from_env({name: value})


def test_ac_011_4_other_127_addresses_are_refused() -> None:
    with pytest.raises(ConfigError, match="OPENMEDCHECK_HOST"):
        Config.from_env({"OPENMEDCHECK_HOST": "127.0.0.2"})
    assert not is_loopback_host("127.0.0.2")
