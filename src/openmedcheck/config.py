"""Environment-based configuration with the loopback guard (AC-011.3, AC-011.4)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Raised when the environment holds an invalid or disallowed setting."""


def is_loopback_host(host: str) -> bool:
    """True only for ``localhost``, ``127.0.0.1`` and ``::1``.

    Deliberately narrower than ``ipaddress.is_loopback`` so it matches the trusted-host
    list in ``web`` (other 127.x.x.x addresses are refused).
    """
    return host.strip("[]").lower() in {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 8000
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "gemma4:e4b"
    model_timeout_s: float = 10.0
    allow_nonlocal: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        """Build and validate a Config from ``OPENMEDCHECK_*`` variables."""
        defaults = cls()
        config = cls(
            host=env.get("OPENMEDCHECK_HOST", defaults.host),
            port=_parse_port(env.get("OPENMEDCHECK_PORT", str(defaults.port))),
            ollama_url=env.get("OPENMEDCHECK_OLLAMA_URL", defaults.ollama_url),
            model=env.get("OPENMEDCHECK_MODEL", defaults.model),
            model_timeout_s=_parse_timeout(
                env.get("OPENMEDCHECK_MODEL_TIMEOUT_S", str(defaults.model_timeout_s))
            ),
            allow_nonlocal=env.get("OPENMEDCHECK_ALLOW_NONLOCAL", "0") == "1",
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Refuse a non-loopback bind host or Ollama URL unless explicitly allowed."""
        if not self.model:
            raise ConfigError("OPENMEDCHECK_MODEL must not be empty")
        ollama_host = _validated_ollama_host(self.ollama_url)
        if self.allow_nonlocal:
            return
        if not is_loopback_host(self.host):
            raise ConfigError(
                "OPENMEDCHECK_HOST is not a loopback address; "
                "set OPENMEDCHECK_ALLOW_NONLOCAL=1 to override"
            )
        if not is_loopback_host(ollama_host):
            raise ConfigError(
                "OPENMEDCHECK_OLLAMA_URL is not a loopback address; "
                "set OPENMEDCHECK_ALLOW_NONLOCAL=1 to override"
            )


def _validated_ollama_host(url: str) -> str:
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port  # raises ValueError for a non-numeric or out-of-range port
    except ValueError:
        raise ConfigError("OPENMEDCHECK_OLLAMA_URL is not a valid URL") from None
    if parts.scheme not in {"http", "https"} or host is None:
        raise ConfigError("OPENMEDCHECK_OLLAMA_URL must be an http(s) URL with a host")
    return host


def _parse_port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError("OPENMEDCHECK_PORT must be an integer") from None
    if not 1 <= port <= 65535:
        raise ConfigError("OPENMEDCHECK_PORT must be between 1 and 65535")
    return port


def _parse_timeout(raw: str) -> float:
    try:
        timeout = float(raw)
    except ValueError:
        raise ConfigError("OPENMEDCHECK_MODEL_TIMEOUT_S must be a number") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ConfigError("OPENMEDCHECK_MODEL_TIMEOUT_S must be a positive, finite number")
    return timeout
