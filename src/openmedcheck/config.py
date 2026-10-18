"""Environment-based configuration with the loopback guard (AC-011.3, AC-011.4)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Raised when the environment holds an invalid or disallowed setting."""


def is_loopback_host(host: str) -> bool:
    """True only for ``localhost``, ``127.0.0.1`` and ``::1``.

    Deliberately narrower than ``ipaddress.is_loopback`` so it matches the trusted-host
    list in ``web`` (other 127.x.x.x addresses are refused).
    """
    return host.strip("[]").lower() in {"localhost", "127.0.0.1", "::1"}


_HOSTNAME = re.compile(
    r"(?=.{1,253}\Z)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*"
)
_API_KEY = re.compile(r"[\x21-\x7e]{1,512}")  # printable ASCII, no whitespace (header-safe)


@dataclass(frozen=True)
class Config:
    host: str = "127.0.0.1"
    port: int = 8000
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "gemma4:e4b"
    model_timeout_s: float = 10.0
    allow_nonlocal: bool = False
    public_hosts: tuple[str, ...] = ()
    # Secret (AC-015.2): excluded from repr so it never reaches logs or tracebacks.
    ollama_api_key: str = field(default="", repr=False)
    # Concurrent model calls; beyond it a check gets the rules-only card at once (REQ-005).
    max_model_calls: int = 4

    @property
    def hosted(self) -> bool:
        """Hosted demo profile (AC-015.1): non-local mode plus a non-loopback public host."""
        return self.allow_nonlocal and any(not is_loopback_host(h) for h in self.public_hosts)

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Config:
        """Build and validate a Config from ``OPENMEDCHECK_*`` variables."""
        defaults = cls()
        config = cls(
            host=env.get("OPENMEDCHECK_HOST", defaults.host),
            port=_parse_port(env.get("OPENMEDCHECK_PORT") or env.get("PORT") or str(defaults.port)),
            ollama_url=env.get("OPENMEDCHECK_OLLAMA_URL", defaults.ollama_url),
            model=env.get("OPENMEDCHECK_MODEL", defaults.model),
            model_timeout_s=_parse_timeout(
                env.get("OPENMEDCHECK_MODEL_TIMEOUT_S", str(defaults.model_timeout_s))
            ),
            allow_nonlocal=env.get("OPENMEDCHECK_ALLOW_NONLOCAL", "0") == "1",
            public_hosts=_parse_public_hosts(env.get("OPENMEDCHECK_PUBLIC_HOSTS", "")),
            ollama_api_key=env.get("OPENMEDCHECK_OLLAMA_API_KEY", "").strip(),
            max_model_calls=_parse_max_calls(env.get("OPENMEDCHECK_MAX_MODEL_CALLS", "4")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Refuse a non-loopback bind host or Ollama URL unless explicitly allowed."""
        if not self.model:
            raise ConfigError("OPENMEDCHECK_MODEL must not be empty")
        ollama_host = _validated_ollama_host(self.ollama_url)
        if self.public_hosts and not self.allow_nonlocal:
            raise ConfigError("OPENMEDCHECK_PUBLIC_HOSTS requires OPENMEDCHECK_ALLOW_NONLOCAL=1")
        if self.ollama_api_key:
            if not _API_KEY.fullmatch(self.ollama_api_key):
                raise ConfigError("OPENMEDCHECK_OLLAMA_API_KEY has an invalid format")
            if urlsplit(self.ollama_url).scheme != "https" and not is_loopback_host(ollama_host):
                raise ConfigError(
                    "OPENMEDCHECK_OLLAMA_API_KEY requires an https:// OPENMEDCHECK_OLLAMA_URL"
                )
        # A public demo must never call a remote model in clear text or without the proxy key.
        remote_model = self.hosted and not is_loopback_host(ollama_host)
        insecure = urlsplit(self.ollama_url).scheme != "https" or not self.ollama_api_key
        if remote_model and insecure:
            raise ConfigError(
                "the hosted profile needs an https:// OPENMEDCHECK_OLLAMA_URL and "
                "OPENMEDCHECK_OLLAMA_API_KEY for a remote model"
            )
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


def _parse_public_hosts(raw: str) -> tuple[str, ...]:
    hosts = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    for host in hosts:
        if not _HOSTNAME.fullmatch(host):
            raise ConfigError("OPENMEDCHECK_PUBLIC_HOSTS must be comma-separated host names")
    return hosts


def _parse_max_calls(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError("OPENMEDCHECK_MAX_MODEL_CALLS must be an integer") from None
    if not 1 <= value <= 64:
        raise ConfigError("OPENMEDCHECK_MAX_MODEL_CALLS must be between 1 and 64")
    return value


def _parse_port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError("OPENMEDCHECK_PORT (or PORT) must be an integer") from None
    if not 1 <= port <= 65535:
        raise ConfigError("OPENMEDCHECK_PORT (or PORT) must be between 1 and 65535")
    return port


def _parse_timeout(raw: str) -> float:
    try:
        timeout = float(raw)
    except ValueError:
        raise ConfigError("OPENMEDCHECK_MODEL_TIMEOUT_S must be a number") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ConfigError("OPENMEDCHECK_MODEL_TIMEOUT_S must be a positive, finite number")
    return timeout
